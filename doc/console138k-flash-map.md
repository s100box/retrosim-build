# The Tang Console 138K's SPI flash, and who claims what

The Console 138K's flash offsets are per-project conventions, not reserved
partitions. The layouts below overlap, so program the data belonging to the
design you load. Measure each build's bitstream before choosing a data offset.

## The part

Sipeed Tang Console 138K (GW5AST-138C), a **W25Q64 — 8 MiB**, `0x000000` to
`0x800000`. One part, one config region at zero, and everything else is
convention.

## What is written to it

| From | To | Size | Who | Measured how |
| --- | --- | ---: | --- | --- |
| `0x000000` | `0x4C0E00` | 4.75 MiB | **hh-tx0** bitstream | counted the `0`/`1` characters in `impl_tx0_console138k/pnr/tx0_console138k.fs`; length varies by build |
| `0x000000` | ~`0x490000` | ~4.7 MB | **a2600box** bitstream | its `WORKFLOW.md`, "the GW5AST-138 config image is ~4.7 MB" |
| `0x000000` | `0x48F000` | 4.56 MiB | **tvi955** bitstream | `gowin.sh`'s own note |
| `0x000000` | `0x4A5C00` | 4.65 MiB | **vt525sim** VT-510 bitstream | counted the `0`/`1` characters in `impl_vt510_console138k/pnr/vt510_console138k.fs`: 38,985,728 bits = 4,873,216 bytes, |
| `0x500000` | ~`0x79A000` | 2.6 MB | **a2600box** ROM container (`roms.img`) | `a2600box/WORKFLOW.md`: "`0x500000` \| ROM container (`roms.img`, 2.6 MB)" |
| `0x500000` | `0x580000` | 512 KiB | **vt525sim** VT-510 ROM blob (`vt510_rom.bin`) | `vt525sim/fpga/build.sh console138k rom-flash`; the size is the part's, 512 KiB exactly. **Overlaps a2600box's container.** |
| `0x580000` | `0x581000` | 4 KiB | **vt525sim** VT-510 saved Set-Up settings | `vt525sim/fpga/src/vt510_nvr_flash.sv`: one sector, magic `"V510NVR1"`, header at +0 and a 1 KiB payload at +0x100. Written by the DESIGN at runtime, not only by a programmer -- see below |
| `0x600000` | `0x640000` | 256 KiB | **hh-tx0** tape shelf (`tapes.img`) | `tools/make_tape_shelf.py`: 8 slots × 32 KiB |
| `0x680000` | ? | ? | **tvi955** hh-usbh 6809 firmware | `gowin.sh`'s note; size not recorded anywhere |
| `0x700000` | `0x780000` | 512 KiB | **v180** `sc503_rom.bin` | `stat` on the file; offset from `v180/WORKFLOW.md` |
| `0x780000` | `0x800000` | 512 KiB | **v180** `rcz80_rom.bin` | same |

## Overlapping layouts

`0x500000` is where the data region starts, and it is the one number every
project already agrees on — it is chosen so a ~4.7 MB config image cannot reach
it. That leaves **3 MiB** above it.

The claims on that 3 MiB come to **more than 4 MiB**: a2600box's 2.6, v180's
1.0, tvi955's firmware, and whatever hh-tx0 takes. They overlap each other
before hh-tx0 asks for anything at all:

- v180's `sc503` at `0x700000` sits **inside** a2600box's container, which
  runs to about `0x79A000`.
- tvi955's firmware at `0x680000` sits inside it too.

**So the part cannot hold every project's data at once, and no rearrangement
makes it.** That is worth knowing rather than fixing: these are different
designs and only one of them is in the FPGA at a time. What it means in
practice is that *whichever design you load, you re-flash its data*, and that a
board which comes up with rubbish where its data should be is far more likely
to be reading somebody else's image than to be broken.

## ⛔ One region is written by a DESIGN, not by a programmer

Every other row in the table above is placed there by someone running a flash
tool. **`0x580000` is not.** The VT-510 design erases and programs that sector
*at runtime*, whenever the terminal's Set-Up settings change — so on a board
running that bitstream, the sector's contents change without anyone asking.

Two consequences for everyone else:

- If your data is at `0x580000` and a VT-510 has been run on the board, assume
  it is gone. That is the same rule as the rest of this page ("re-flash your
  data when you load your design"), but it is the one region where the loss can
  happen while you are not looking.
- The design cannot reach outside that sector. Its addresses are built as
  `{0x580, offset[11:0]}`, so the top twelve bits are a constant and an erase or
  program is structurally incapable of naming another sector. The bench
  (`vt525sim/sim/tb_vt510_nvr_flash.sv`) fails the run if any address escapes,
  which is why that is a claim and not a hope.

## What a project can usefully do

1. **Measure its own bitstream** and put the number in the table above. Not the
   `.fs` file size — that is ASCII, roughly eight times the truth. Count the
   binary digits:
   ```sh
   grep '^[01]' impl_*/pnr/*.fs | tr -d '\r\n' | wc -c   # bits; /8 for bytes
   ```
   Measure every build: the encoded length varies with the design, even on
   the same FPGA part. The bitstream rows above are representative results,
   not fixed reservations.
2. **Claim only the space needed.** For example, hh-tx0 uses eight 32 KiB
   tape slots, for a 256 KiB shelf.
3. **Check, at flash time, that its own data is above its own bitstream** —
   which is the one collision a project can detect by itself, and the one that
   silently destroys the design that is about to run. `hh-tx0/fpga/build.sh`
   does this in `do_flash_check`.
4. **Say what it wrote.** A one-line record in the project's `WORKFLOW.md` and
   a row here.
