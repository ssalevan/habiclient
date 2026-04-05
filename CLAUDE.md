# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Commodore 64 client for Lucasfilm's Habitat (1986) — the world's first MMO. The game engine is written in 6502 assembly using Lucasfilm's custom **Macross** assembler. A C-based launcher (compiled with cc65) handles login, modem setup, and game loading.

## Build Commands

### Full Build (Docker — primary method)
```bash
./dockerbuild
```
Runs inside Rocky Linux 9 x86_64 container (QEMU on ARM Mac). Outputs `Dist/Habitat-A.d64` and `Dist/Habitat-B.d64`.

### Interactive Docker Shell
```bash
./dockershell
```

### Inside Docker (or native Linux x86_64)
```bash
export CC65_HOME=/usr/share/cc65
make clean && make        # Full build (both disks)
make diska                # Game disk only (tools → main → launcher → disk)
make diskb                # Data disk only (behaviors, images, sounds, muddle, charset)
make tools                # Build tools only (macross, slinky, muddle, etc.)
make main                 # Assemble game engine only
make -C Launcher          # Build launcher only (requires main)
make behaviors            # Assemble all 224 behavior .bin files
```

### Individual Tool Builds
```bash
make -C Tools/macross macross
make -C Tools/slinky
make -C Tools/muddle all
```

## Build Pipeline

### Disk A (Game)
1. **Tools**: Build macross, slinky, muddle, a65toprg, mcmgtrim, mtobin, filldisk, habdiska
2. **Main**: Each `.m` source → macross → `.obj` → slinky links all `.obj` → `all.out` → a65toprg → `all.prg` → mcmgtrim → `mcmg.prg` → exomizer → `mcmg.exo`
3. **Launcher**: `launcher.c` → cc65 → cl65 → `launcher.prg`; then 64tass glues BASIC stub + compressed game + raster handler + launcher + title screens → `habitat.prg`
4. **Disk image**: cc1541 writes `habitat.prg` + serial drivers to `Habitat-A.d64`

### Disk B (Data)
Behaviors, images, sounds, muddle/jmuddle output, and charset assembled in parallel, then `filldisk` packs them into `Habitat-B.d64`.

## Architecture

### Main/ — Game Engine (Macross 6502 assembly)
Core runtime assembled as ~84 `.m` files. Key modules:
- **init.m**: System initialization, RS-232/ACIA setup
- **vblank.m**: Raster interrupt handler (split-screen), NMI dispatcher
- **rs232.m**: Bit-banged user port RS-232 AND ACIA/SwiftLink driver
- **comm_control.m, protocol.m**: Network protocol (packet framing, sequencing)
- **database.m**: Object database
- **render.m, paint.m, dline.m, mix.m**: Graphics rendering
- **animate.m, animinit.m**: Animation system
- **keyboard.m, keys.m, cursor.m, pointer.m**: Input handling
- **diskdriver.m, diskdos.m, diskinit.m**: Custom interruptable disk I/O
- **frf_equates.m**: Master equates (memory map, hardware registers, message types)
- **farmers_variables.m**: Runtime variables

Assembly convention: each `.m` is assembled with `macross -c -o $*.obj all.m $*.m` — `all.m` provides shared includes.

### Launcher/ — Login & Setup (cc65 C)
`launcher.c` handles splash screen, name input, modem type selection (SwiftLink or User Port), serial driver loading, and game launch. Compiled to start at `$6000`. The `main.asm` (64tass) combines all components into the final `habitat.prg`.

### Behaviors/ — Object Behaviors (224 .m files)
Each file defines one object action (do, get, put, talk, etc.). Assembled individually to `.bin` files in `Actions/`.

### Tools/ — Custom Build Tools (C)
- **macross**: Lucasfilm's custom 6502 macro assembler
- **slinky**: Linker for macross `.obj` files with explicit segment placement
- **muddle/jmuddle/puddle**: Data definition compiler for `beta.mud`
- **a65toprg, mcmgtrim, mtobin, filldisk, habdiska**: Format converters and disk utilities

All tools in `Tools/` require **`-m32 -fcommon`** CFLAGS for 32-bit builds.

### Memory Map (Game)
| Range | Contents |
|-------|----------|
| `$0801` | BASIC SYS stub |
| `$080E` | Exomizer-compressed game |
| `$0800-$3D03` | Main game code (after decompression) |
| `$4B40-$5F3F` | Graphics silhouette data |
| `$5F00` | Raster interrupt handler (59 bytes) |
| `$5F40-$5FF6` | Animation init |
| `$6000` | Launcher code (cc65) |
| `$6400-$67FF` | Lookup tables |
| `$6A00-$71F7` | Disk init, init, sprites, charset |
| `$8000-$9DFF` | Interrupt handlers, keyboard, protocol, database, variables |
| `$8800/$8C00/$A000` | Title screen data |
| `$FF40-$FFF7` | Hardware vectors |

### Data Definitions
`beta.mud` is the master class/object definition file. Compiled by `muddle` (text listing) and `jmuddle` (JSON). Defines all game object classes with associated sounds, images, and action behaviors.

## Key Technical Details

- **cc65 IRQ conflict**: cc65's crt0 installs its own IRQ handler at `$0314` that breaks KERNAL keyboard scan. The launcher patches `$0314` directly and reinitializes CIA1 Timer A.
- **Raster handler bug at `$5F00`**: CIA1 interrupts during raster lines 72-107 exit via `JMP $EA7E` which doesn't acknowledge the CIA interrupt. Fix: patch `$5F16` from `$7E` to `$31` (route to `$EA31` instead).
- **Serial driver loading**: `ser_load_driver()` does disk I/O; needs `CLRCHN ($FFCC)` after. `ser_open()` corrupts CIA1, so defer serial init until after keyboard input.
- **Launcher binary size**: Must stay under ~10KB to fit `$6000-$8800`.
- **ACIA mode signaling**: Launcher sets `$0297` flag byte to signal ACIA mode to the game engine.

## Current Branch: ssalevan/swift

Adding SwiftLink/ACIA modem support for Ultimate 64 hardware. ACIA registers at `$DE00-$DE03`. Game assembly uses NMI-driven receive and polled transmit. Launcher selects between SwiftLink and User Port serial drivers.
