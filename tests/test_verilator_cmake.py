# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Exercise CMake's configure-time Verilator cache policy without a compiler."""
from pathlib import Path
import json
import shutil
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
from retrosim_build.toolchain import Toolchain


class VerilatorCmakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='verilator cmake ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.build = self.root / 'build'
        self.cmake = shutil.which('cmake')
        vs = Toolchain().resolve('VS_ROOT', required=False)
        if not self.cmake:
            candidate = Path(vs.path) / 'Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe' if vs else None
            if not candidate or not candidate.is_file():
                self.skipTest('CMake is required for the Verilator integration-policy tests')
            self.cmake = str(candidate)
        self.ninja = shutil.which('ninja')
        if not self.ninja:
            candidate = Path(vs.path) / 'Common7/IDE/CommonExtensions/Microsoft/CMake/Ninja/ninja.exe' if vs else None
            if not candidate or not candidate.is_file():
                self.skipTest('Ninja is required for the CMake fixture')
            self.ninja = str(candidate)
        (self.source / 'top.sv').write_text('first')
        (self.source / 'included.svh').write_text('include')

    def configure(self, directory=''):
        helper = TOOLS / 'verilator.cmake'
        # The fake generator models the real integration's argument-only cache:
        # the C++ split set is rebuilt only when verilator_args.txt is absent.
        # Without the shared helper, editing HDL leaves the stale split set.
        use = f'include("{helper.as_posix()}")' if helper.exists() else ''
        call = 'retrosim_verilate' if helper.exists() else 'verilate'
        text = '''cmake_minimum_required(VERSION 3.20)
project(fixture NONE)
add_library(model INTERFACE)
function(verilate target)
  set(gen "${CMAKE_CURRENT_BINARY_DIR}/CMakeFiles/model.dir/Vmodel.dir")
  file(MAKE_DIRECTORY "${gen}")
  if(NOT EXISTS "${gen}/verilator_args.txt")
    file(READ "${CMAKE_CURRENT_SOURCE_DIR}/top.sv" shape)
    file(WRITE "${gen}/split-set" "${shape}")
    file(WRITE "${gen}/verilator_args.txt" "same command")
  endif()
  target_sources(model INTERFACE "${CMAKE_CURRENT_SOURCE_DIR}/top.sv" "${CMAKE_CURRENT_SOURCE_DIR}/included.svh")
endfunction()
''' + use + f'\n{call}(model PREFIX Vmodel SOURCES "${{CMAKE_CURRENT_SOURCE_DIR}}/top.sv" {directory})\n'
        text += 'get_property(watched DIRECTORY PROPERTY CMAKE_CONFIGURE_DEPENDS)\nfile(WRITE "${CMAKE_CURRENT_BINARY_DIR}/watched" "${watched}")\n'
        (self.source / 'CMakeLists.txt').write_text(text)
        return subprocess.run([self.cmake, '-G', 'Ninja', '-DCMAKE_MAKE_PROGRAM='+self.ninja,
                               '-S', str(self.source), '-B', str(self.build)], capture_output=True, text=True)

    def test_changed_hdl_refreshes_split_set_and_watches_includes(self):
        result = self.configure()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        metadata = self.build / 'CMakeFiles/model.dir/Vmodel.dir'
        sentinel = metadata / 'handwritten-sentinel'
        sentinel.write_text('keep')
        (self.source / 'top.sv').write_text('expanded split set')
        result = self.configure()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((metadata / 'split-set').read_text(), 'expanded split set')
        self.assertEqual(sentinel.read_text(), 'keep')
        watched = (self.build / 'watched').read_text()
        self.assertIn('top.sv', watched)
        self.assertIn('included.svh', watched)

    def test_external_generated_directory_is_refused_without_modification(self):
        outside = self.root / 'external'
        outside.mkdir()
        sentinel = outside / 'verilator_args.txt'
        sentinel.write_text('preserve external cache')
        result = self.configure(f'DIRECTORY "{outside.as_posix()}"')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(sentinel.read_text(), 'preserve external cache')

    def test_json_lists_round_trip_spaces_quotes_and_literal_variables(self):
        values = ['path with spaces/file.cpp', 'a"quoted.cpp', '${UNDEFINED}/literal.cpp', r'back\slash']
        manifest = json.dumps({'sources': {'deps': values, 'empty': []}})
        script = self.root / 'quote.cmake'
        script.write_text(f'''include("{(TOOLS / 'verilator.cmake').as_posix()}")
set(manifest [==[{manifest}]==])
json_get_list(result "${{manifest}}" sources deps)
file(WRITE "{self.root.as_posix()}/list.cmake" "set(values ${{result}})\\n")
include("{self.root.as_posix()}/list.cmake")
foreach(value IN LISTS values)
  file(APPEND "{self.root.as_posix()}/round-trip" "${{value}}\\n")
endforeach()
json_get_list(empty "${{manifest}}" sources empty)
json_get_list(missing "${{manifest}}" sources absent)
if(NOT empty STREQUAL "" OR NOT missing STREQUAL "")
  message(FATAL_ERROR "missing/empty list was not empty")
endif()
''')
        result = subprocess.run([self.cmake, '-P', script], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.root / 'round-trip').read_text().splitlines(), values)


if __name__ == '__main__':
    unittest.main()
