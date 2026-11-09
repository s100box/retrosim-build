#!/usr/bin/env bash
# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
# Build Windows-native VAX GNU binutils using MSYS2's MinGW compiler.
# Inputs must already be fetched and signature/hash verified. This script
# neither downloads inputs nor changes the installed MSYS2 packages.
# Usage: bash build-vax-binutils.sh SOURCE BUILD STAGE MAKE [JOBS]
set -euo pipefail

if [[ $# -lt 4 || $# -gt 5 ]]; then
    echo 'usage: build-vax-binutils.sh SOURCE BUILD STAGE MAKE [JOBS]' >&2
    exit 2
fi
source_root=$(cd "$1" && pwd)
build_root=$2
stage_root=$3
make_tool=$4
jobs=${5:-8}
[[ "$jobs" =~ ^[1-9][0-9]*$ ]] || { echo 'invalid job count' >&2; exit 2; }
[[ -f "$source_root/configure" && -x "$make_tool" ]]

export PATH=/mingw64/bin:/usr/bin
# A minimal MSYS2 install may lack diffutils. Use the existing Git for
# Windows copy as a build-only fallback; do not modify either installation.
if ! command -v cmp >/dev/null; then
    export PATH="$PATH:/c/Program Files/Git/usr/bin"
fi
command -v cmp >/dev/null || { echo 'cmp (diffutils) is required' >&2; exit 1; }
export LC_ALL=C
export CONFIG_SHELL=/usr/bin/bash
[[ $(gcc -dumpmachine) == x86_64-w64-mingw32 ]] || {
    echo 'MSYS2 MinGW64 gcc is required; do not use an MSYS-target compiler' >&2
    exit 1
}
mkdir -p "$build_root" "$stage_root"
build_root=$(cd "$build_root" && pwd)
stage_root=$(cd "$stage_root" && pwd)
[[ "$source_root" != "$build_root" && "$build_root" != "$stage_root" ]]
cd "$build_root"

echo "Configuring native VAX binutils; logs: $build_root"
if ! "$source_root/configure" \
    --build=x86_64-w64-mingw32 --host=x86_64-w64-mingw32 \
    --target=vax--netbsdelf --prefix="$stage_root" \
    --disable-nls --disable-werror --disable-gdb --disable-gprofng \
    --disable-dependency-tracking --disable-silent-rules \
    --disable-sim --disable-gold --disable-libctf --disable-shared \
    --enable-static --disable-plugins --without-zlib --without-zstd \
    --without-debuginfod \
    CC=gcc CXX=g++ CFLAGS='-O2' CXXFLAGS='-O2' \
    LDFLAGS='-static -static-libgcc -static-libstdc++' \
    MAKEINFO=true > configure.log 2>&1; then
    tail -n 30 configure.log >&2
    exit 1
fi
echo 'Building assembler, linker, and binary utilities'
if ! "$make_tool" -j"$jobs" V=1 MAKEINFO=true POD2MAN=true all-binutils all-gas all-ld > build.log 2>&1; then
    tail -n 40 build.log >&2
    exit 1
fi
echo 'Installing into the staging directory'
if ! "$make_tool" V=1 MAKEINFO=true POD2MAN=true install-binutils install-gas install-ld > install.log 2>&1; then
    tail -n 30 install.log >&2
    exit 1
fi
mkdir -p "$stage_root/licenses"
cp "$source_root/COPYING" "$source_root/COPYING3" \
   "$source_root/COPYING.LIB" "$source_root/COPYING3.LIB" "$stage_root/licenses/"
# Libtool may retain MinGW's native POSIX-thread library even with the
# static runtime flags above. Bundle it locally; this is not the MSYS DLL.
cp /mingw64/bin/libwinpthread-1.dll "$stage_root/bin/"
cp /mingw64/share/licenses/winpthreads/COPYING "$stage_root/licenses/winpthreads-COPYING"
for tool in as ld objcopy objdump; do
    exe="$stage_root/bin/vax--netbsdelf-$tool.exe"
    [[ -f "$exe" ]]
    "$exe" --version | head -n 1
done
echo 'Build staged; native execution, DLL dependencies, and ROM verification still required.'
