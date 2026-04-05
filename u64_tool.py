#!/usr/bin/env python3
"""Ultimate 64 automation tool for Habitat C64 client testing.

Wraps the Ultimate 64 REST API (port 80) for remote control: pushing disk
images, reading/writing memory, resetting, injecting keystrokes, etc.

Requires firmware >= 3.11 with network enabled.
Uses only stdlib (urllib) — no pip install needed.

Usage:
    from u64_tool import U64Session

    u = U64Session("192.168.2.64")
    u.mount_disk("a", "Dist/Habitat-A.d64")
    u.reset()
    time.sleep(20)
    u.read_byte(0x0210)  # check ACIA flag

Environment:
    U64_HOST: Default IP address of the Ultimate 64.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

PROJECT = os.path.dirname(os.path.abspath(__file__))
DEFAULT_HOST = os.environ.get("U64_HOST", "192.168.1.158")

# PETSCII screen code → ASCII lookup (upper/graphics charset)
SCREEN_TO_ASCII = {}
for i in range(26):
    SCREEN_TO_ASCII[i + 1] = chr(0x41 + i)  # A-Z
for i in range(10):
    SCREEN_TO_ASCII[0x30 + i] = chr(0x30 + i)  # 0-9
SCREEN_TO_ASCII[0x20] = " "
SCREEN_TO_ASCII[0x2E] = "."
SCREEN_TO_ASCII[0x2D] = "-"
SCREEN_TO_ASCII[0x2B] = "+"
SCREEN_TO_ASCII[0x2A] = "*"
SCREEN_TO_ASCII[0x2F] = "/"
SCREEN_TO_ASCII[0x3A] = ":"
SCREEN_TO_ASCII[0x00] = "@"


def _multipart_encode(fields, files):
    """Build a multipart/form-data body. Returns (content_type, body)."""
    boundary = "----U64Boundary" + str(int(time.time()))
    parts = []
    for key, val in fields.items():
        parts.append(f"--{boundary}\r\n"
                     f"Content-Disposition: form-data; name=\"{key}\"\r\n\r\n"
                     f"{val}\r\n".encode())
    for key, (filename, data) in files.items():
        parts.append(f"--{boundary}\r\n"
                     f"Content-Disposition: form-data; name=\"{key}\"; filename=\"{filename}\"\r\n"
                     f"Content-Type: application/octet-stream\r\n\r\n".encode()
                     + data + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    content_type = f"multipart/form-data; boundary={boundary}"
    return content_type, body


class U64Session:
    """Manages a remote Ultimate 64 session via its REST API."""

    def __init__(self, host=None, password=None, verbose=True):
        self.host = host or DEFAULT_HOST
        self.base = f"http://{self.host}/v1"
        self.password = password
        self.verbose = verbose

    # ── HTTP helpers ──────────────────────────────────────────────────

    def _request(self, method, url, data=None, headers=None, timeout=10):
        """Make an HTTP request. Returns response body as bytes."""
        req = urllib.request.Request(url, data=data, method=method)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {e.code} {method} {url}: {body}") from e

    def _get(self, endpoint, timeout=10, **params):
        """GET request."""
        url = f"{self.base}/{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return self._request("GET", url, timeout=timeout)

    def _put(self, endpoint, timeout=10, **params):
        """PUT request."""
        url = f"{self.base}/{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return self._request("PUT", url, timeout=timeout)

    def _post_multipart(self, endpoint, fields, files, timeout=30):
        """POST with multipart/form-data body."""
        url = f"{self.base}/{endpoint}"
        content_type, body = _multipart_encode(fields, files)
        return self._request("POST", url, data=body,
                             headers={"Content-Type": content_type},
                             timeout=timeout)

    def _post_binary(self, endpoint, data, timeout=10, **params):
        """POST with raw binary body."""
        url = f"{self.base}/{endpoint}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return self._request("POST", url, data=data,
                             headers={"Content-Type": "application/octet-stream"},
                             timeout=timeout)

    # ── Machine control ────────────────────────────────────────────────

    def reset(self):
        """Reset the C64 (preserves configuration)."""
        self._put("machine:reset")

    def reboot(self):
        """Reboot with cartridge reinit."""
        self._put("machine:reboot")

    def pause(self):
        """Pause CPU via DMA line."""
        self._put("machine:pause")

    def resume(self):
        """Resume CPU from pause."""
        self._put("machine:resume")

    def poweroff(self):
        """Power off (U64 only)."""
        self._put("machine:poweroff")

    # ── Memory access ──────────────────────────────────────────────────

    def read_mem(self, addr, length=256):
        """Read memory. Returns bytes."""
        return self._get("machine:readmem",
                         address=f"{addr:04X}", length=str(length))

    def read_byte(self, addr):
        """Read a single byte. Returns int 0-255."""
        data = self.read_mem(addr, 1)
        return data[0] if data else None

    def read_word(self, addr):
        """Read a 16-bit little-endian word. Returns int."""
        data = self.read_mem(addr, 2)
        if len(data) >= 2:
            return data[0] | (data[1] << 8)
        return None

    def write_mem(self, addr, data):
        """Write binary data to memory via POST body."""
        self._post_binary("machine:writemem", data, address=f"{addr:04X}")

    def write_byte(self, addr, val):
        """Write a single byte via hex query parameter."""
        self._put("machine:writemem", address=f"{addr:04X}", data=f"{val:02X}")

    def write_bytes(self, addr, data):
        """Write multiple bytes."""
        if isinstance(data, (list, tuple)):
            data = bytes(data)
        self.write_mem(addr, data)

    # ── Disk management ────────────────────────────────────────────────

    def mount_disk(self, drive, d64_path, mode="readwrite"):
        """Upload and mount a D64 disk image on the given drive (a or b)."""
        with open(d64_path, "rb") as f:
            file_data = f.read()
        # Send type/mode as query params; file as multipart body
        endpoint = f"drives/{drive}:mount?type=d64&mode={mode}"
        self._post_multipart(
            endpoint,
            fields={},
            files={"file": (os.path.basename(d64_path), file_data)},
        )
        self._log(f"Mounted {os.path.basename(d64_path)} on drive {drive}")

    def remove_disk(self, drive):
        """Unmount disk from drive."""
        self._put(f"drives/{drive}:remove")

    def reset_drive(self, drive):
        """Reset a drive."""
        self._put(f"drives/{drive}:reset")

    # ── Program loading ────────────────────────────────────────────────

    def run_prg(self, prg_path):
        """Upload and run a PRG file."""
        with open(prg_path, "rb") as f:
            file_data = f.read()
        self._post_multipart(
            "runners:run_prg",
            fields={},
            files={"file": (os.path.basename(prg_path), file_data)},
        )
        self._log(f"Running {os.path.basename(prg_path)}")

    def load_prg(self, prg_path):
        """Upload a PRG file without running it."""
        with open(prg_path, "rb") as f:
            file_data = f.read()
        self._post_multipart(
            "runners:load_prg",
            fields={},
            files={"file": (os.path.basename(prg_path), file_data)},
        )

    # ── Configuration ──────────────────────────────────────────────────

    def get_version(self):
        """Get firmware version info."""
        data = self._get("version")
        return json.loads(data)

    def get_config(self, category, item=None):
        """Get configuration value(s)."""
        endpoint = f"configs/{urllib.parse.quote(category)}"
        if item:
            endpoint += f"/{urllib.parse.quote(item)}"
        data = self._get(endpoint)
        return json.loads(data)

    def set_config(self, category, item, value):
        """Set a configuration value."""
        cat = urllib.parse.quote(category)
        itm = urllib.parse.quote(item)
        self._put(f"configs/{cat}/{itm}", value=str(value))

    def configure_habitat(self):
        """Configure U64 modem and cartridge settings for Habitat via API."""
        settings = {
            "Modem Settings": {
                "Modem Interface": "ACIA / SwiftLink",
                "ACIA (6551) Mapping": "DF80/NMI",
                "Hardware Mode": "SwiftLink",
                "Drop connection on DTR low": "Disabled",
                "CTS Behavior": "Active (Low)",
                "DCD Behavior": "Active when connected",
                "DSR Behavior": "Active when connected",
                "Set Socket Opt TCP_NODELAY": "Enabled",
            },
            "C64 and Cartridge Settings": {
                "Command Interface": "Enabled",
            },
        }
        for cat, items in settings.items():
            for item, value in items.items():
                self._log(f"  {item} = {value}")
                self.set_config(cat, item, value)

        # Force ACIA reinit: firmware ignores set-to-same-value,
        # so map to DE00 first, then to DF80 to trigger actual remap
        self._log("  Reinitializing ACIA...")
        self.set_config("Modem Settings", "ACIA (6551) Mapping", "DE00/NMI")
        time.sleep(2)
        self.set_config("Modem Settings", "ACIA (6551) Mapping", "DF80/NMI")
        self._log("  Modem ready.")

    # ── Keystroke injection ────────────────────────────────────────────

    def inject_keys(self, *petscii_codes):
        """Inject keystrokes into the KERNAL keyboard buffer at $0277.

        Pauses CPU, writes to buffer, resumes. Max 10 keys.
        """
        n = min(len(petscii_codes), 10)
        self.pause()
        time.sleep(0.1)
        self.write_mem(0x00C6, bytes([n]))
        self.write_mem(0x0277, bytes(petscii_codes[:n]))
        self.resume()

    @staticmethod
    def _ascii_to_petscii(c):
        """Convert ASCII character to PETSCII for keyboard buffer."""
        code = ord(c)
        if 0x61 <= code <= 0x7A:  # lowercase a-z
            return code - 0x20    # PETSCII: $41-$5A
        if 0x41 <= code <= 0x5A:  # uppercase A-Z
            return code + 0x80    # PETSCII: $C1-$DA
        return code

    def type_text(self, text):
        """Type a string via KERNAL keyboard buffer. Appends Return."""
        codes = [self._ascii_to_petscii(c) for c in text] + [0x0D]
        self.inject_keys(*codes)

    # ── Screen reading ─────────────────────────────────────────────────

    def read_screen(self, row=None):
        """Read screen RAM ($0400-$07E7). Returns 25 rows of 40 columns.

        If row is specified, returns just that row as ASCII string.
        """
        data = self.read_mem(0x0400, 1000)
        rows = []
        for r in range(25):
            row_data = data[r * 40 : (r + 1) * 40]
            text = ""
            for b in row_data:
                text += SCREEN_TO_ASCII.get(b, "?")
            rows.append(text)
        if row is not None:
            return rows[row] if 0 <= row < 25 else ""
        return rows

    def dump_screen(self):
        """Print all 25 screen rows."""
        rows = self.read_screen()
        for i, r in enumerate(rows):
            self._log(f"  [{i:2d}] {r}")
        return rows

    def wait_for_screen_text(self, text, row=None, timeout=60, interval=2):
        """Poll screen RAM until text appears. Returns True if found."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if row is not None:
                    screen = self.read_screen(row)
                    if text.upper() in screen.upper():
                        return True
                else:
                    rows = self.read_screen()
                    for r in rows:
                        if text.upper() in r.upper():
                            return True
            except Exception as e:
                self._log(f"  (screen poll error: {e})")
            time.sleep(interval)
        return False

    # ── Display helpers ────────────────────────────────────────────────

    def dump(self, addr, length, label=""):
        """Dump a memory region in hex+ASCII format."""
        data = self.read_mem(addr, length)
        if data:
            if label:
                print(f"\n{label}:")
            for i in range(0, len(data), 16):
                chunk = data[i:i+16]
                hex_str = ' '.join(f'{b:02X}' for b in chunk)
                ascii_str = ''.join(chr(b) if 0x20 <= b < 0x7F else '.' for b in chunk)
                print(f"  ${addr+i:04X}: {hex_str:<48s} {ascii_str}")
            return data
        else:
            print(f"  Failed to read ${addr:04X}-${addr+length-1:04X}")
            return None

    def disassemble(self, addr, length=32):
        """Simple 6502 disassembly of memory at addr."""
        data = self.read_mem(addr, length)
        if not data:
            print(f"  Failed to read ${addr:04X}")
            return
        OPCODES = {
            0x00: ("BRK", 1), 0x40: ("RTI", 1), 0x60: ("RTS", 1),
            0x4C: ("JMP", 3), 0x6C: ("JMP()", 3), 0x20: ("JSR", 3),
            0x78: ("SEI", 1), 0x58: ("CLI", 1), 0x38: ("SEC", 1),
            0x18: ("CLC", 1), 0xEA: ("NOP", 1), 0xE6: ("INC zp", 2),
            0xC6: ("DEC zp", 2), 0xE8: ("INX", 1), 0xC8: ("INY", 1),
            0xCA: ("DEX", 1), 0x88: ("DEY", 1),
            0xA0: ("LDY #", 2), 0xA2: ("LDX #", 2), 0xA9: ("LDA #", 2),
            0xBA: ("TSX", 1), 0x9A: ("TXS", 1), 0xAA: ("TAX", 1),
            0xA8: ("TAY", 1), 0x8A: ("TXA", 1), 0x98: ("TYA", 1),
            0x48: ("PHA", 1), 0x68: ("PLA", 1), 0x08: ("PHP", 1), 0x28: ("PLP", 1),
            0xD0: ("BNE", 2), 0xF0: ("BEQ", 2), 0x30: ("BMI", 2),
            0x10: ("BPL", 2), 0x90: ("BCC", 2), 0xB0: ("BCS", 2),
            0x8D: ("STA", 3), 0xAD: ("LDA", 3), 0x8E: ("STX", 3), 0xAE: ("LDX", 3),
            0x8C: ("STY", 3), 0xAC: ("LDY", 3),
            0x9D: ("STA,X", 3), 0xBD: ("LDA,X", 3),
            0x85: ("STA zp", 2), 0xA5: ("LDA zp", 2),
            0x86: ("STX zp", 2), 0xA6: ("LDX zp", 2),
            0x84: ("STY zp", 2), 0xA4: ("LDY zp", 2),
            0xCD: ("CMP", 3), 0xC9: ("CMP #", 2), 0xC5: ("CMP zp", 2),
            0xEC: ("CPX", 3), 0xE0: ("CPX #", 2), 0xCC: ("CPY", 3), 0xC0: ("CPY #", 2),
            0x29: ("AND #", 2), 0x09: ("ORA #", 2), 0x49: ("EOR #", 2),
            0x2D: ("AND", 3), 0x0D: ("ORA", 3), 0x4D: ("EOR", 3),
            0xEE: ("INC", 3), 0xCE: ("DEC", 3),
            0x4A: ("LSR A", 1), 0x0A: ("ASL A", 1), 0x6A: ("ROR A", 1), 0x2A: ("ROL A", 1),
        }
        i = 0
        while i < len(data):
            op = data[i]
            mnemonic, size = OPCODES.get(op, (f".byte ${op:02X}", 1))
            if i + size > len(data):
                break
            hex_bytes = ' '.join(f'{data[i+j]:02X}' for j in range(min(size, len(data)-i)))
            if size == 1:
                print(f"  ${addr+i:04X}: {hex_bytes:<9s} {mnemonic}")
            elif size == 2:
                operand = data[i+1] if i+1 < len(data) else 0
                if mnemonic.startswith("B") and mnemonic not in ("BRK",):
                    target = addr + i + 2 + (operand if operand < 128 else operand - 256)
                    print(f"  ${addr+i:04X}: {hex_bytes:<9s} {mnemonic} ${target:04X}")
                else:
                    print(f"  ${addr+i:04X}: {hex_bytes:<9s} {mnemonic} ${operand:02X}")
            elif size == 3:
                lo = data[i+1] if i+1 < len(data) else 0
                hi = data[i+2] if i+2 < len(data) else 0
                print(f"  ${addr+i:04X}: {hex_bytes:<9s} {mnemonic} ${hi:02X}{lo:02X}")
            i += size

    # ── CRT upload ───────────────────────────────────────────────────

    def upload_crt(self, crt_path=None):
        """Upload CRT file to U64 via FTP."""
        import ftplib
        crt_path = crt_path or os.path.join(PROJECT, "Dist", "Habitat.crt")
        if not os.path.exists(crt_path):
            raise FileNotFoundError(f"{crt_path} not found")
        files = [
            (crt_path, "Habitat.crt"),
            (os.path.join(PROJECT, "Dist", "habitat-u64.cfg"), "habitat-u64.cfg"),
        ]
        self._log(f"Uploading to {self.host} via FTP...")
        ftp = ftplib.FTP(self.host)
        ftp.login()
        lines = []
        ftp.retrlines('NLST', lines.append)
        usb = next((d for d in lines if d.upper().startswith("USB")), None)
        if not usb:
            ftp.quit()
            raise RuntimeError(f"No USB drive found. Available: {', '.join(lines)}")
        ftp.cwd(usb)
        try:
            ftp.cwd("HABICART")
        except ftplib.error_perm:
            ftp.mkd("HABICART")
            ftp.cwd("HABICART")
        for local, remote in files:
            if os.path.exists(local):
                sz = os.path.getsize(local)
                self._log(f"  {remote} ({sz:,} bytes)")
                with open(local, 'rb') as f:
                    ftp.storbinary(f"STOR {remote}", f)
        ftp.quit()
        self._log(f"Done. Files in {usb}/HABICART/")

    # ── Crash diagnostics ────────────────────────────────────────────

    def diagnose(self):
        """Read key memory locations to diagnose crash state.

        Pauses the CPU and dumps: CPU port, SFX entry, NMI/IRQ vectors,
        stack, decompressor, VIC state, ACIA state, EasyFlash state,
        game entry point, and flag bytes.
        """
        print(f"=== U64 Crash Diagnostics ({self.host}) ===\n")

        self.pause()

        # CPU port register
        port = self.read_byte(0x0001)
        if port is not None:
            print(f"\n$01 (CPU port): ${port:02X}")
            states = {
                0x37: "KERNAL+BASIC+IO (normal / post-decompression)",
                0x38: "All RAM (Exomizer decompression in progress)",
                0x36: "cc65 default (launcher still running?)",
                0x35: "IO+RAM (BASIC off, KERNAL off)",
                0x34: "All RAM + IO (no ROMs)",
            }
            print(f"  -> {states.get(port, 'Unexpected value!')}")

        # SFX entry area
        self.dump(0x080D, 10, "SFX entry ($080D-$0816)")

        # NMI/IRQ vectors in RAM
        self.dump(0xFFFA, 6, "Hardware vectors in RAM ($FFFA-$FFFF)")
        nmi = self.read_word(0xFFFA)
        irq = self.read_word(0xFFFE)
        if nmi is not None:
            print(f"  NMI vector: ${nmi:04X}")
        if irq is not None:
            print(f"  IRQ vector: ${irq:04X}")

        # Stack area
        self.dump(0x01F0, 16, "Stack top ($01F0-$01FF)")
        self.dump(0x0100, 32, "Stack page ($0100-$011F)")

        # Zero page Exomizer vars
        self.dump(0x00FD, 3, "ZP vars ($FD-$FF)")

        # Decompressor area
        self.dump(0x5DC0, 48, "Decompressor ($5DC0-$5DEF)")
        print("  Disassembly:")
        self.disassemble(0x5DC0, 48)

        # VIC state
        border = self.read_byte(0xD020)
        bg = self.read_byte(0xD021)
        d011 = self.read_byte(0xD011)
        if border is not None:
            print(f"\n$D020 (border): ${border:02X}")
        if bg is not None:
            print(f"$D021 (bg): ${bg:02X}")
        if d011 is not None:
            print(f"$D011 (VIC ctrl): ${d011:02X}")

        # ACIA state
        self.dump(0xDF80, 4, "ACIA registers ($DF80-$DF83)")

        # EasyFlash state
        self.dump(0xDE00, 3, "EasyFlash regs ($DE00-$DE02)")

        # Game entry point
        self.dump(0x0816, 16, "Game entry ($0816-$0825)")
        print("  Disassembly:")
        self.disassemble(0x0816, 16)

        # Flags
        self.dump(0x0210, 3, "Flags: use_acia($0210) / use_cart($0211) / disk_b_base($0212)")

        # Debug register
        try:
            debug = self.read_byte(0xD7FF)
            if debug is not None:
                print(f"\nDebug register ($D7FF): ${debug:02X}")
        except Exception:
            pass

        print("\n=== Done. CPU still paused. Use u.resume() to continue. ===")

    def check_boot_state(self):
        """Quick check of boot progress indicators (pauses CPU)."""
        self.pause()
        port = self.read_byte(0x0001)
        border = self.read_byte(0xD020)
        nmi_vec = self.read_word(0xFFFA)
        irq_vec = self.read_word(0xFFFE)
        flags = self.read_mem(0x0210, 3)
        print(f"$01=${port:02X}  border=${border:02X}  "
              f"NMI=${nmi_vec:04X}  IRQ=${irq_vec:04X}  "
              f"flags={flags.hex() if flags else 'N/A'}")

    # ── Modem / ACIA helpers ────────────────────────────────────────────

    def modem_hangup(self):
        """Hang up the modem by toggling ACIA off and back on.

        Sets ACIA mapping to Off (calls acia.deinit, drops TCP connection),
        waits briefly, then re-enables at the current mapping (DF80/NMI).
        """
        self._log("Hanging up modem...")
        self._put('configs/Modem%20Settings/ACIA%20(6551)%20Mapping', value='Off')
        time.sleep(1)
        self._put('configs/Modem%20Settings/ACIA%20(6551)%20Mapping', value='DF80/NMI')
        self._log("Modem hung up and ACIA re-enabled.")

    def dial_modem(self, host="app.neohabitat.org:1986", acia_base=0xDF80):
        """Send ATDT command via DMA writes to ACIA registers.

        DMA writes bypass the C64 CPU and go directly through the U64's
        FPGA to the ACIA emulation.  acia_base defaults to $DF80 (current
        U64 modem config). Use $DE00 for stock SwiftLink address.
        """
        # Init ACIA
        self.write_byte(acia_base + 1, 0x00)   # STATUS = reset
        self.write_byte(acia_base + 2, 0x0B)   # COMMAND: DTR on, TX on
        self.write_byte(acia_base + 3, 0x18)   # CONTROL: 1200 baud, 8N1
        time.sleep(0.2)

        # Drain any stale RX data
        for _ in range(16):
            s = self.read_byte(acia_base + 1)
            if s & 0x08:
                self.read_byte(acia_base)
            else:
                break

        # Build and send AT command (lowercase hostname)
        cmd = f"ATDT{host}\r"
        self._log(f"DMA dial: {cmd.strip()}")
        for ch in cmd:
            self.write_byte(acia_base, ord(ch))
            time.sleep(0.05)  # 50ms per byte

    # ── Polling helpers ────────────────────────────────────────────────

    def wait_for_byte(self, addr, value, timeout=120, interval=2):
        """Poll a memory address until it equals value. Returns True/False."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                v = self.read_byte(addr)
                if v == value:
                    return True
            except Exception:
                pass
            time.sleep(interval)
        return False

    # ── Habitat boot helpers ───────────────────────────────────────────

    def boot_habitat(self, name="a", disk_a=None, disk_b=None,
                     dial_timeout=60, game_timeout=120):
        """Full boot sequence for Habitat on Ultimate 64."""
        disk_a = disk_a or os.path.join(PROJECT, "Dist", "Habitat-A.d64")
        disk_b = disk_b or os.path.join(PROJECT, "Dist", "Habitat-B.d64")

        P = self._log

        P("[1] Mount Disk A and reset...")
        self.mount_disk("a", disk_a)
        self.reset()

        P("[2] Wait for launcher splash...")
        if not self.wait_for_screen_text("HABITAT", timeout=30):
            P("WARNING: Splash screen not detected, continuing anyway")
        time.sleep(2)

        P("[3] Dismiss splash (Return)...")
        self.inject_keys(0x0D)
        time.sleep(5)

        P(f"[4] Type name '{name}' + Return...")
        self.type_text(name)

        P(f"[5] Wait for dial + connect + decompress ({dial_timeout}s)...")
        time.sleep(dial_timeout)

        P("[6] Mount Disk B...")
        self.mount_disk("b", disk_b)

        P(f"[7] Wait for game init ({game_timeout}s)...")
        time.sleep(game_timeout)

        P("[8] Check final state...")
        self.check_habitat_state()

    def check_habitat_state(self):
        """Read and report key Habitat game state."""
        P = self._log

        # Default addresses for swift branch (check SIZE file if they shift):
        initst_addr = 0x8D02    # INITST in protocol.obj (from all.sym)
        use_acia_addr = 0x9E50  # use_acia in farmers_variables.obj (from all.sym)

        try:
            initst = self.read_byte(initst_addr)
            P(f"  INITST @${initst_addr:04X} = ${initst:02X}"
              f" {'(handshake OK)' if initst == 0 else '(NOT ready)'}")
        except Exception as e:
            P(f"  INITST read failed: {e}")
            initst = None

        try:
            use_acia = self.read_byte(use_acia_addr)
            P(f"  use_acia @${use_acia_addr:04X} = ${use_acia:02X}"
              f" {'(SwiftLink)' if use_acia == 0xFF else '(Userport)'}")
        except Exception as e:
            P(f"  use_acia read failed: {e}")
            use_acia = None

        try:
            nmi_lo = self.read_byte(0x0318)
            nmi_hi = self.read_byte(0x0319)
            nmi = (nmi_hi << 8) | nmi_lo
            P(f"  NMI vector $0318 = ${nmi:04X}")
        except Exception as e:
            P(f"  NMI vector read failed: {e}")

        return {"initst": initst, "use_acia": use_acia}

    # ── Internal helpers ───────────────────────────────────────────────

    def deploy_cart(self, dest=None):
        """Deploy CRT + cfg + README to the U64 via FTP.

        Uploads Dist/Habitat.crt, Dist/habitat-u64.cfg, and
        Dist/README.txt to a HABICART directory on the U64.
        Auto-detects USB mount point. Creates directory if needed.
        """
        import ftplib

        files = [
            (os.path.join(PROJECT, "Dist", "Habitat.crt"), "Habitat.crt"),
            (os.path.join(PROJECT, "Dist", "habitat-u64.cfg"), "habitat-u64.cfg"),
            (os.path.join(PROJECT, "Dist", "README.txt"), "README.txt"),
        ]
        for local, _ in files:
            if not os.path.exists(local):
                raise FileNotFoundError(f"{local} not found — run ./dockercart first")

        self._log(f"Connecting to {self.host} via FTP...")
        ftp = ftplib.FTP(self.host)
        ftp.login()  # anonymous / no password

        if dest is None:
            # Auto-detect USB mount point
            lines = []
            ftp.retrlines('NLST', lines.append)
            usb = next((d for d in lines if d.upper().startswith("USB")), None)
            if not usb:
                ftp.quit()
                raise RuntimeError(f"No USB drive found. Available: {', '.join(lines)}")
            dest = f"{usb}/HABICART"
            self._log(f"Found USB drive: {usb}")

        # Navigate to destination, creating directories as needed
        for part in dest.strip("/").split("/"):
            try:
                ftp.cwd(part)
            except ftplib.error_perm:
                ftp.mkd(part)
                self._log(f"Created {part}/")
                ftp.cwd(part)

        for local, remote in files:
            size = os.path.getsize(local)
            self._log(f"  Uploading {remote} ({size:,} bytes)...")
            with open(local, 'rb') as f:
                ftp.storbinary(f"STOR {remote}", f)

        ftp.quit()
        self._log(f"Files deployed to {dest}/")

        # Configure modem/cartridge settings via API
        self._log("Configuring U64 settings...")
        self.configure_habitat()
        self._log("Deploy complete! Run Habitat.crt from the U64 file browser.")

    def _log(self, msg):
        if self.verbose:
            print(msg, flush=True)


# ── CLI ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Ultimate 64 automation for Habitat")
    parser.add_argument("host", nargs="?", default=DEFAULT_HOST,
                        help=f"U64 IP address (default: {DEFAULT_HOST})")
    parser.add_argument("--version", action="store_true", help="Print firmware version")
    parser.add_argument("--reset", action="store_true", help="Reset machine")
    parser.add_argument("--pause", action="store_true", help="Pause CPU")
    parser.add_argument("--resume", action="store_true", help="Resume CPU")
    parser.add_argument("--screen", action="store_true", help="Dump screen contents")
    parser.add_argument("--mount-a", metavar="D64", help="Mount D64 on drive A")
    parser.add_argument("--mount-b", metavar="D64", help="Mount D64 on drive B")
    parser.add_argument("--run", metavar="PRG", help="Upload and run PRG")
    parser.add_argument("--crt", metavar="CRT", help="Upload and run CRT cartridge")
    parser.add_argument("--read", metavar="ADDR", help="Read byte at hex address")
    parser.add_argument("--dump", nargs=2, metavar=("ADDR", "LEN"),
                        help="Dump memory region (hex addr and length)")
    parser.add_argument("--disasm", nargs=2, metavar=("ADDR", "LEN"),
                        help="Disassemble memory (hex addr and length)")
    parser.add_argument("--write", nargs=2, metavar=("ADDR", "VAL"),
                        help="Write byte (hex addr and value)")
    parser.add_argument("--deploy-cart", action="store_true",
                        help="Deploy CRT + cfg + README to USB via FTP and configure U64")
    parser.add_argument("--configure", action="store_true",
                        help="Configure U64 modem/cartridge settings for Habitat")
    parser.add_argument("--diagnose", action="store_true", help="Full crash diagnostics")
    parser.add_argument("--boot-state", action="store_true", help="Quick boot state check")
    parser.add_argument("--boot", metavar="NAME", help="Full Habitat boot with given name")
    parser.add_argument("--check", action="store_true", help="Check Habitat game state")
    args = parser.parse_args()

    u = U64Session(host=args.host)

    try:
        if args.version:
            print(u.get_version())
        if args.reset:
            u.reset()
            print("Reset sent.")
        if args.pause:
            u.pause()
        if args.resume:
            u.resume()
        if args.screen:
            u.dump_screen()
        if args.mount_a:
            u.mount_disk("a", args.mount_a)
        if args.mount_b:
            u.mount_disk("b", args.mount_b)
        if args.run:
            u.run_prg(args.run)
        if args.crt:
            u.upload_crt(args.crt)
        if args.deploy_cart:
            u.deploy_cart()
        if args.configure:
            u.configure_habitat()
        if args.read:
            u.pause()
            addr = int(args.read, 16)
            val = u.read_byte(addr)
            print(f"${addr:04X} = ${val:02X} ({val})")
        if args.dump:
            u.pause()
            addr = int(args.dump[0], 16)
            length = int(args.dump[1], 16)
            u.dump(addr, length)
        if args.disasm:
            u.pause()
            addr = int(args.disasm[0], 16)
            length = int(args.disasm[1], 16)
            u.disassemble(addr, length)
        if args.write:
            addr = int(args.write[0], 16)
            val = int(args.write[1], 16)
            u.write_byte(addr, val)
            print(f"${addr:04X} <- ${val:02X}")
        if args.diagnose:
            u.diagnose()
        if args.boot_state:
            u.check_boot_state()
        if args.check:
            u.check_habitat_state()
        if args.boot:
            u.boot_habitat(name=args.boot)
    except urllib.error.URLError as e:
        print(f"ERROR: Could not connect to Ultimate 64 at {args.host}: {e}",
              file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)
