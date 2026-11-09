# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Opt-in real Windows CMake/MSVC cache regression; no boards or vendor EDA."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
from retrosim_build.toolchain import Toolchain
from verilator_msvc import vcvars_environment


@unittest.skipUnless(os.name == 'nt', 'native Windows integration')
class IncrementalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='verilator incremental ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.build = self.root / 'build'
        tc = Toolchain()
        vs = Path(tc.resolve('VS_ROOT').path)
        self.cmake = vs / 'Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe'
        self.ninja = vs / 'Common7/IDE/CommonExtensions/Microsoft/CMake/Ninja/ninja.exe'
        oss = Path(tc.resolve('OSS_CAD_SUITE').path)
        env = dict(os.environ, VERILATOR_ROOT=(oss/'share/verilator').as_posix(), PYTHON3=Path(sys.executable).as_posix())
        env['PATH'] = os.pathsep.join([str(oss/'bin'),str(oss/'lib'),env.get('PATH','')])
        self.env = vcvars_environment(vs/'VC/Auxiliary/Build/vcvarsall.bat',env)
        (self.root/'top.sv').write_text('''`timescale 1ns/1ps
module tb_incremental;
reg clk = 0;
always #5 clk = ~clk;
reg [31:0] value [0:63];
`include "shape.svh"
initial begin
  repeat (8) @(negedge clk);
  for (integer i=0; i<COUNT; i=i+1)
    if (value[i] !== i+3) $fatal(1, "bad coroutine result");
  $display("INCREMENTAL PASS count=%0d", COUNT);
  $finish;
end
endmodule
''')

    def command(self, args, *, passed=True):
        result = subprocess.run([str(a) for a in args],cwd=self.root,env=self.env,capture_output=True,text=True)
        if passed:
            self.assertEqual(result.returncode,0,result.stdout[-6000:]+result.stderr[-6000:])
        else:
            self.assertNotEqual(result.returncode,0,'broken HDL unexpectedly compiled')
        return result.stdout+result.stderr

    def shape(self, count):
        t = f'localparam integer COUNT={count};\n'
        for i in range(count):
            t += f'initial begin value[{i}]={i}; repeat (3) begin @(posedge clk); value[{i}] <= value[{i}]+1; end end\n'
        (self.root/'shape.svh').write_text(t)

    def exercise(self, consumer):
        self.shape(2)
        if consumer:
            (self.root/'anchor.cpp').write_text('int anchor = 0;\n')
            (self.root/'CMakeLists.txt').write_text(f'''cmake_minimum_required(VERSION 3.20)
project(consumer CXX)
set(CMAKE_CXX_STANDARD 20)
find_package(verilator REQUIRED)
include("{(TOOLS/'verilator.cmake').as_posix()}")
add_executable(model anchor.cpp)
retrosim_verilate(model PREFIX Vtb_incremental TOP_MODULE tb_incremental
 SOURCES "${{CMAKE_CURRENT_SOURCE_DIR}}/top.sv"
 VERILATOR_ARGS --timing --main --coverage-line --output-split 100 --output-split-cfuncs 10 -Wno-fatal
 "-I${{CMAKE_CURRENT_SOURCE_DIR}}")
''')
            self.command([self.cmake,'-G','Ninja','-S',self.root,'-B',self.build,
                          '-DCMAKE_MAKE_PROGRAM='+str(self.ninja),'-DCMAKE_PREFIX_PATH='+self.env['VERILATOR_ROOT']])
            self.command([self.cmake,'--build',self.build])
            exe = self.build/'model.exe'
        else:
            self.command([sys.executable,TOOLS/'verilator_msvc.py','--top','tb_incremental',
                          '--build-dir',self.build,'--source',self.root/'top.sv',
                          '--verilator-arg=-I'+str(self.root),'--verilator-arg=--coverage-line',
                          '--verilator-arg=--output-split','--verilator-arg=100','--verilator-arg=--output-split-cfuncs','--verilator-arg=10'])
            exe = self.build/'tb_incremental_vl.exe'
        self.assertIn('INCREMENTAL PASS count=2',self.command([exe]))
        before = len(list(self.build.rglob('Vtb_incremental*.cpp')))
        self.shape(64)
        # Build directly: included HDL changes must trigger configure, refresh
        # the JSON-derived split set, and compile every newly generated helper.
        self.command([self.cmake,'--build',self.build])
        after = len(list(self.build.rglob('Vtb_incremental*.cpp')))
        self.assertGreater(after,before,'fixture did not change the C++ split set')
        self.assertIn('INCREMENTAL PASS count=64',self.command([exe]))
        with (self.root/'shape.svh').open('a') as f:
            f.write('\nthis is invalid HDL;\n')
        self.command([self.cmake,'--build',self.build],passed=False)

    def test_native_driver(self):
        self.exercise(False)

    def test_consumer_cmake(self):
        self.exercise(True)


if __name__ == '__main__':
    unittest.main()
