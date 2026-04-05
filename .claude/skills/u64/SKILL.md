# Ultimate 64 Remote Debugging

Remote control and debug the Habitat C64 client running on Ultimate 64 hardware via REST API.

## Usage

Use `u64_tool.py` in the project root to automate the U64. Write and run Python scripts that import `U64Session`.

### Quick crash diagnosis

```python
from u64_tool import U64Session

u = U64Session("192.168.1.158")
u.diagnose()
# CPU paused, key memory locations dumped
# Call u.resume() when done
```

### Memory inspection

```python
from u64_tool import U64Session

u = U64Session("192.168.1.158")
u.pause()
u.dump(0x0800, 0x40)           # Hex+ASCII dump
u.disassemble(0x080D, 32)      # 6502 disassembly
val = u.read_byte(0x0001)      # Read single byte
word = u.read_word(0xFFFA)     # Read 16-bit LE word
data = u.read_mem(0x0100, 256) # Read raw bytes
u.resume()
```

### Memory writes

```python
u.write_byte(0xD020, 0x02)             # Set border color
u.write_bytes(0xFFFA, [0xFC, 0x01])    # Set NMI vector
```

### Upload and boot CRT

```python
u = U64Session("192.168.1.158")
u.upload_crt("Dist/Habitat.crt")
# U64 resets and boots from cartridge
```

### Full Habitat boot (disk-based)

```python
u = U64Session("192.168.1.158")
u.boot_habitat("steve")
# Mounts disks, resets, navigates launcher, waits for game
```

### Screen reading

```python
u.pause()
rows = u.read_screen()       # All 25 rows as ASCII
row5 = u.read_screen(5)      # Single row
u.dump_screen()              # Print all rows
u.wait_for_screen_text("HABITAT", timeout=30)  # Poll until text appears
u.resume()
```

### Keystroke injection

```python
u.inject_keys(0x0D)             # Press Return
u.type_text("steve")            # Type name + Return (auto-appended)
```

## CLI Usage

```bash
python3 u64_tool.py 192.168.1.158 --diagnose        # Full crash diagnostics
python3 u64_tool.py 192.168.1.158 --boot-state       # Quick boot check
python3 u64_tool.py 192.168.1.158 --pause             # Pause CPU
python3 u64_tool.py 192.168.1.158 --resume            # Resume CPU
python3 u64_tool.py 192.168.1.158 --reset             # Reset C64
python3 u64_tool.py 192.168.1.158 --dump 0800 40      # Dump memory (hex)
python3 u64_tool.py 192.168.1.158 --disasm 080D 20    # Disassemble (hex)
python3 u64_tool.py 192.168.1.158 --read 0001         # Read byte
python3 u64_tool.py 192.168.1.158 --write D020 02     # Write byte
python3 u64_tool.py 192.168.1.158 --screen            # Dump screen text
python3 u64_tool.py 192.168.1.158 --crt Dist/Habitat.crt   # Upload CRT
python3 u64_tool.py 192.168.1.158 --boot steve        # Full boot sequence
python3 u64_tool.py 192.168.1.158 --check             # Check game state
python3 u64_tool.py 192.168.1.158 --version           # Firmware version
```

Default IP comes from `U64_HOST` env var or `192.168.2.64`.

## API Reference

### Machine Control
| Method | Description |
|--------|-------------|
| `pause()` | Pause CPU via DMA line |
| `resume()` | Resume CPU |
| `reset()` | Reset C64 |
| `reboot()` | Reboot with cartridge reinit |
| `upload_crt(path)` | Upload and run CRT file |
| `run_prg(path)` | Upload and run PRG file |

### Memory Access
| Method | Description |
|--------|-------------|
| `read_mem(addr, length)` -> bytes | Read memory block via DMA |
| `read_byte(addr)` -> int | Read single byte |
| `read_word(addr)` -> int | Read 16-bit LE word |
| `write_mem(addr, data)` | Write bytes via DMA |
| `write_byte(addr, val)` | Write single byte |
| `write_bytes(addr, data)` | Write multiple bytes |

### Display
| Method | Description |
|--------|-------------|
| `dump(addr, length, label)` | Hex+ASCII memory dump |
| `disassemble(addr, length)` | 6502 disassembly |
| `dump_screen()` | Print screen RAM as ASCII |
| `read_screen(row)` | Read screen RAM (all rows or single row) |

### Diagnostics
| Method | Description |
|--------|-------------|
| `diagnose()` | Full crash diagnostics (pauses CPU, reads key locations) |
| `check_boot_state()` | Quick boot progress check |
| `check_habitat_state()` | Read INITST, use_acia, NMI vector |

### Disk Management
| Method | Description |
|--------|-------------|
| `mount_disk(drive, d64_path)` | Upload and mount D64 |
| `remove_disk(drive)` | Unmount disk |

### Input
| Method | Description |
|--------|-------------|
| `inject_keys(*petscii_codes)` | Write to KERNAL keyboard buffer |
| `type_text(text)` | Type string + Return |

### Modem
| Method | Description |
|--------|-------------|
| `dial_modem(host, acia_base)` | Send ATDT via DMA to ACIA. Default acia_base=$DF80 |

### Polling
| Method | Description |
|--------|-------------|
| `wait_for_byte(addr, value, timeout)` | Poll until byte matches |
| `wait_for_screen_text(text, row, timeout)` | Poll screen until text appears |

## Key Memory Locations

| Address | Name | Description |
|---------|------|-------------|
| `$0001` | CPU port | Memory banking ($37=normal, $38=all-RAM, $36=cc65) |
| `$0210` | use_acia flag | $FF = SwiftLink mode |
| `$0211` | use_cart flag | $FF = EasyFlash cart mode |
| `$0212` | disk_b_base | First EasyFlash bank for Disk B data |
| `$080D` | SFX entry | Exomizer self-extracting decompressor start |
| `$0816` | Game entry | start_of_program (after decompression) |
| `$FFFA-$FFFB` | NMI vector | Hardware NMI (reads from RAM when $01=$38) |
| `$FFFE-$FFFF` | IRQ vector | Hardware IRQ (reads from RAM when $01=$38) |
| `$DF80-$DF83` | ACIA regs | SwiftLink at $DF80 (U64 modem config) |
| `$DE00-$DE02` | EasyFlash regs | Bank select ($DE00), control ($DE02) |
| `$D020` | Border color | Quick visual state indicator |
| `$D7FF` | Debug register | U64 debug register |
| `$5DC0` | Decompressor | Exomizer decompression routine |

## Important Notes

- **DMA reads are non-intrusive**: `read_mem`/`read_byte` work via DMA, not CPU. They read actual RAM contents regardless of CPU banking state ($01 register).
- **Pause before reading**: Always `pause()` before memory inspection to get a consistent snapshot. The CPU is halted via DMA line.
- **ACIA at $DF80**: Current U64 modem config is DF80/NMI. Set in U64 menu: F2 → Modem → DF80/NMI.
- **CRT upload resets U64**: `upload_crt()` POSTs to `/v1/runners:run_crt` which resets and boots from the cartridge.
- **REST API requires firmware 3.11+**: Check with `--version`.
- **Default IP**: Set `U64_HOST` env var or pass IP as first positional arg.
