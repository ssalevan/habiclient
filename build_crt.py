#!/usr/bin/env python3
"""
Build EasyFlash CRT image from habitat.prg, mcmg.prg, and Habitat-B.d64.

Usage: python3 build_crt.py <habitat.prg> <mcmg.prg> <Habitat-B.d64> <output.crt>

Creates a single EasyFlash cartridge containing the entire game:
- Bank 0: Boot code (ROMH at $E000) + empty ROML
- Banks 1-N: habitat.prg data (launcher + title screens)
- Banks N+1-N+G: mcmg.prg data (uncompressed game, $0806-$C017)
- Banks N+G+1-M: Disk B sectors (behaviors, images, sounds, heads)

Boot sequence:
1. Ultimax mode: RESET -> ROMH bank 0 -> boot code at $E000
2. Boot code copies small RAM copier to $0100, JMPs there
3. Copier switches to 8K cart mode, copies habitat.prg banks to $0801+
4. Copier sets use_acia/use_cart flags and game/disk bank numbers
5. Copier calls KERNAL IOINIT/RESTOR/CINT, JMPs to launcher at $6000
6. Launcher connects to server, then copies game banks from cart to $0806+
7. Launcher JMPs to $0816 (game entry) — no Exomizer decompression needed
"""

import math
import struct
import sys

BANK_SIZE = 8192  # 8KB per bank

# EasyFlash control register ($DE02):
#   Bit 0: GAME    (directly active, active-low accent)
#   Bit 1: !EXROM  (inverted: 1 = EXROM inactive/HIGH)
#   Bit 2: mode    (selects between two mode tables)
# Mapping (jumper OFF, default VICE):
#   $00/$01 = Ultimax, $02/$03 = 16K, $04 = Off, $06 = 8K, $07 = 16K
EF_8K  = 0x03  # ROML visible on U64 (serve_rom=1). Use EF_OFF=$01 to keep cart_active
EF_OFF = 0x04  # Cart disabled: all RAM + KERNAL/BASIC ROMs via $01


def build_copier(num_prg_banks, game_base_bank, num_game_banks, disk_b_base_bank):
    """Build the RAM copier routine that runs from $0100.

    Everything runs from $0100 — no separate tail needed. After KERNAL init,
    cart disable/flags/JMP are high enough on page 1 to survive stack writes
    (SP restricted to $3F = stack at $0100-$013F).
    """
    BASE = 0x0100
    code = bytearray()
    labels = {}

    def pos():
        return BASE + len(code)

    def emit(*args):
        code.extend(args)

    # Initialize processor port DDR (6510 resets with DDR=$00 = all inputs;
    # without DDR setup, banking bits in $01 aren't driven as outputs)
    emit(0xA9, 0x2F)           # LDA #$2F  (standard C64 DDR)
    emit(0x85, 0x00)           # STA $00

    # Switch from Ultimax to 8K cart mode
    emit(0xA9, EF_8K)           # LDA #$03
    emit(0x8D, 0x02, 0xDE)     # STA $DE02
    emit(0xA9, 0x37)           # LDA #$37  (LORAM+HIRAM+CHAREN for ROML visibility)
    emit(0x85, 0x01)           # STA $01

    # Destination pointer = $0801 (habitat.prg load address)
    emit(0xA9, 0x01)           # LDA #$01
    emit(0x85, 0xFB)           # STA $FB
    emit(0xA9, 0x08)           # LDA #$08
    emit(0x85, 0xFC)           # STA $FC

    # Bank loop setup
    emit(0xA9, 0x01)           # LDA #1    (first PRG bank)
    emit(0x85, 0xFD)           # STA $FD   (current bank)
    emit(0xA2, num_prg_banks)  # LDX #num_prg_banks

    # --- bank_loop ---
    labels['bank_loop'] = pos()
    emit(0xA5, 0xFD)           # LDA $FD
    emit(0x8D, 0x00, 0xDE)    # STA $DE00  (select bank)

    inner_loop_hi = pos() + 13

    emit(0xA9, 0x80)                                        # LDA #$80
    emit(0x8D, inner_loop_hi & 0xFF, inner_loop_hi >> 8)   # STA inner_loop+2
    emit(0xA9, 32)                                           # LDA #32  (pages per bank)
    emit(0x85, 0xFE)                                         # STA $FE
    emit(0xA0, 0x00)                                         # LDY #$00

    # --- inner_loop (byte copy) ---
    labels['inner_loop'] = pos()
    assert pos() + 2 == inner_loop_hi, \
        f"inner_loop high byte mismatch: {pos()+2:#06x} != {inner_loop_hi:#06x}"

    emit(0xB9, 0x00, 0x80)    # LDA $8000,Y  (high byte self-modified)
    emit(0x91, 0xFB)           # STA ($FB),Y
    emit(0xC8)                  # INY
    emit(0xD0)
    emit((labels['inner_loop'] - (pos() + 1)) & 0xFF)

    # Page advance
    emit(0xE6, 0xFC)           # INC $FC
    src_hi = labels['inner_loop'] + 2
    emit(0xEE, src_hi & 0xFF, src_hi >> 8)  # INC inner_loop+2
    emit(0xC6, 0xFE)           # DEC $FE
    ldy_addr = labels['inner_loop'] - 2
    emit(0xD0)
    emit((ldy_addr - (pos() + 1)) & 0xFF)

    # Next bank
    emit(0xE6, 0xFD)           # INC $FD
    emit(0xCA)                  # DEX
    emit(0xD0)
    emit((labels['bank_loop'] - (pos() + 1)) & 0xFF)

    # === KERNAL state init (replaces RAMTAS without destructive memory test) ===

    # --- Zero ZP $02-$FF (KERNAL variables: NFILES, DFLTI, DFLTO, etc.) ---
    emit(0xA9, 0x00)           # LDA #$00
    emit(0xA0, 0xFE)           # LDY #$FE
    labels['zp_clear'] = pos()
    emit(0x99, 0x01, 0x00)    # STA $0001,Y  (Y=$FE→$FF .. Y=$01→$02)
    emit(0x88)                  # DEY
    emit(0xD0)
    emit((labels['zp_clear'] - (pos() + 1)) & 0xFF)  # BNE zp_clear

    # --- Zero page 2 ($0200-$02FF: file tables, keyboard buffer, etc.) ---
    emit(0xA8)                  # TAY  (Y=0, A=0)
    labels['p2_clear'] = pos()
    emit(0x99, 0x00, 0x02)    # STA $0200,Y
    emit(0xC8)                  # INY
    emit(0xD0)
    emit((labels['p2_clear'] - (pos() + 1)) & 0xFF)

    # --- Zero page 3 ($0300-$03FF: KERNAL/BASIC indirect vectors, etc.) ---
    labels['p3_clear'] = pos()
    emit(0x99, 0x00, 0x03)    # STA $0300,Y
    emit(0xC8)                  # INY
    emit(0xD0)
    emit((labels['p3_clear'] - (pos() + 1)) & 0xFF)

    # --- Set critical KERNAL variables ---
    emit(0xA9, 0x04)           # LDA #$04
    emit(0x8D, 0x88, 0x02)    # STA $0288  (screen memory page = $0400)
    emit(0xA9, 0x00)           # LDA #$00
    emit(0x8D, 0x82, 0x02)    # STA $0282  (top of memory low)
    emit(0xA9, 0xA0)           # LDA #$A0
    emit(0x8D, 0x83, 0x02)    # STA $0283  (top of memory high = $A000)

    # --- Restore full stack before KERNAL init ---
    # Copier ends at ~$0188; SP=$FF gives 119 bytes of stack ($01FF-$0189)
    # before touching copier code. KERNAL init uses ~30 bytes max.
    emit(0xA2, 0xFF)           # LDX #$FF
    emit(0x9A)                  # TXS

    # --- KERNAL init ---
    emit(0x20, 0x84, 0xFF)    # JSR $FF84  IOINIT
    emit(0x20, 0x8A, 0xFF)    # JSR $FF8A  RESTOR
    emit(0x20, 0x81, 0xFF)    # JSR $FF81  CINT

    # --- Keep cart alive, bank 0 ---
    emit(0xA9, 0x00)           # LDA #$00
    emit(0x8D, 0x00, 0xDE)    # STA $DE00

    # --- Copy KERNAL ROM to RAM ($E000-$FFFF) ---
    emit(0xA0, 0x00)           # LDY #$00
    emit(0xA2, 0x20)           # LDX #32
    labels['kc'] = pos()
    emit(0xB9, 0x00, 0xE0)    # LDA $E000,Y
    emit(0x99, 0x00, 0xE0)    # STA $E000,Y
    emit(0xC8)                  # INY
    emit(0xD0)                  # BNE kc
    emit((labels['kc'] - (pos() + 1)) & 0xFF)
    src_hi = labels['kc'] + 2
    dst_hi = labels['kc'] + 5
    emit(0xEE, src_hi & 0xFF, src_hi >> 8)  # INC kc+2
    emit(0xEE, dst_hi & 0xFF, dst_hi >> 8)  # INC kc+5
    emit(0xCA)                  # DEX
    emit(0xD0)                  # BNE kc
    emit((labels['kc'] - (pos() + 1)) & 0xFF)

    # --- Disable EasyFlash and hide ROML ---
    # EF_OFF prevents ROML from responding to bus reads at $8000-$9FFF.
    # On the U64 with Bus Sharing = Both, the EasyFlash ROM can conflict
    # with RAM reads if the cart stays in 8K mode.  read_TS_cart re-enables
    # the cart for each sector read, then disables it again.
    emit(0xA9, EF_OFF)         # LDA #$04
    emit(0x8D, 0x02, 0xDE)    # STA $DE02  (disable cart)
    emit(0xA9, 0x35)           # LDA #$35
    emit(0x85, 0x01)           # STA $01
    emit(0xA9, 0x05)           # LDA #$05
    emit(0x8D, 0x08, 0x60)    # STA $6008

    # --- Set flags ---
    emit(0xA9, 0xFF)           # LDA #$FF
    emit(0x8D, 0x10, 0x02)    # STA $0210  (use_acia)
    emit(0x8D, 0x11, 0x02)    # STA $0211  (use_cart)
    emit(0xA9, disk_b_base_bank & 0xFF)
    emit(0x8D, 0x12, 0x02)    # STA $0212  (disk_b_base_bank)
    emit(0xA9, game_base_bank & 0xFF)
    emit(0x8D, 0x13, 0x02)    # STA $0213  (game_base_bank)
    emit(0xA9, num_game_banks & 0xFF)
    emit(0x8D, 0x14, 0x02)    # STA $0214  (num_game_banks)

    # --- Enable interrupts and jump to launcher ---
    emit(0x58)                  # CLI
    emit(0x4C, 0x00, 0x60)    # JMP $6000

    return bytes(code)


def build_boot_romh(copier_bytes):
    """Build 8KB ROMH for bank 0 with boot code at $E000 and reset vector.

    Boot code copies copier_bytes → $0100, then JMPs to $0100.
    """
    romh = bytearray(b'\xFF' * BANK_SIZE)

    boot = bytearray()
    boot.extend([0x78])         # SEI
    boot.extend([0xD8])         # CLD
    boot.extend([0xA2, 0xFF])   # LDX #$FF
    boot.extend([0x9A])         # TXS

    # Copy copier to $0100: LDX #len; loop: LDA data-1,X; STA $00FF,X; DEX; BNE
    boot.extend([0xA2, len(copier_bytes)])  # LDX #len
    copier_loop_start = len(boot)
    boot.extend([0xBD, 0x00, 0x00])  # LDA copier_data-1,X (placeholder)
    boot.extend([0x9D, 0xFF, 0x00])  # STA $00FF,X
    boot.extend([0xCA])              # DEX
    boot.extend([0xD0, 0xF7])        # BNE loop (-9)
    boot.extend([0x4C, 0x00, 0x01])  # JMP $0100

    copier_data_offset = len(boot)
    boot.extend(copier_bytes)

    # RTI for NMI/IRQ stubs
    rti_offset = len(boot)
    boot.extend([0x40])

    # Fix up copier data address
    copier_data_addr = 0xE000 + copier_data_offset
    boot[copier_loop_start + 1] = (copier_data_addr - 1) & 0xFF
    boot[copier_loop_start + 2] = (copier_data_addr - 1) >> 8

    romh[:len(boot)] = boot

    # Vectors at $FFFA-$FFFF (offset $1FFA in 8KB ROMH)
    rti_addr = 0xE000 + rti_offset
    struct.pack_into('<H', romh, 0x1FFA, rti_addr)  # NMI
    struct.pack_into('<H', romh, 0x1FFC, 0xE000)     # RESET
    struct.pack_into('<H', romh, 0x1FFE, rti_addr)  # IRQ

    return bytes(romh)


def write_crt_header(f, name="Habitat"):
    """Write 64-byte CRT file header for EasyFlash."""
    hdr = bytearray(64)
    hdr[0:16] = b"C64 CARTRIDGE   "
    struct.pack_into('>I', hdr, 16, 64)       # header length
    struct.pack_into('>H', hdr, 20, 0x0100)   # CRT version 1.0
    struct.pack_into('>H', hdr, 22, 32)       # hardware type: EasyFlash
    hdr[24] = 1                                # EXROM=1 (Ultimax startup)
    hdr[25] = 0                                # GAME=0
    name_bytes = name.encode('ascii')[:31]
    hdr[32:32 + len(name_bytes)] = name_bytes
    f.write(hdr)


def write_chip(f, bank, load_addr, data):
    """Write one CHIP packet (16-byte header + ROM data)."""
    chip = bytearray(16)
    chip[0:4] = b"CHIP"
    struct.pack_into('>I', chip, 4, 16 + len(data))
    struct.pack_into('>H', chip, 8, 2)          # Flash ROM
    struct.pack_into('>H', chip, 10, bank)
    struct.pack_into('>H', chip, 12, load_addr)
    struct.pack_into('>H', chip, 14, len(data))
    f.write(chip)
    f.write(data)


def main():
    if len(sys.argv) < 5:
        print(f"Usage: {sys.argv[0]} <habitat.prg> <mcmg.prg> <Habitat-B.d64> <output.crt>")
        sys.exit(1)

    prg_path = sys.argv[1]
    game_path = sys.argv[2]
    d64_path = sys.argv[3]
    crt_path = sys.argv[4]

    # Read habitat.prg (launcher + title screens; strip 2-byte load address header)
    with open(prg_path, 'rb') as f:
        prg_raw = f.read()
    load_addr = struct.unpack_from('<H', prg_raw, 0)[0]
    prg_data = prg_raw[2:]

    # Read mcmg.prg (uncompressed game; strip 2-byte load address header)
    with open(game_path, 'rb') as f:
        game_raw = f.read()
    game_load_addr = struct.unpack_from('<H', game_raw, 0)[0]
    game_data = game_raw[2:]

    # Read D64
    with open(d64_path, 'rb') as f:
        d64_data = f.read()

    num_prg_banks = math.ceil(len(prg_data) / BANK_SIZE)
    num_game_banks = math.ceil(len(game_data) / BANK_SIZE)
    num_d64_banks = math.ceil(len(d64_data) / BANK_SIZE)
    game_base_bank = num_prg_banks + 1           # after boot + PRG banks
    disk_b_base_bank = game_base_bank + num_game_banks
    total_banks = 1 + num_prg_banks + num_game_banks + num_d64_banks

    print(f"PRG:  {len(prg_raw):>6} bytes, load ${load_addr:04X}, "
          f"{len(prg_data)} data bytes -> {num_prg_banks} banks (1-{num_prg_banks})")
    print(f"Game: {len(game_raw):>6} bytes, load ${game_load_addr:04X}, "
          f"{len(game_data)} data bytes -> {num_game_banks} banks "
          f"({game_base_bank}-{game_base_bank+num_game_banks-1})")
    print(f"D64:  {len(d64_data):>6} bytes, {len(d64_data)//256} sectors "
          f"-> {num_d64_banks} banks ({disk_b_base_bank}-{disk_b_base_bank+num_d64_banks-1})")
    print(f"Total: {total_banks} / 64 banks")
    print(f"  game_base_bank = {game_base_bank}, disk_b_base_bank = {disk_b_base_bank}")

    if total_banks > 64:
        print(f"ERROR: requires {total_banks} banks (max 64)")
        sys.exit(1)

    # Build boot code
    copier = build_copier(num_prg_banks, game_base_bank, num_game_banks,
                          disk_b_base_bank)
    romh = build_boot_romh(copier)
    print(f"Copier: {len(copier)} bytes at $0100-${0xFF+len(copier):04X}")

    # Pad to full bank boundaries
    prg_padded = prg_data.ljust(num_prg_banks * BANK_SIZE, b'\x00')
    game_padded = game_data.ljust(num_game_banks * BANK_SIZE, b'\x00')
    d64_padded = d64_data.ljust(num_d64_banks * BANK_SIZE, b'\x00')

    # Write CRT
    with open(crt_path, 'wb') as f:
        write_crt_header(f)

        # Bank 0: ROML (shadow of $8000-$9FFF from habitat.prg) + ROMH (boot)
        # U64 EasyFlash emulation is permanently torn down by $DE02=$04,
        # so we keep the cart alive in 16K mode.  Bank 0 ROML must contain
        # the $8000-$9FFF portion of habitat.prg so that ROML reads during
        # launcher operation return the correct code/data (cc65 BSS, title
        # screen bitmaps, etc.).  The boot copier selects bank 0 before
        # jumping to the launcher.
        shadow_offset = 0x8000 - load_addr  # offset into prg_data for $8000
        shadow_data = prg_padded[shadow_offset : shadow_offset + BANK_SIZE]
        print(f"Bank 0 ROML: shadow of ${load_addr + shadow_offset:04X}-"
              f"${load_addr + shadow_offset + BANK_SIZE - 1:04X} "
              f"(offset {shadow_offset:#06x} in PRG)")
        write_chip(f, 0, 0x8000, shadow_data)
        write_chip(f, 0, 0xE000, romh)

        # PRG banks (habitat.prg: launcher + title screens)
        for i in range(num_prg_banks):
            write_chip(f, i + 1, 0x8000,
                       prg_padded[i*BANK_SIZE : (i+1)*BANK_SIZE])

        # Game banks (mcmg.prg: uncompressed game)
        for i in range(num_game_banks):
            write_chip(f, game_base_bank + i, 0x8000,
                       game_padded[i*BANK_SIZE : (i+1)*BANK_SIZE])

        # D64 banks (Disk B sectors)
        for i in range(num_d64_banks):
            write_chip(f, disk_b_base_bank + i, 0x8000,
                       d64_padded[i*BANK_SIZE : (i+1)*BANK_SIZE])

    import os
    crt_size = os.path.getsize(crt_path)
    print(f"\nWrote {crt_path} ({crt_size:,} bytes)")
    print(f"Boot: RESET -> $E000 -> copier@$0100 -> "
          f"copy {num_prg_banks} PRG banks to ${load_addr:04X} -> "
          f"KERNAL init -> JMP $6000")
    print(f"Launcher exit: copy {num_game_banks} game banks to "
          f"${game_load_addr:04X} -> JMP $0816 (no Exomizer)")


if __name__ == '__main__':
    main()
