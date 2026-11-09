# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Bounded child processes with fresh logs and explicit verdicts."""
from dataclasses import dataclass
import os
from pathlib import Path
import re
import signal
import subprocess


@dataclass
class Result:
    returncode: int
    timed_out: bool
    log: Path

    def passed(self, pattern=None):
        return self.returncode == 0 and not self.timed_out and (
            pattern is None or re.search(pattern, self.log.read_text(encoding="utf-8", errors="replace"), re.M) is not None)


def run(argv, *, cwd, log, timeout=300, env=None):
    if timeout <= 0:
        raise ValueError("timeout must be positive")
    log = Path(log)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("w", encoding="utf-8") as stream:
        try:
            process = subprocess.Popen([str(x) for x in argv], cwd=cwd, env=env,
                                       stdout=stream, stderr=subprocess.STDOUT,
                                       start_new_session=os.name != "nt")
        except OSError as error:
            stream.write(str(error) + "\n")
            return Result(127, False, log)
        try:
            code = process.wait(timeout=timeout)
            if code:
                status = f" (0x{code & 0xffffffff:08x})" if os.name == "nt" else ""
                stream.write(f"\nPROCESS EXIT: {code}{status}\n")
            return Result(code, False, log)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass  # The child may exit between the timeout and kill.
            process.kill()
            process.wait()
            stream.write("\nTIMEOUT\n")
            return Result(124, True, log)
