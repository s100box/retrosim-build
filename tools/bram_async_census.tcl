# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
# ============================================================================
# bram_async_census.tcl -- find registers with an ASYNCHRONOUS reset that reach
# a block RAM address or enable (Vivado REQP-1839/1840), anywhere in the fleet.
#
# WHY THIS EXISTS. The rule is Vivado's, so a Gowin-only repo never looks --
# hh-emac carried the hazard in two adapters for weeks after their Artix-7 twin
# was fixed, for no reason but that nothing on that flow runs the check. But a
# repo does NOT need an A7-Lite target to be checked: synth_design in
# OUT-OF-CONTEXT mode needs no pins, no board, no XDC, and the rule is a netlist
# check that runs perfectly well on the result. That is what this does.
#
# Verified with a positive AND negative control before being trusted: hh-hdmi's
# edid_i2c reports 10 violations at its pre-fix commit and 0 after, from the
# same OOC flow.
#
# Env in:
#   CENSUS_FILES  space-separated HDL files, in compile order
#   CENSUS_TOP    top module (use the design's REAL top -- a leaf synthesized
#                 alone hides every violation whose driving register lives in a
#                 parent, which is how the worst one in hdmi-tester hid)
#   CENSUS_PART   optional, defaults to the A7-Lite part
#   CENSUS_NAME   label for the report
#
# Prints one RESULT line, then one line per DISTINCT violation. Deduplicated on
# purpose: report_drc caps a rule at 20, and scoping with -cells changes which
# cells it WALKS, not which violations come back -- so counting per scope
# multiplies the truth. See the workspace note on report_drc truncation.
# ============================================================================

set files [split $::env(CENSUS_FILES)]
set top   $::env(CENSUS_TOP)
set name  [expr {[info exists ::env(CENSUS_NAME)] ? $::env(CENSUS_NAME) : $top}]
set part  [expr {[info exists ::env(CENSUS_PART)] ? $::env(CENSUS_PART) : "xc7a200tfbg484-2"}]

set ok 1
foreach f $files {
    if {[string trim $f] eq ""} { continue }
    if {![file exists $f]} { puts "census: MISSING $f"; set ok 0; continue }
    if {[catch {
        if {[string match "*.sv" $f] || [string match "*.svh" $f]} {
            read_verilog -quiet -sv $f
        } else {
            read_verilog -quiet $f
        }
    } msg]} {
        puts "census: READ FAILED $f: $msg"
        set ok 0
    }
}
if {!$ok} { puts "RESULT $name : SKIPPED (file list did not read)" ; exit 0 }

# Vendor primitives (Gowin PLL/DCS/OSER10/ELVDS_OBUF, ...) become black boxes.
# That is fine and is not a reason to skip: the memories and their address
# registers are ordinary fabric either way, which is all this rule looks at.
# NO -quiet HERE. With it, a failed synth_design returns without raising, the
# design is empty, and the census cheerfully reports "0 violations" -- a silent
# false clean, which is the one outcome this tool must never produce.
if {[catch {synth_design -mode out_of_context -top $top -part $part} msg]} {
    puts "RESULT $name : SKIPPED (synth failed: [string range $msg 0 200])"
    exit 0
}

# A verdict is only meaningful if something was actually built. An empty or
# trivial netlist means the file list or the top was wrong, not that the design
# is clean -- say so rather than banking a pass.
set ncells [llength [get_cells -hier -quiet]]
set nbram  [llength [get_cells -hier -quiet -filter {REF_NAME =~ RAMB*}]]
set nlut   [llength [get_cells -hier -quiet -filter {REF_NAME =~ RAM*X* || REF_NAME =~ RAM*M*}]]
if {$ncells < 50} {
    puts "RESULT $name : INCONCLUSIVE (only $ncells cells synthesized -- bad file list or top?)"
    exit 0
}
if {$nbram == 0} {
    puts "RESULT $name : NO BLOCK RAM ($ncells cells, $nlut distributed-RAM cell(s)) -- REQP-1839/1840 only covers RAMB, so this is not a pass; check by hand whether the design's arrays should be block RAM on the Gowin part"
    exit 0
}

report_drc -quiet -name census -checks [get_drc_checks {REQP-1839 REQP-1840}]
array set seen {}
foreach v [get_drc_violations -quiet -name census] {
    set seen([get_property DESCRIPTION $v]) 1
}
set n [array size seen]
puts "RESULT $name : $n violation(s) over $nbram block RAM(s), $ncells cells"

# Condense each violation to the bit that matters: which RAM, which pin, which
# driving register. The full sentence is identical every time and unreadable in
# bulk.
foreach d [lsort [array names seen]] {
    set ram ""; set pin ""; set drv ""
    regexp {The (?:RAMB\S+) (\S+) has an input control pin \S+/(\S+?)(?:\[\d+\])? \(} $d -> ram pin
    regexp {driven by a register \((\S+?)(?:\[\d+\])?\)} $d -> drv
    puts "   $ram | $pin | $drv"
}
