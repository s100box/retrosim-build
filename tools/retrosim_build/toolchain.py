# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Read the shared Ninja pin without invoking Ninja or a shell."""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import shutil

ROOT = Path(__file__).resolve().parents[2]
ROOTS = {"VS_ROOT": "vs_root", "OSS_CAD_SUITE": "oss_cad_suite",
         "VERIBLE_ROOT": "verible_root", "GOWIN_ROOT": "gowin_root",
         "SDCC_ROOT": "sdcc_root", "SDCC_M6809_ROOT": "sdcc_m6809_root",
         "VAX_BINUTILS_ROOT": "vax_binutils_root"}
TOOLS = {"GWSH": ("gowin_root", "IDE/bin/gw_sh.exe", "gw_sh"),
         "PROGRAMMER_CLI": ("gowin_root", "Programmer/bin/programmer_cli.exe", "programmer_cli"),
         "VIVADO": ("vivado_root", "bin/vivado.bat", "vivado"),
         "BASH_EXE": ("bash_exe", "", "bash"),
         "IVERILOG": ("oss_cad_suite", "bin/iverilog.exe", "iverilog"),
         "VVP": ("oss_cad_suite", "bin/vvp.exe", "vvp"),
         "VERILATOR": ("oss_cad_suite", "bin/verilator.exe", "verilator"),
         "VERILATOR_COVERAGE": ("oss_cad_suite", "bin/verilator_coverage.exe", "verilator_coverage")}


def read_pins(path=ROOT / "toolchain.ninja"):
    raw = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Za-z_][\w]*)\s*=\s*(.*?)\s*$", line)
        if match:
            raw[match[1]] = match[2]
    def expand(name, seen=()):
        if name in seen:
            raise ValueError("cyclic toolchain variable: " + name)
        if name not in raw:
            raise ValueError("undefined toolchain variable: " + name)
        value = raw[name].replace("$$", "\0")
        return re.sub(r"\$\{(\w+)\}|\$(\w+)",
                      lambda m: expand(m[1] or m[2], (*seen, name)), value).replace("\0", "$")
    return {name: expand(name) for name in raw}


@dataclass(frozen=True)
class Selection:
    path: str
    source: str

    def provenance(self):
        path = Path(self.path)
        return {"path": str(path.resolve()), "source": self.source,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None}


class Toolchain:
    def __init__(self, pin=ROOT / "toolchain.ninja", environ=None):
        self.pin = Path(pin)
        self.environ = dict(os.environ if environ is None else environ)
        self.pins = read_pins(self.pin)

    def resolve(self, name, *, required=True):
        aliases = ("VSINSTALL", "VS_ROOT") if name == "VS_ROOT" else (name,)
        for alias in aliases:
            value = self.environ.get(alias)
            live = value and (Path(value).is_dir() if name in ROOTS or name == "VERILATOR_ROOT" else Path(value).is_file())
            if live:
                return Selection(value, "environment:" + alias)
        if name in ROOTS:
            value = self.pins.get(ROOTS[name])
            if value and Path(value).is_dir():
                return Selection(value, "pin:" + ROOTS[name])
        elif name == "VERILATOR_ROOT":
            root = self.resolve("OSS_CAD_SUITE", required=False)
            if root and (Path(root.path) / "share/verilator").is_dir():
                return Selection(str(Path(root.path) / "share/verilator"), root.source)
        elif name in TOOLS:
            key, suffix, fallback = TOOLS[name]
            base = self.pins.get(key)
            root_env = next((var for var, pin in ROOTS.items() if pin == key), None)
            if root_env:
                selected = self.resolve(root_env, required=False)
                base = selected.path if selected else base
            if base:
                candidate = Path(base) / suffix if suffix else Path(base)
                candidates = [candidate]
                if candidate.suffix == ".exe":
                    if os.name == "nt":
                        stem = candidate.with_suffix("")
                        candidates += [Path(str(stem) + "_bin.exe"), Path(str(stem) + "_bin_dbg.exe")]
                    else:
                        candidates.append(candidate.with_suffix(""))
                for path in candidates:
                    if path.is_file():
                        return Selection(str(path), "pin:" + key if not root_env or not selected else selected.source)
            found = shutil.which(fallback, path=self.environ.get("PATH", ""))
            if found:
                return Selection(found, "PATH")
        else:
            raise ValueError("unknown toolchain selection: " + name)
        if required:
            raise FileNotFoundError(f"{name}: configure {self.pin} or set a live {name} override")
        return None

    def environment(self):
        env = self.environ.copy()
        for name in (*ROOTS, "VERILATOR_ROOT", *TOOLS):
            selection = self.resolve(name, required=False)
            if selection:
                env[name] = selection.path
        paths = []
        if env.get("OSS_CAD_SUITE"):
            paths += [str(Path(env["OSS_CAD_SUITE"]) / part) for part in ("bin", "lib")]
        if env.get("VERIBLE_ROOT"):
            paths.insert(0, env["VERIBLE_ROOT"])
        env["PATH"] = os.pathsep.join([*paths, env.get("PATH", "")])
        return env
