Habitat for the Ultimate 64
===========================

[![Build & Release](https://github.com/ssalevan/habiclient/actions/workflows/build.yml/badge.svg?branch=main)](https://github.com/ssalevan/habiclient/actions/workflows/build.yml)
[![Latest release](https://img.shields.io/github/v/release/ssalevan/habiclient?include_prereleases&sort=date)](https://github.com/ssalevan/habiclient/releases)
[![license](https://img.shields.io/github/license/ssalevan/habiclient)](https://github.com/ssalevan/habiclient/blob/main/LICENSE)
[![Slack](http://slack.neohabitat.org/badge.svg)](http://slack.neohabitat.org/)

This repository contains a modernised port of the original Commodore 64 client
for [Lucasfilm's Habitat](https://en.wikipedia.org/wiki/Habitat_(video_game))
— the world's first MMO, released in 1986 on QuantumLink. The port targets
the [Ultimate 64](https://ultimate64.com) (an FPGA-based Commodore 64
reimplementation), using its built-in SwiftLink/ACIA modem emulation to
connect to a [Neohabitat](http://neohabitat.org) server over TCP rather than
over a real 1200-baud modem.

The entire game ships as a single EasyFlash cartridge: launcher, decompressed
game engine, behaviors, sounds, images, and head sprites all live in cartridge
ROM, so loading times are effectively instant and no floppy swapping is
required.

> **Note** — this project is not officially supported by the
> [Neohabitat Project](http://neohabitat.org). It exists for preservation and
> education. There are no guarantees of stability, only of adventure.

Quick Start
-----------

1. Grab the latest cartridge bundle:
   - **Latest stable:**
     [`Habitat-U64.zip`](https://github.com/ssalevan/habiclient/releases/latest/download/Habitat-U64.zip)
   - **Rolling (built from `main`):**
     [`Habitat-U64.zip`](https://github.com/ssalevan/habiclient/releases/download/rolling/Habitat-U64.zip)
   - **All releases:**
     [github.com/ssalevan/habiclient/releases](https://github.com/ssalevan/habiclient/releases)
2. Unzip and copy the `Habitat-U64/` folder onto your Ultimate 64's USB stick
   (e.g. `USB1/HABICART/`).
3. From the U64 menu, load `habitat-u64.cfg` into your current configuration
   (and save it to flash if you want it to stick).
4. Select `Habitat.crt` and choose *Run Cartridge*.
5. Type a character name, press <kbd>RETURN</kbd> twice, and you're connected
   to the Neohabitat server.

The full install walkthrough — including modem-emulation settings, firmware
requirements, troubleshooting, and "deploy from your laptop over the network"
recipes — lives in [docs/U64.md](docs/U64.md).

Hardware Requirements
---------------------

| Item             | Minimum                              | Notes                                          |
|------------------|--------------------------------------|------------------------------------------------|
| Ultimate 64      | Any revision (Mark I, II, Elite)     | The original C64 + Ultimate II+ also works.    |
| Firmware         | 3.11 or later                        | Earlier firmware lacks the REST API.           |
| Network          | Ethernet or WiFi (Elite-II only)     | Must be online to reach the Neohabitat server. |
| Display          | NTSC by preference                   | PAL works; the `.cfg` configures NTSC.         |
| Keyboard         | Stock C64 keyboard / U64 keyrah      | The launcher accepts standard PETSCII input.   |

A `.cfg` file is provided that configures the U64's built-in modem emulation
to expose a 6551-compatible ACIA at `$DF80` with NMI-driven receive — the
exact register map the in-game serial driver expects. No external SwiftLink
hardware is needed.

Features
--------

- **Single-cartridge install.** Boot the entire game (launcher + engine +
  data) from one EasyFlash CRT image. No disk swapping; no copy-protection
  worries.
- **TCP networking via U64 modem emulation.** The U64 firmware exposes an
  emulated SwiftLink at `$DF80`. The game's NMI-driven ACIA driver talks to
  it directly, with TCP frames carried transparently to/from Neohabitat.
- **Cart-mode safe disk emulation.** The original game streams behaviors and
  images from Disk B at runtime. The cartridge bakes Disk B contents into
  flash banks and serves them via an in-RAM disk-driver shim.
- **REST-API deploy.** Push a new `Habitat.crt` straight to a U64 over HTTP
  (`./upload_u64.sh`) — no SD card juggling, no power cycling.
- **Legacy hardware still supported.** A stock C64 with a SwiftLink cartridge
  (or a User Port RS-232 + null-modem) can still run the disk-image build via
  `Habitat-A.d64` / `Habitat-B.d64`. See [docs/U64.md](docs/U64.md#legacy-builds).

Build From Source
-----------------

Builds run inside a Rocky Linux 9 x86_64 Docker container (so the same
toolchain works on Linux, macOS Intel, and Apple Silicon via QEMU).

```bash
./dockercart       # Build the EasyFlash cartridge (Dist/Habitat.crt + Habitat-U64.zip)
./dockerbuild      # Build classic 1541 disk images (Dist/Habitat-A.d64, Habitat-B.d64)
./dockershell      # Interactive shell inside the build container
```

The build pipeline, individual `make` targets, and the memory map are
documented in [CLAUDE.md](CLAUDE.md).

Repository Layout
-----------------

| Path             | What's there                                                                   |
|------------------|--------------------------------------------------------------------------------|
| `Main/`          | Game engine in Lucasfilm Macross 6502 assembly (~84 `.m` files).               |
| `Launcher/`      | cc65 C launcher (login screen, modem setup, game bootstrap).                   |
| `Behaviors/`     | 224 per-object action handlers (one `.m` file each).                           |
| `Heap/`, `Io/`   | Equates and externs shared across game and launcher.                           |
| `Tools/`         | Macross assembler, slinky linker, muddle data compiler, disk utilities.        |
| `Dist/`          | Build artefacts: `Habitat.crt`, `Habitat-A.d64`, `Habitat-B.d64`, U64 zip.     |
| `build_crt.py`   | Packs `habitat.prg` + `mcmg.prg` + Disk B into an EasyFlash CRT.               |
| `u64_tool.py`    | Python wrapper around the U64 REST API (push CRTs, peek/poke memory, reset).  |
| `u64_deploy.py`  | Uploads disk images to the U64's USB stick over FTP.                           |
| `upload_u64.sh`  | One-shot "build CRT, push to U64, reboot into it" helper.                      |
| `docs/U64.md`    | Detailed Ultimate 64 install + troubleshooting guide.                          |

License
-------

Released under the MIT License (see `LICENSE`). Original Habitat client code
© 1986 Lucasfilm Games / QuantumLink, released to the public archive by
F. Randall Farmer in 2017.

Credits
-------

- **Original 6502 client (1986):** Chip Morningstar, F. Randall Farmer,
  Aric Wilmunder, Janet Hunter.
- **Build tooling, disk packers, original Neohabitat launcher:** Gary Lake.
- **Dockerization and buildmeistering:** Steve Salevan.
- **Ultimate 64 / SwiftLink port, EasyFlash cartridge build,
  Neohabitat re-bring-up:** Steve Salevan, with ample 6502 hand-holding by
  Claude.

Community
---------

The Neohabitat project maintains a [Slack](http://slack.neohabitat.org)
where preservation enthusiasts, retro-hardware people, and current Habitat
players hang out. The `#troubleshooting` channel is the right place to ask
for help with this client.
