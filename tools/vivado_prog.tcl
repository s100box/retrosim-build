# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
# Generic Vivado hardware-manager programmer for the retrosim FPGA repos.
# Driven entirely by env vars from vivado.sh -- no repo-specific knowledge.
#
#   VIVADO_MODE        sram | flash
#   VIVADO_BIT         .bit  (sram mode)
#   VIVADO_MCS         .mcs  (flash mode)
#   VIVADO_CFGMEM_PART get_cfgmem_parts pattern (flash mode)
#   VIVADO_HW_TARGET   substring of the target URL, or "" for the only one

proc env_or {name default} {
  if {[info exists ::env($name)]} { return $::env($name) }
  return $default
}

set mode [env_or VIVADO_MODE sram]
set want [env_or VIVADO_HW_TARGET ""]

open_hw_manager
connect_hw_server

set targets [get_hw_targets]
if {[llength $targets] == 0} {
  error "no JTAG targets found -- is the board powered and the USB cable in?"
}
if {$want ne ""} {
  set targets [lsearch -all -inline $targets *$want*]
  if {[llength $targets] == 0} {
    error "no JTAG target matching '$want' (attached: [get_hw_targets])"
  }
}
if {[llength $targets] > 1} {
  error "several JTAG targets attached ([join $targets {, }]) -- set VIVADO_TARGET"
}

current_hw_target [lindex $targets 0]
open_hw_target
set dev [lindex [get_hw_devices] 0]
current_hw_device $dev
refresh_hw_device -update_hw_probes false $dev
puts "target [lindex $targets 0] device $dev"

if {$mode eq "sram"} {
  set bit $::env(VIVADO_BIT)
  set_property PROGRAM.FILE $bit $dev
  program_hw_devices $dev
  refresh_hw_device $dev
  puts "loaded $bit (volatile -- gone at power-off)"
} else {
  set mcs  $::env(VIVADO_MCS)
  set part $::env(VIVADO_CFGMEM_PART)
  set memp [lindex [get_cfgmem_parts $part] 0]
  if {$memp eq ""} { error "no cfgmem part matching '$part'" }
  create_hw_cfgmem -hw_device $dev -mem_dev $memp
  set cfg [get_property PROGRAM.HW_CFGMEM $dev]
  set_property PROGRAM.BLANK_CHECK  0     $cfg
  set_property PROGRAM.ERASE        1     $cfg
  set_property PROGRAM.CFG_PROGRAM  1     $cfg
  set_property PROGRAM.VERIFY       1     $cfg
  set_property PROGRAM.CHECKSUM     0     $cfg
  set_property PROGRAM.ADDRESS_RANGE {use_file} $cfg
  set_property PROGRAM.FILES        [list $mcs] $cfg
  set_property PROGRAM.UNUSED_PIN_TERMINATION {pull-none} $cfg
  create_hw_bitstream -hw_device $dev [get_property PROGRAM.HW_CFGMEM_BITFILE $dev]
  program_hw_devices $dev
  program_hw_cfgmem -hw_cfgmem $cfg
  # Booting from flash is only meaningful when the MCS actually carries a
  # bitstream at address 0. A DATA-region image (a diagnostic at 0x500000,
  # written with -loaddata and no -loadbit) does not, so boot_hw_device sits
  # there for its full 180 s timeout and then fails -- AFTER a programming
  # pass that succeeded. That reads as "flashing is broken" when nothing is
  # wrong with it. VIVADO_CFGMEM_BOOT=0 says "the data landed, leave the
  # running device alone"; the caller reloads the bitstream itself.
  if {[env_or VIVADO_CFGMEM_BOOT 1] ne "0"} {
    boot_hw_device $dev
    puts "programmed $mcs to flash and rebooted the device"
  } else {
    puts "programmed $mcs to flash (data region; device not rebooted)"
  }
}

close_hw_target
disconnect_hw_server
