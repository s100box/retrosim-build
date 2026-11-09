# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
include_guard(GLOBAL)

# Verilator's JSON exporter interpolates this result into generated CMake
# source lists. Quote each element there so a source/build path with spaces
# remains one argument. Keep this adapter beside the split-list refresh.
function(json_get_list output manifest section field)
  string(JSON count ERROR_VARIABLE error LENGTH "${manifest}" "${section}" "${field}")
  if(NOT error STREQUAL "NOTFOUND" OR count EQUAL 0)
    set(${output} "" PARENT_SCOPE)
    return()
  endif()
  math(EXPR last "${count} - 1")
  set(result "")
  foreach(index RANGE ${last})
    string(JSON item GET "${manifest}" "${section}" "${field}" ${index})
    string(REPLACE "\\" "\\\\" item "${item}")
    string(REPLACE "\"" "\\\"" item "${item}")
    string(REPLACE "$" "\\$" item "${item}")
    string(APPEND result " \"${item}\"")
  endforeach()
  set(${output} "${result}" PARENT_SCOPE)
endfunction()

# Call after find_package(verilator). JSON-based Verilator releases regenerate
# C++ during a build but convert the JSON split-source list only at configure
# time. Refresh that list before Ninja chooses objects to compile and link.
function(retrosim_verilate target)
  cmake_parse_arguments(RV "" "PREFIX;DIRECTORY" "" ${ARGN})
  if(NOT RV_PREFIX OR NOT RV_PREFIX MATCHES "^[A-Za-z_][A-Za-z0-9_]*$")
    message(FATAL_ERROR "retrosim_verilate requires an explicit C++ PREFIX")
  endif()
  get_target_property(binary_dir ${target} BINARY_DIR)
  file(REAL_PATH "${binary_dir}" owned_root)
  if(RV_DIRECTORY)
    if(NOT IS_ABSOLUTE "${RV_DIRECTORY}")
      message(FATAL_ERROR "Verilator DIRECTORY must be absolute and inside the build tree")
    endif()
    set(generated_dir "${RV_DIRECTORY}")
  else()
    set(generated_dir "${binary_dir}/CMakeFiles/${target}.dir/${RV_PREFIX}.dir")
  endif()
  cmake_path(ABSOLUTE_PATH generated_dir NORMALIZE OUTPUT_VARIABLE generated_real)
  cmake_path(IS_PREFIX owned_root "${generated_real}" NORMALIZE owned)
  if(NOT owned OR generated_real STREQUAL owned_root)
    message(FATAL_ERROR "Verilator generated directory must be inside the build tree")
  endif()
  set(existing "${generated_real}")
  while(NOT EXISTS "${existing}")
    get_filename_component(existing "${existing}" DIRECTORY)
  endwhile()
  file(REAL_PATH "${existing}" existing_real)
  cmake_path(IS_PREFIX owned_root "${existing_real}" NORMALIZE owned)
  if(NOT owned)
    message(FATAL_ERROR "Verilator generated directory resolves outside the build tree")
  endif()

  # Remove one generator receipt, retaining handwritten files and cached C++
  # objects. Unchanged Verilator output keeps its timestamps and incremental
  # compilation; a changed split set is available during this configure pass.
  file(REMOVE "${generated_real}/verilator_args.txt")
  # Its separate timestamp cache can otherwise skip regeneration even here,
  # particularly for included files. CMake already decides when to reconfigure.
  verilate(${target} ${ARGN} VERILATOR_ARGS --no-skip-identical)

  # Verilator attaches its discovered HDL/includes to the target. Watch those
  # inputs so direct cmake --build also configures before regenerating C++.
  get_target_property(inputs ${target} SOURCES)
  get_target_property(interface_inputs ${target} INTERFACE_SOURCES)
  foreach(input IN LISTS inputs interface_inputs)
    if(input MATCHES "\\.(v|sv|vh|svh|vlt|f)$" AND NOT input MATCHES "^\\$<")
      get_filename_component(input "${input}" ABSOLUTE BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
      set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${input}")
    endif()
  endforeach()
endfunction()
