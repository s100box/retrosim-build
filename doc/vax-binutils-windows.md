<!-- SPDX-License-Identifier: MIT OR Apache-2.0 -->
<!-- SPDX-FileCopyrightText: 2026 Howard M. Harte -->

# Native Windows VAX binutils

## Purpose

Provide GNU VAX assembler, linker, disassembler, and binary utilities that run
directly in PowerShell or native Python, without WSL or an MSYS runtime DLL.
The first use is the KA49 ROM reconstruction (`../../nvax-docs/doc/ka49-rom-reconstruction.md`).
GNU syntax is the working source notation; this is not a MACRO-32 assembler.

Build the pinned official GNU release with an MSYS2 MinGW64 compiler. MSYS2 supplies build-time shell tools;
the resulting MinGW executables must be checked outside that environment.
See [MSYS2 environments](https://www.msys2.org/docs/environments/).

The tools have been verified on native Windows.
The installed location is the `vax_binutils_root` entry in
[`toolchain.ninja`](../toolchain.ninja). There are 15 x64 PE executables and
one bundled native DLL. No global PATH change is required.

## Pinned build inputs

| Input | Provenance |
|---|---|
| GNU binutils 2.47 | [Official release directory](https://ftp.gnu.org/gnu/binutils/), `binutils-2.47.tar.xz` and its detached `.sig` |
| Release keyring | `https://ftp.gnu.org/gnu/gnu-keyring.gpg`, fetched over HTTPS |
| Host compiler | Existing `C:/msys64/mingw64/bin/gcc.exe`, GCC 13.2.0, MSYS2 Rev6, target `x86_64-w64-mingw32` |
| Build make | [MSYS2 package archive](https://repo.msys2.org/msys/x86_64/), `make-4.4.1-2-x86_64.pkg.tar.zst` and its detached `.sig` |
| Build shell/runtime | Existing `C:/msys64`, MSYS2 runtime 3.4.10-4 |

SHA-256 pins:

```text
154ab23b60070e8f27013c22977f1129425d67d1e8acd6e13010e617811e4cff  binutils-2.47.tar.xz
9fa42a8770ff1fdb3059a6d5c7b7030899acee58b343364bc42b6facfa35ce65  binutils-2.47.tar.xz.sig
b136fbe57ade4ee5270ca66c402cae7b50349fd07646b5b3de7962d58d4df608  gnu-keyring.gpg
2408af61717dae87b00c855b132769a125c708907fc94a46bb16dae076113e5c  make-4.4.1-2-x86_64.pkg.tar.zst
1d0c1b5be33fb34ad910a23a595c11ffcde67f959c13e3bd404bcc0471660673  make-4.4.1-2-x86_64.pkg.tar.zst.sig
```

GnuPG verified the binutils release signature with fingerprint
`3A24BC1E8FB409FA9F14371813FCEF89DD9E3C4F` (Nick Clifton, Chief Binutils
Maintainer), using GNU's downloaded keyring. It verified the make package
signature with fingerprint `5F944B027F7FE2091985AA2EFA11531AA0AA7F57`
(Christoph Reiter, MSYS2 development key), from the installed MSYS2 keyring.
The isolated verification key database has no personal web-of-trust
certifications; the release authorities are the HTTPS-distributed keyrings.
Signature verification was not disabled.

Fetched inputs are cached in `nvax-docs/refs/dl/toolchains/`; extracted sources,
the isolated GPG directory, bootstrap make, logs, and staging installation
are under `nvax-docs/refs/work/windows-vax-binutils/`. Both locations are
ignored by the documentation repository.
## Rebuilding

Obtain the archives and signatures from the official locations above, verify
their SHA-256 values, and verify their detached signatures before extraction.
Use an isolated GPG home. The installed MSYS2 `msys2.gpg` is ASCII-armored;
import it into that isolated database rather than treating it as a binary
keyring. Public-key verification needs no secret-key agent.

Extract binutils into `src/` and the make package into `bootstrap/` in the
working directory. Only `bootstrap/usr/bin/make.exe` is needed from the make
package. This does not require a package-manager update or replacing any
files in `C:/msys64`.

From the workspace root in PowerShell:

```powershell
$work = (Resolve-Path nvax-docs/refs/work/windows-vax-binutils).Path
& C:/msys64/usr/bin/bash.exe --noprofile --norc `
  retrosim-build/tools/build-vax-binutils.sh `
  "$work/src/binutils-2.47" "$work/build" "$work/stage" `
  "$work/bootstrap/usr/bin/make.exe" 8
```

[`build-vax-binutils.sh`](../tools/build-vax-binutils.sh) selects the MinGW
compiler and uses an out-of-source build. It configures `vax--netbsdelf` as
the target, builds `all-binutils`, `all-gas`, and `all-ld`, then installs only
those components into the staging directory. NLS, plugins, zlib, zstd,
debuginfod, libctf, GDB, and gprofng are disabled. Static runtime flags are
requested, but libtool retains a dependency on `libwinpthread-1.dll`; the
script bundles the existing native MinGW DLL and its license. This DLL is
not the MSYS POSIX runtime. Record the complete executable version string from `--version` in
verification profiles, including any upstream snapshot suffix.

`MAKEINFO=true POD2MAN=true` skips regeneration of documentation, so this
package is for the command-line tools and does not claim a complete set of
generated manuals. Use GNU's online manuals. Dependency tracking and silent
rules are disabled to avoid an automake/Windows `depcomp` command issue.
The existing Git for Windows `cmp` is a build-only fallback when MSYS2 lacks
diffutils. The GPL/LGPL notices are copied into `licenses/`. Logs are
`configure.log`, `build.log`, and `install.log`.

Before accepting or installing a build:

1. Inspect the PE imports of each `.exe`; reject dependencies on MSYS,
   Cygwin, or any unbundled non-Windows runtime. The bundled native
   `libwinpthread-1.dll` is allowed; inspect its imports too.
2. Run the executables from PowerShell with `PATH` limited to the installed
   tool directory and Windows system directories.
3. Run the KA49 slice verifier using native Windows Python. It must check
   section VMA/LMA, sizes, and exact ROM bytes, not just tool version output.
4. Keep source provenance, executable SHA-256 hashes, and the verification
   report. A new binutils release needs explicit version-policy validation.

Installation belongs in its own versioned directory and must not overwrite
other toolchains. The location belongs in the shared
[`toolchain.ninja`](../toolchain.ninja) pin as `vax_binutils_root`, exported by
[`toolchain.ps1`](../toolchain.ps1) as `VAX_BINUTILS_ROOT`. An explicit
environment override or verifier `--prefix` takes precedence. No machine-wide
PATH modification is necessary.

## Verification result

All 16 native files were inspected as x64 PE images. The executables import
only `KERNEL32.dll`, `msvcrt.dll`, and, where needed, the bundled
`libwinpthread-1.dll`. That DLL itself imports only the two Windows DLLs.
The installation's `manifest.json` records every native file's SHA-256,
size, and imports, plus the upstream source hash and release signer. Files
were hash-checked again after installation.

With PATH limited to Windows system directories, native Python successfully
ran the assembler, linker, section extraction, address checks, and byte
comparison for all three initial KA49 source sections: **63/524,288 bytes**.
The native disassembler also read the raw ROM entry as
`31 fd 1f` / `brw 0x20042000`. This establishes initial tool operation, not
complete VAX instruction coverage or complete ROM reconstruction.

From `nvax-docs`, with native Python available:

```powershell
python tools/ka49/verify_slices.py
```

The verifier locates the native installation through the shared pin. Its
JSON report records host, source hashes, tool hashes, section addresses, and
comparison results. To invoke tools directly from the workspace root:

```powershell
. ./retrosim-build/toolchain.ps1
& "$env:VAX_BINUTILS_ROOT/bin/vax--netbsdelf-objdump.exe" --version
```
