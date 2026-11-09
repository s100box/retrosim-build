# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Keep authored candidates visible while excluding generated scratch trees."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCANNER = Path(__file__).resolve().parents[1] / "tools/async_reset_ram_scan.py"
SOURCE = """module fixture(input clk, rst_n, output [7:0] data);
logic [7:0] memory [0:255];
logic [7:0] addr;
always_ff @(posedge clk or negedge rst_n) begin
  if (!rst_n) addr <= 0;
  else addr <= addr + 1;
end
assign data = memory[addr];
endmodule
"""


class AsyncRamScanTests(unittest.TestCase):
    def test_authored_candidate_is_reported_without_generated_duplicates(self):
        with tempfile.TemporaryDirectory(prefix="ram scan ") as directory:
            root = Path(directory)
            (root / "authored.sv").write_text(SOURCE)
            for name in (".scratch", "build", "impl_board", "node_modules"):
                generated = root / name / "generated.sv"
                generated.parent.mkdir()
                generated.write_text(SOURCE)
            result = subprocess.run([sys.executable, SCANNER, root], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("authored.sv", result.stdout)
            self.assertNotIn("generated.sv", result.stdout)
            self.assertIn("1 candidate(s)", result.stdout)

    def test_synchronous_address_register_is_not_an_async_candidate(self):
        with tempfile.TemporaryDirectory(prefix="ram scan ") as directory:
            root = Path(directory)
            (root / "synchronous.sv").write_text(SOURCE.replace(" or negedge rst_n", ""))
            result = subprocess.run([sys.executable, SCANNER, root], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("synchronous.sv", result.stdout)
            self.assertIn("0 candidate(s)", result.stdout)


if __name__ == "__main__":
    unittest.main()
