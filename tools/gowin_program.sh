#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
# Internal dispatch for program_fpga.py, after its freshness and timing checks.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$here/../gowin.sh"
gowin_board "$1"
mode=$2 artifact=$3 expected=$4
shift 4
[ -z "$expected" ] || [ "$expected" = "$GOWIN_DEVICE" ] || {
    echo "program: device $expected does not match $GOWIN_DEVICE" >&2; exit 2;
}
[ -x "$PROG" ] || { echo "program: no programmer at $PROG" >&2; exit 127; }
_gowin_program_artifact "$artifact" "$mode" --device "$GOWIN_DEVICE" "$@"
