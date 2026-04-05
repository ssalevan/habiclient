#!/usr/bin/env python3
"""Debug helper for Ultimate 64 via REST API.

Reads C64 memory via DMA to diagnose crash state.
Usage: python3 u64_debug.py [ip_address]
"""

import sys
import json
import urllib.request

IP = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.158"
BASE = f"http://{IP}"


def api_get(path):
    """GET request, return JSON."""
    url = f"{BASE}{path}"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def api_put(path):
    """PUT request, return JSON."""
    url = f"{BASE}{path}"
    try:
        req = urllib.request.Request(url, method='PUT', data=b'')
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"  ERROR: {e}")
        return None


def read_mem(addr, length=1):
    """Read C64 memory via DMA. Returns list of byte values."""
    result = api_get(f"/v1/machine:readmem?addr={addr:04X}&len={length:X}")
    if result and 'data' in result:
        return bytes.fromhex(result['data'])
    return None


def read_byte(addr):
    data = read_mem(addr, 1)
    return data[0] if data else None


def pause():
    print("Pausing CPU...")
    return api_put("/v1/machine:pause")


def resume():
    print("Resuming CPU...")
    return api_put("/v1/machine:resume")


def dump_region(addr, length, label=""):
    """Dump a memory region in hex."""
    data = read_mem(addr, length)
    if data:
        if label:
            print(f"\n{label}:")
        for i in range(0, len(data), 16):
            hex_str = ' '.join(f'{b:02X}' for b in data[i:i+16])
            print(f"  ${addr+i:04X}: {hex_str}")
        return data
    else:
        print(f"  Failed to read ${addr:04X}-${addr+length-1:04X}")
        return None


def diagnose_exomizer_crash():
    """Read key memory locations to diagnose Exomizer crash."""
    print(f"=== U64 Crash Diagnostics ({IP}) ===\n")

    print("Pausing CPU for memory inspection...")
    pause()

    # CPU port register
    port = read_byte(0x0001)
    if port is not None:
        print(f"\n$01 (CPU port): ${port:02X}")
        if port == 0x37:
            print("  → KERNAL+BASIC+IO visible (pre-Exomizer or post-decompression)")
        elif port == 0x38:
            print("  → All RAM (Exomizer decompression in progress)")
        elif port == 0x36:
            print("  → cc65 default (launcher still running?)")
        else:
            print(f"  → Unexpected value!")

    # SFX entry area
    dump_region(0x080D, 10, "SFX entry ($080D-$0816)")

    # NMI/IRQ vectors in RAM
    dump_region(0xFFFA, 6, "Hardware vectors in RAM ($FFFA-$FFFF)")

    # Stack area (where NMI would push)
    dump_region(0x01F0, 16, "Stack top ($01F0-$01FF)")

    # Stack page code (Exomizer decompressor)
    dump_region(0x0100, 32, "Stack page code ($0100-$011F)")

    # Zero page Exomizer vars
    dump_region(0x00FD, 3, "ZP vars ($FD-$FF)")

    # Decompressor area
    dump_region(0x5DC0, 32, "Decompressor ($5DC0-$5DDF)")

    # Border color and VIC state
    border = read_byte(0xD020)
    d011 = read_byte(0xD011)
    if border is not None:
        print(f"\n$D020 (border): ${border:02X}")
    if d011 is not None:
        print(f"$D011 (VIC ctrl): ${d011:02X}")

    # ACIA state
    dump_region(0xDF80, 4, "ACIA registers ($DF80-$DF83)")

    # EasyFlash state
    dump_region(0xDE00, 3, "EasyFlash regs ($DE00-$DE02)")

    # Check if decompression started - look at game entry point
    dump_region(0x0816, 16, "Game entry ($0816-$0825)")

    # Check $0210-$0212 flags
    dump_region(0x0210, 3, "Flags: use_acia/use_cart/disk_b_base")

    # Debug register
    debug = api_get("/v1/machine:debugreg")
    if debug:
        print(f"\nDebug register ($D7FF): {debug}")

    print("\n=== Done. CPU still paused. Use 'resume' to continue. ===")


def cmd_resume():
    resume()
    print("CPU resumed.")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[-1] == 'resume':
        cmd_resume()
    else:
        diagnose_exomizer_crash()
