# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
# Per-top ArgsFile CMake adapter. The receipt is published only after a
# successful build and executable copy; failures always invalidate it.
param(
    [Parameter(Mandatory=$true)][string]$SourceDir,
    [Parameter(Mandatory=$true)][string]$Top,
    [Parameter(Mandatory=$true)][string]$ArgsFile,
    [ValidateSet('vl','cov')][string]$Variant = 'vl',
    [string]$DestinationDir = '../obj_dir',
    [int]$Jobs = 0
)
$ErrorActionPreference = 'Continue'
if ($Top -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') { throw 'Invalid bench top' }
if ($Jobs -lt 0) { throw 'Jobs must be nonnegative' }
if ($env:VSINSTALL) { $env:VS_ROOT = $env:VSINSTALL }
. (Join-Path $PSScriptRoot 'vs_env.ps1')
$oss = $env:OSS_CAD_SUITE
if ($oss) { $env:Path = "$oss\bin;$oss\lib;" + $env:Path }
Set-Location $SourceDir
$SourceDir = (Get-Location).Path
$ArgsFile = (Resolve-Path -LiteralPath $ArgsFile).Path
$items = @(Get-Content -LiteralPath $ArgsFile | Where-Object { $_ -ne '' })
$vdefs = @($items | Where-Object { $_.StartsWith('-') })
$srcs = @($items | Where-Object { -not $_.StartsWith('-') })
# Some vendor CMake dependency parsers split source filenames at spaces.
# Use filesystem aliases for the compiler, while hashing the original paths.
if (-not ('RetrosimShortPath' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public static class RetrosimShortPath {
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode)]
    public static extern uint GetShortPathName(string path, StringBuilder output, uint size);
}
'@
}
function Convert-CompilerPath([string]$path) {
    $absolute = [IO.Path]::GetFullPath($path)
    if ($absolute.Contains(' ')) {
        $buffer = New-Object Text.StringBuilder 32768
        $size = [RetrosimShortPath]::GetShortPathName($absolute, $buffer, $buffer.Capacity)
        if ($size -eq 0 -or $size -ge $buffer.Capacity -or $buffer.ToString().Contains(' ')) {
            throw "The Verilator CMake integration requires a source alias without spaces: $absolute"
        }
        $absolute = $buffer.ToString()
    }
    return $absolute.Replace('\','/')
}
$srcs = @($srcs | ForEach-Object { Convert-CompilerPath $_ })
$vdefs = @($vdefs | ForEach-Object { if ($_.StartsWith('-I')) { '-I' + (Convert-CompilerPath $_.Substring(2)) } else { $_ } })
$bdir = if ($Variant -eq 'cov') { "build-cov-$Top" } else { "build-$Top" }
New-Item -ItemType Directory -Force -Path $bdir | Out-Null
$cmakeSource = Convert-CompilerPath $SourceDir
$cmakeBuild = Convert-CompilerPath (Join-Path $SourceDir $bdir)
$covflag = if ($Variant -eq 'cov') { 'ON' } else { 'OFF' }
$destination = Join-Path $DestinationDir "${Top}_$Variant.exe"
$snap = Join-Path $bdir 'configure.key'
$python = if ($env:PYTHON3) { $env:PYTHON3 } else { 'python' }
$toolArgs = @('--tool', $RetrosimCMake, '--tool', $RetrosimNinja)
$clPath = (Get-Command cl.exe -ErrorAction Stop).Source
$toolArgs += @('--tool', $clPath, '--tool', (Join-Path $env:VERILATOR_ROOT '../../bin/verilator_bin.exe'))
$toolArgs += @('--tool', $PSCommandPath, '--tool', (Join-Path $PSScriptRoot 'vs_env.ps1'))
$toolArgs += @('--tool', (Join-Path $PSScriptRoot '../toolchain.ps1'), '--tool', (Join-Path $PSScriptRoot '../toolchain.ninja'))
$want = & $python (Join-Path $PSScriptRoot 'build_key.py') $SourceDir $ArgsFile `
    --setting "TOP=$Top" --setting "VL_COVERAGE=$covflag" `
    --setting "VERILATOR_ROOT=$env:VERILATOR_ROOT" --include-root "$env:VERILATOR_ROOT" @toolArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$have = if (Test-Path -LiteralPath $snap) { [IO.File]::ReadAllText((Join-Path $SourceDir $snap)).Trim() } else { '' }
if ($want -ne $have -or -not (Test-Path "$bdir/build.ninja")) {
    Remove-Item -LiteralPath $snap -ErrorAction SilentlyContinue
    # A changed tool identity must also discard CMake's cached compiler path.
    # --fresh clears CMake-owned metadata while retaining build outputs.
    & $RetrosimCMake --fresh -G Ninja -S $cmakeSource -B $cmakeBuild -DCMAKE_BUILD_TYPE=Release `
        "-DCMAKE_MAKE_PROGRAM=$RetrosimNinja" "-DCMAKE_PREFIX_PATH=$env:VERILATOR_ROOT" `
        "-DTOP=$Top" "-DVL_COVERAGE=$covflag" ("-DSRCS=" + ($srcs -join ';')) ("-DVDEFS=" + ($vdefs -join ';'))
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else { Write-Host "configure ($Top): unchanged" }
$buildArgs = @('--build', $cmakeBuild)
if ($Jobs -gt 0) { $buildArgs += @('--parallel', "$Jobs") }
& $RetrosimCMake @buildArgs
if ($LASTEXITCODE -ne 0) { Remove-Item -LiteralPath $snap -ErrorAction SilentlyContinue; exit $LASTEXITCODE }
$exe = Join-Path $bdir "${Top}_vl.exe"
if (-not (Test-Path -LiteralPath $exe)) { Remove-Item -LiteralPath $snap -ErrorAction SilentlyContinue; throw "Missing $exe" }
New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
$copied = $false
for ($i=0; $i -lt 5 -and -not $copied; $i++) {
    try { Copy-Item -LiteralPath $exe -Destination $destination -Force -ErrorAction Stop; $copied=$true }
    catch { Start-Sleep -Seconds 2 }
}
if (-not $copied) { Remove-Item -LiteralPath $snap -ErrorAction SilentlyContinue; throw "Cannot publish $destination (locked?)" }
[IO.File]::WriteAllText((Join-Path $SourceDir $snap), "$want")
Write-Host "OK: $destination"
