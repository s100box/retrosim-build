#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Convert an SDCC Intel HEX image to a flat $readmemh byte-per-line file.

Usage: ihx2mem.py <in.ihx> <out.mem> <size> [fill_hex] [--origin ADDR]
                  [--binary-out FILE]

Produces exactly <size> lines, one two-digit hex byte each, suitable for
Verilog `$readmemh` into a byte array. Gaps are filled with <fill_hex>
(default 00). Records outside [origin, origin+size) are ignored.

`--binary-out` writes the exact same window as raw bytes. This keeps a BRAM
`.mem` image and a separately flashed firmware payload byte-identical without
running a second Intel-HEX converter.

`--origin ADDR` (default 0) is the address the output's byte 0 maps to — set
it for a ROM that is not based at $0000 (e.g. a 6809 ROM at $8000: pass
`--origin 0x8000` so records at $8000..$FFFF land at output lines 0..size-1).

The shared copy for every SDCC firmware/ROM build in the workspace, in
retrosim-build/tools/. Consumers reference it in place (like gowin.sh /
timing_signoff.py); do not re-vendor per repo.
"""
import argparse
import sys


def _int0(s):
    return int(s, 0)


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="ihx2mem.py", description="SDCC Intel HEX -> $readmemh byte-per-line"
    )
    ap.add_argument("infile")
    ap.add_argument("outfile")
    ap.add_argument("size", type=_int0, help="output byte count (== $readmemh depth)")
    ap.add_argument("fill", type=_int0, nargs="?", default=0x00, help="gap fill byte")
    ap.add_argument("--origin", type=_int0, default=0,
                    help="address that maps to output byte 0 (default 0)")
    ap.add_argument("--binary-out", help="also write the same window as raw bytes")
    a = ap.parse_args(argv)

    mem = bytearray([a.fill]) * a.size
    base = 0
    with open(a.infile) as f:
        for line in f:
            line = line.strip()
            if not line or line[0] != ":":
                continue
            n = int(line[1:3], 16)
            addr = int(line[3:7], 16)
            rectype = int(line[7:9], 16)
            data = line[9:9 + 2 * n]
            if rectype == 0x00:            # data
                pos = base + addr - a.origin
                for i in range(n):
                    b = int(data[2 * i:2 * i + 2], 16)
                    if 0 <= pos + i < a.size:
                        mem[pos + i] = b
            elif rectype == 0x01:          # EOF
                break
            elif rectype == 0x02:          # extended segment address
                base = int(data, 16) << 4
            elif rectype == 0x04:          # extended linear address
                base = int(data, 16) << 16
    # newline='\n' forces LF on every platform so the ROM image is byte-stable.
    with open(a.outfile, "w", newline="\n") as f:
        for b in mem:
            f.write("%02X\n" % b)
    if a.binary_out:
        with open(a.binary_out, "wb") as f:
            f.write(mem)
    return 0


if __name__ == "__main__":
    sys.exit(main())
