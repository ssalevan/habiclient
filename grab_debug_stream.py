#!/usr/bin/env python3
"""
Capture U64 debug stream and find writes to $0000/$0001.

Usage:
    1. On the U64, press F5 (action menu) and start the Debug Stream
       with destination IP = this machine's IP, port 11002
    2. Run: python3 grab_debug_stream.py [seconds]
    3. Reproduce the vendo DO crash
    4. The script captures all CPU cycles and finds the culprit

Each 32-bit record:
    Bit 31:    PHI2
    Bit 30:    GAME#
    Bit 29:    EXROM#
    Bit 28:    BA
    Bit 27:    IRQ#
    Bit 26:    ROM#
    Bit 25:    NMI#
    Bit 24:    R/W# (1=read, 0=write)
    Bits 23-16: Data byte
    Bits 15-0:  Address
"""
import sys
import socket
import struct

UDP_PORT = 11002
RECORDS_PER_PACKET = 360  # 360 x 4 bytes = 1440, plus 4 byte header = 1444

seconds = 30
if len(sys.argv) > 1:
    seconds = int(sys.argv[1])

print(f"Capturing debug stream for {seconds} seconds on UDP port {UDP_PORT}...")
print(f"Make sure the U64 debug stream is pointed at this machine's IP, port {UDP_PORT}")
print()

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.settimeout(3.0)
sock.bind(('', UDP_PORT))

# Collect raw data
raw_records = bytearray()
packets = 0
previous_seq = None
drops = 0

frames_needed = 2737 * seconds  # ~2737 packets/second at ~1MHz

try:
    for _ in range(frames_needed):
        try:
            data, address = sock.recvfrom(1536)
        except socket.timeout:
            if packets == 0:
                print("No data received. Is the debug stream started on the U64?")
                print("  Press F5 on U64 -> Debug Stream -> set destination IP + port 11002")
                sys.exit(1)
            break

        (seq,) = struct.unpack("<H", data[0:2])
        if previous_seq is not None and (previous_seq + 1) & 0xFFFF != seq:
            drops += 1
        previous_seq = seq
        packets += 1

        # Append the 360 records (skip 4-byte header)
        raw_records.extend(data[4:])

        if packets % 1000 == 0:
            print(f"  {packets} packets, {len(raw_records)//4} records...", flush=True)

except KeyboardInterrupt:
    print("\nStopped early by Ctrl+C")

sock.close()

total_records = len(raw_records) // 4
print(f"\nCaptured {packets} packets, {total_records} CPU cycles, {drops} drops")

# Now analyze: find writes to $0000 or $0001
print("\n=== Scanning for writes to $0000/$0001 ===\n")

suspicious = []
for i in range(total_records):
    word = struct.unpack_from("<I", raw_records, i * 4)[0]
    addr = word & 0xFFFF
    data_byte = (word >> 16) & 0xFF
    rw = (word >> 24) & 0x01  # 1=read, 0=write
    phi2 = (word >> 31) & 0x01
    nmi = (word >> 25) & 0x01
    irq = (word >> 27) & 0x01

    if addr <= 0x0001 and rw == 0 and phi2 == 1:
        # Write to $0000 or $0001 during CPU cycle (PHI2=1)
        # Check if it's a "bad" write
        if addr == 0x0000 and data_byte != 0x2F and data_byte != 0x07:
            # DDR should be $2F (gameplay) or $07 (init_disk)
            suspicious.append((i, addr, data_byte, nmi, irq))
        elif addr == 0x0001 and data_byte not in (0x06, 0x24, 0x25, 0x27, 0x37):
            # Port should be one of the known banking values
            suspicious.append((i, addr, data_byte, nmi, irq))

if not suspicious:
    print("No suspicious writes to $0000/$0001 found.")
    print("The crash might not have happened during capture,")
    print("or the writes use expected values.")
    # Show ALL writes to $0000/$0001 for review
    print("\nAll writes to $0000/$0001:")
    count = 0
    for i in range(total_records):
        word = struct.unpack_from("<I", raw_records, i * 4)[0]
        addr = word & 0xFFFF
        data_byte = (word >> 16) & 0xFF
        rw = (word >> 24) & 0x01
        phi2 = (word >> 31) & 0x01
        if addr <= 0x0001 and rw == 0 and phi2 == 1:
            print(f"  cycle {i}: WRITE ${addr:04X} = ${data_byte:02X}")
            count += 1
            if count > 50:
                print("  ... (truncated)")
                break
else:
    print(f"Found {len(suspicious)} suspicious writes!\n")
    for (cycle_idx, addr, data_byte, nmi, irq) in suspicious[:20]:
        print(f"  cycle {cycle_idx}: WRITE ${addr:04X} = ${data_byte:02X}"
              f"  NMI#={'hi' if nmi else 'LO'} IRQ#={'hi' if irq else 'LO'}")

        # Show surrounding cycles for context (the preceding instructions)
        print(f"    Context (10 cycles before):")
        start = max(0, cycle_idx - 10)
        for j in range(start, cycle_idx + 1):
            w = struct.unpack_from("<I", raw_records, j * 4)[0]
            a = w & 0xFFFF
            d = (w >> 16) & 0xFF
            r = (w >> 24) & 0x01
            p = (w >> 31) & 0x01
            op = "READ " if r else "WRITE"
            mark = " <<<" if j == cycle_idx else ""
            print(f"      [{j}] {op} ${a:04X} = ${d:02X}{mark}")
        print()

# Save raw data for offline analysis
outfile = "debug_trace.raw"
with open(outfile, "wb") as f:
    f.write(raw_records)
print(f"Raw trace saved to {outfile} ({len(raw_records)} bytes)")
print(f"Each record is 4 bytes LE: bits[31:24]=flags, [23:16]=data, [15:0]=addr")
