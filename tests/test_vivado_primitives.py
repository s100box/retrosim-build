# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Execute Tcl primitives with mocked Vivado commands, without starting Vivado."""
from pathlib import Path
import sys
import tempfile
import unittest
import tkinter

ROOT = Path(__file__).resolve().parents[1]


class VivadoPrimitivesTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="vivado primitives ")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.tcl = tkinter.Tcl()
        self.tcl.call("source", str(ROOT / "vivado.tcl"))
        self.tcl.setvar("env(PYTHON3)", sys.executable)

    def test_project_and_physical_checks(self):
        tcl = self.tcl
        tcl.eval('proc create_project {args} {set ::project_args $args}')
        tcl.call("retrosim::create_project", "example", "output with spaces", "part-number")
        self.assertEqual(tcl.splitlist(tcl.getvar("project_args")), ('-force','example','output with spaces','-part','part-number'))
        tcl.eval('proc filter {ports expression} {return {}}; proc get_cells {args} {return {}}')
        tcl.call("retrosim::check_ports", ("p1", "p2"))
        tcl.call("retrosim::reject_latches")
        tcl.eval('proc get_cells {args} {return {latch1}}')
        with self.assertRaises(tkinter.TclError): tcl.call("retrosim::reject_latches")
        tcl.eval('proc filter {ports expression} {return {bad_port}}')
        with self.assertRaises(tkinter.TclError): tcl.call("retrosim::check_ports", ("bad_port",))

    def test_content_bound_cache_and_owned_invalidation(self):
        root, tcl = self.root, self.tcl
        dependency = root / "config.tcl"; dependency.write_text("first")
        output = root / "output"; ip = output / "ip/instance"; wrapper = ip / "synth/wrapper.v"
        tcl.setvar("wrapper", str(wrapper))
        producer = 'file mkdir [file dirname $wrapper]; set f [open $wrapper w]; puts $f generated; close $f; incr ::builds'
        tcl.setvar("builds", 0)
        def build(settings=()):
            return tcl.call("retrosim::cached_ip", str(ip), str(output), (str(dependency),), str(wrapper), producer, settings)
        self.assertEqual(build(), 1)
        self.assertEqual(build(), 0)
        dependency.write_text("second")
        self.assertEqual(build(), 1)
        self.assertEqual(build(("changed-part",)), 1)
        self.assertEqual(int(tcl.getvar("builds")), 3)
        producer += "; # producer change"
        self.assertEqual(build(("changed-part",)), 1)
        tcl.eval('proc version {args} {return tool-version-one}')
        self.assertEqual(build(("changed-part",)), 1)
        self.assertEqual(build(("changed-part",)), 0)
        tcl.eval('proc version {args} {return tool-version-two}')
        self.assertEqual(build(("changed-part",)), 1)
        with self.assertRaises(tkinter.TclError):
            tcl.call("retrosim::cached_ip", str(root), str(output), (str(dependency),), str(wrapper), producer)
        dependency.write_text("failure invalidates key")
        with self.assertRaises(tkinter.TclError):
            tcl.call("retrosim::cached_ip", str(ip), str(output), (str(dependency),), str(wrapper), 'error failed')
        self.assertFalse((ip / ".retrosim-ip.key").exists())
