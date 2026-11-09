#!/usr/bin/env python3
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
"""Shared engine for the per-repo Gowin .gprj generators.

Each retrosim repo keeps a thin tools/gen_gprj.py SHIM that declares its
board/variant matrix (device metadata, fileset names, output paths, header
comment) and calls into this library for everything mechanical: loading the
FuseSoC .core filesets, resolving file lists, emitting + validating the
project XML, the --check drift gate, and --stage-config.

The gw_sh build.tcl flow remains the canonical build everywhere; the .gprj
GUI projects only mirror it. See retrosim-build/README.md.
"""
import os
import shutil
import sys
import xml.dom.minidom

try:
    import yaml
except ImportError:
    sys.exit("gen_gprj: PyYAML required (pip install pyyaml)")

GPRJ_TYPE = {"systemVerilogSource": "file.verilog", "verilogSource": "file.verilog",
             "CST": "file.cst", "SDC": "file.sdc"}

# The one Gowin board table for .gprj generation -- the Python mirror of
# gowin.sh's gowin_board() (device + part) plus the Gowin IDE's device-id
# string the .gprj needs. Canonical board names only (see
# retrosim-build/README.md). Repo shims take a row and add their own
# fileset/dir/base keys:  dict(**lib.GOWIN_BOARDS["nano20k"], fileset=...).
# ⚠ Keep device/part in lockstep with gowin.sh's table.
GOWIN_BOARDS = {
    "nano20k":     dict(name="GW2AR-18C", pn="GW2AR-LV18QN88C8/I7",
                        devid="gw2ar18c-000"),
    # primer20k devid verified against the installed Gowin IDE's
    # device_info.csv (pn GW2A-LV18PG256C8/I7, PBGA256, speed C8/I7).
    "primer20k":   dict(name="GW2A-18C", pn="GW2A-LV18PG256C8/I7",
                        devid="gw2a18c-011"),
    "console60k":  dict(name="GW5AT-60B", pn="GW5AT-LV60PG484AC1/I0",
                        devid="gw5at60b-002"),
    "console138k": dict(name="GW5AST-138C", pn="GW5AST-LV138PG484AC1/I0",
                        devid="gw5ast138c-007"),
    "mega138kpro": dict(name="GW5AST-138B", pn="GW5AST-LV138FPG676AC1/I0",
                        devid="gw5ast138b-007"),
    # primer25k devid verified against the installed Gowin IDE's
    # device_info.csv (pn GW5A-LV25MG121NES).
    "primer25k":   dict(name="GW5A-25A", pn="GW5A-LV25MG121NES",
                        devid="gw5a25a-000"),
}


def load_filesets(core_path):
    with open(core_path, encoding="utf-8") as fh:
        core = yaml.safe_load(fh)
    return core["filesets"]


def fileset_files(filesets, name):
    """Return [(repo_relative_path, gprj_type), ...] for a fileset, in order."""
    fs = filesets[name]
    default_ft = fs.get("file_type", "systemVerilogSource")
    out = []
    for entry in fs["files"]:
        if isinstance(entry, dict):
            (path, attrs), = entry.items()
            ft = attrs.get("file_type", default_ft)
        else:
            path, ft = entry, default_ft
        out.append((path, GPRJ_TYPE[ft]))
    return out


def file_lines(repo, project_dir, group):
    """Render one group of <File .../> lines, paths relative to the .gprj dir."""
    def rel(path):
        return os.path.relpath(os.path.join(repo, path), project_dir).replace("\\", "/")
    return "\n".join(
        f'        <File path="{rel(p)}" type="{t}" enable="1"/>' for p, t in group)


def project_xml(repo, project_dir, device, header, groups):
    """The full .gprj document.

    device = dict(name=, pn=, devid=); header = the generated-file comment
    body (no <!-- -->); groups = [(comment_or_None, [(path, type), ...]), ...].
    """
    body = []
    for comment, group in groups:
        if comment is not None:
            body.append(f"        <!-- {comment} -->")
        body.append(file_lines(repo, project_dir, group))
    filelist = "\n".join(body)
    return f"""<?xml version="1" encoding="UTF-8"?>
<!DOCTYPE gowin-fpga-project>
<!-- {header} -->
<Project>
    <Template>FPGA</Template>
    <Version>5</Version>
    <Device name="{device['name']}" pn="{device['pn']}">{device['devid']}</Device>
    <FileList>
{filelist}
    </FileList>
</Project>
"""


def stage_config(repo, path):
    """Stage the committed process_config.json beside the .gprj into impl/.

    The Gowin IDE keeps its synthesis/PnR settings in
    impl/<project>_process_config.json, but impl/ is wiped on a clean. The
    canonical copy is committed next to the .gprj; copy it into impl/ so the
    project opens with those settings. No-op (with a note) when absent.
    """
    project_dir = os.path.dirname(path)
    cfg = os.path.splitext(os.path.basename(path))[0] + "_process_config.json"
    src = os.path.join(project_dir, cfg)
    if not os.path.exists(src):
        print(f"skip:  {cfg} (no committed copy beside {os.path.basename(path)})")
        return
    impl = os.path.join(project_dir, "impl")
    os.makedirs(impl, exist_ok=True)
    shutil.copyfile(src, os.path.join(impl, cfg))
    print(f"staged {os.path.relpath(os.path.join(impl, cfg), repo)}")


def run(repo, projects, check=False, do_stage_config=False):
    """The main loop. projects = [(gprj_path, xml_text), ...].

    check: verify on-disk files match (exit 1 on drift). do_stage_config:
    only stage the process configs. Otherwise write + stage. Every document
    is minidom-validated first (Gowin's strict XML reader rejects e.g. '--'
    inside a comment as 'Invalid project file').
    """
    drift = False
    for path, want in projects:
        xml.dom.minidom.parseString(want)
        if check:
            have = open(path, encoding="utf-8").read() if os.path.exists(path) else ""
            if have != want:
                drift = True
                print(f"DRIFT: {os.path.relpath(path, repo)} is out of date "
                      f"(run: python tools/gen_gprj.py)")
            else:
                print(f"ok:    {os.path.relpath(path, repo)}")
        elif do_stage_config:
            stage_config(repo, path)
        else:
            with open(path, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(want)
            print(f"wrote  {os.path.relpath(path, repo)}")
            stage_config(repo, path)
    if check and drift:
        sys.exit(1)
