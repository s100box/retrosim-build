# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
cmake_minimum_required(VERSION 3.20)
if(POLICY CMP0144)
  cmake_policy(SET CMP0144 NEW)
endif()
project(retrosim_verilator_msvc CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
find_package(verilator REQUIRED)
include(${CMAKE_CURRENT_LIST_DIR}/../verilator.cmake)

set(TOP "" CACHE STRING "SystemVerilog bench top")
set(SRCS "" CACHE STRING "Absolute SystemVerilog source list")
set(VDEFS "" CACHE STRING "Additional Verilator arguments")
# A bench with its own C++ driver (MAIN, an absolute path) and, with TIMING
# OFF, no --timing: the driver clocks it (as --savable requires).
set(MAIN "" CACHE STRING "C++ driver in place of sim_main.cpp")
option(TIMING "Build with --timing" ON)
# A header forced into every translation unit, the generated ones too
# (vl_save_queue.h: what --savable needs for queues).
set(FORCE_INCLUDE "" CACHE STRING "Header forced into every C++ source")
if(NOT TOP OR NOT SRCS)
  message(FATAL_ERROR "TOP and SRCS are required; use tools/verilator_msvc.py")
endif()

if(MAIN)
  add_executable(${TOP}_vl ${MAIN})
else()
  add_executable(${TOP}_vl sim_main.cpp)
endif()
if(TIMING)
  set(TIMING_ARG --timing)
else()
  set(TIMING_ARG --no-timing)
endif()
retrosim_verilate(${TOP}_vl
  TOP_MODULE ${TOP}
  PREFIX V${TOP}
  THREADS 1
  SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/tbpins.vlt ${SRCS}
  VERILATOR_ARGS
    ${TIMING_ARG} -O3 -DSIM
    --x-assign 0 --x-initial 0
    -Wno-WIDTH -Wno-WIDTHEXPAND -Wno-WIDTHTRUNC -Wno-CASEINCOMPLETE
    -Wno-UNUSEDSIGNAL -Wno-UNUSEDPARAM -Wno-UNDRIVEN -Wno-SELRANGE
    -Wno-IMPLICIT -Wno-TIMESCALEMOD -Wno-MULTIDRIVEN
    # -Werror-, not -Wno-: an unconnected INPUT is silent in every other tool
    # here, and -Wno-fatal below does not soften a -Werror-. tbpins.vlt (added
    # to SOURCES above, so it applies to every bench this driver builds)
    # waives it for tb_*.sv, where omitting a DUT output is legitimate.
    -Werror-PINMISSING
    -Wno-CASEOVERLAP -Wno-BLKANDNBLK -Wno-fatal
    ${VDEFS}
)
target_compile_definitions(${TOP}_vl PRIVATE VTOP_H="V${TOP}.h" VTOP_CLASS=V${TOP})
if(MSVC)
  # Timing/coverage benches can put large temporary arrays on the main stack.
  # Reserve address space rather than inheriting MSVC's 1 MiB default, which
  # terminates the HDMI bench with STATUS_STACK_OVERFLOW before it can log.
  target_link_options(${TOP}_vl PRIVATE /STACK:67108864)
endif()
if(FORCE_INCLUDE)
  target_compile_options(${TOP}_vl PRIVATE "/FI${FORCE_INCLUDE}")
endif()
