# Habitat VICE Automation

Launch VICE, automate the Habitat C64 client boot sequence, and debug game memory.

## Usage

Use `vice_tool.py` in the project root to automate VICE. Write and run Python scripts that import `VICESession`.

### Full boot (through launcher)

```python
from vice_tool import VICESession

with VICESession(verbose=True) as v:
    v.boot_to_game("steve")
    # Game is now running — inspect state
    regs = v.registers()
    print(f"PC=${regs['PC']:04X}")
    print(f"saved_acia_flag = ${v.read_byte(0x6DD9):02X}")
```

### Direct boot (skip launcher + decompressor)

```python
from vice_tool import VICESession

with VICESession(verbose=True) as v:
    v.boot_direct(acia=True, breakpoint=0x7083)
    # Stopped at rs232_open — step through
    regs = v.registers()
    v.step()
    regs = v.registers()
    print(f"A=${regs['A']:02X}")  # Should be $FF if ACIA flag propagated
```

### Step-by-step boot (for debugging launcher stages)

```python
from vice_tool import VICESession

with VICESession(verbose=True) as v:
    v.boot_to_splash()
    # At splash screen — inspect launcher state
    v.dismiss_splash()
    # At modem selection — default is SwiftLink
    v.switch_to_userport()  # Switch to User Port (avoids VICE hang)
    # At login prompt
    v.login("steve")
    v.wait_for_decrunch()
    # Game running
```

### Set breakpoints and wait

```python
from vice_tool import VICESession

with VICESession(verbose=True) as v:
    v.boot_to_splash()
    v.dismiss_splash()
    v.switch_to_userport()
    # Set a breakpoint before login triggers the boot
    v.set_breakpoint(0x0816)  # start_of_program
    v.login("a")
    # Wait for breakpoint hit (up to 120s for decrunch)
    resp = v.go_and_wait(timeout=120)
    regs = v.registers()
    print(f"Hit breakpoint at PC=${regs['PC']:04X}")
```

## API Reference

### Lifecycle
| Method | Description |
|--------|-------------|
| `launch(disk_image, prg, extra_args, wait)` | Start VICE with remote monitor |
| `connect(retries, delay)` | TCP connect to monitor port |
| `close()` | Close socket + terminate VICE |
| `reconnect(retries, delay)` | Close and reopen monitor connection |

### Monitor Commands
| Method | Description |
|--------|-------------|
| `cmd(command, timeout)` | Send command, wait for prompt, return response |
| `go(addr, settle)` | Continue/goto addr, close socket, wait, reconnect |
| `go_and_wait(addr, timeout)` | Continue/goto addr, wait for breakpoint |
| `keybuf(text)` | Inject keystrokes via `keybuf` command (no escape sequences) |
| `inject_keys(*petscii_codes)` | Write PETSCII codes directly to keyboard buffer |
| `type_and_wait(text, settle)` | inject_keys(text + Return) + go + reconnect |

### Memory
| Method | Description |
|--------|-------------|
| `read_byte(addr)` → int | Read single byte |
| `read_word(addr)` → int | Read 16-bit LE word |
| `read_block(start, length)` → bytearray | Read memory block |
| `write_byte(addr, value)` | Write single byte |
| `write_bytes(addr, data)` | Write multiple bytes |

### Debugging
| Method | Description |
|--------|-------------|
| `registers()` → dict | Get PC, A, X, Y, SP, flags |
| `disassemble(start, end)` → str | Disassemble range |
| `set_breakpoint(addr)` | Set execution breakpoint |
| `set_watchpoint(addr, mode)` | Set store/load watchpoint |
| `delete_breakpoints()` | Delete all breakpoints |
| `step(count)` | Single-step N instructions |
| `load(path, device)` | Load .prg into memory |

### Habitat Boot Helpers
| Method | Description |
|--------|-------------|
| `boot_to_splash(disk_image, wait)` | Launch + connect (at splash screen) |
| `dismiss_splash(settle)` | Press Return past splash |
| `switch_to_userport(settle)` | Press F3 for User Port modem |
| `login(name, settle)` | Type name + Return |
| `wait_for_decrunch(seconds)` | Wait for Exomizer + init |
| `boot_to_game(name, disk_image, userport)` | Full sequence |
| `boot_direct(prg, acia, breakpoint)` | Fast path with all.prg |

### Habitat Inspection
| Method | Description |
|--------|-------------|
| `check_acia_flags()` → dict | Read ACIA flag propagation chain |
| `check_acia_registers()` → dict | Read ACIA hardware at $DE00 |

## Key Memory Locations

| Address | Name | Description |
|---------|------|-------------|
| `$03FF` | acia_signal | Launcher → decompressor ACIA flag |
| `$0334` | use_acia_flag | Decompressor saves/restores this |
| `$6DD9` | saved_acia_flag | start_of_program copies $03FF here |
| `$9DF0` | use_acia | rs232_open copies $6DD9 here (runtime flag) |
| `$0318` | NMI vector | Points to acia_NMI when ACIA active |
| `$DE00-$DE03` | ACIA registers | SwiftLink hardware |
| `$5F00` | raster handler | Split-screen raster IRQ (59 bytes) |
| `$0314` | IRQ vector | Should be $EA31 or $5F00 |

## Important Notes

- **VICE emulates SwiftLink**: The default modem selection (SwiftLink) works in VICE. No need to call `switch_to_userport()` unless specifically testing User Port mode.
- **go() vs go_and_wait()**: Use `go()` when you want to resume execution for a fixed time (e.g., waiting for keys to be processed). Use `go_and_wait()` when you have a breakpoint set and want to catch it.
- **Disk path**: Defaults to `Dist/Habitat-A.d64` relative to project root. Build with `./dockerbuild` first.
- **all.prg path**: For `boot_direct()`, defaults to `all.prg` in project root. Build with `make main` inside Docker.
