# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
# vs_env.ps1 -- import the Visual Studio amd64 build environment into THIS
# PowerShell session, resolving VS through the workspace toolchain pin.
# Dot-source it (from vl_build.ps1, a repo's cov.ps1, or anything that needs
# cl/cmake/ninja):
#
#   . "$PSScriptRoot\..\..\..\retrosim-build\tools\vs_env.ps1"   # depth varies
#
# Afterwards: cl.exe is on PATH, and $RetrosimCMake / $RetrosimNinja name VS's
# bundled CMake and Ninja. Also defaults $env:VERILATOR_ROOT from the pinned
# oss-cad-suite when unset. Idempotent: a second dot-source is a no-op.

if (-not $script:RetrosimVsEnvDone) {
    . (Join-Path $PSScriptRoot '..\toolchain.ps1')
    $vs = if ($env:VS_ROOT) { $env:VS_ROOT } else { 'C:\Program Files\Microsoft Visual Studio\18\Insiders' }
    Write-Host "=== importing vcvars amd64 env ($vs) ==="
    cmd /c "`"$vs\VC\Auxiliary\Build\vcvarsall.bat`" amd64 >nul 2>&1 && set" | ForEach-Object {
        if ($_ -match '^([^=]+)=(.*)$') { Set-Item -Path "env:$($matches[1])" -Value $matches[2] }
    }
    $script:RetrosimVsEnvDone = $true
}
$RetrosimVsRoot = if ($env:VS_ROOT) { $env:VS_ROOT } else { 'C:\Program Files\Microsoft Visual Studio\18\Insiders' }
$RetrosimCMake = "$RetrosimVsRoot\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
$RetrosimNinja = "$RetrosimVsRoot\Common7\IDE\CommonExtensions\Microsoft\CMake\Ninja\ninja.exe"
if (-not $env:VERILATOR_ROOT) {
    $ocs = if ($env:OSS_CAD_SUITE) { $env:OSS_CAD_SUITE } else { "$HOME\oss-cad-suite" }
    $env:VERILATOR_ROOT = "$ocs/share/verilator"
}
$cl = (Get-Command cl.exe -ErrorAction SilentlyContinue).Source
Write-Host "cl.exe: $cl"
