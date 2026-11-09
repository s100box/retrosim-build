# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
# vl_build.ps1 -- the shared Verilator-with-MSVC CMake build driver.
# A consumer shim invokes it as follows:
#
#   & "$PSScriptRoot\..\..\..\retrosim-build\tools\vl_build.ps1" `
#       -SourceDir $PSScriptRoot [-CMakeArgs @('-DFOO=1')] [-Targets bench_a]
#   exit $LASTEXITCODE
#
# Imports the VS amd64 environment (vs_env.ps1, resolved through the
# workspace toolchain pin), configures the repo's own CMakeLists with VS's
# bundled CMake + Ninja and find_package(verilator) from $env:VERILATOR_ROOT,
# then builds. The repo keeps full ownership of its CMakeLists/benches; only
# the driver plumbing is shared.

param(
    [Parameter(Mandatory = $true)][string]$SourceDir,
    [string]$BuildDir = 'build',
    [string]$BuildType = 'Release',
    [string[]]$CMakeArgs = @(),
    [string[]]$Targets = @(),
    [string]$ArgsFile = '',
    [string]$Top = '',
    [switch]$Coverage,
    [string]$DestinationDir = '../obj_dir',
    [int]$Jobs = 0
)
$ErrorActionPreference = 'Continue'
if ($Jobs -lt 0) { throw 'Jobs must be nonnegative' }
if ($ArgsFile) {
    if (-not $Top) { throw 'ArgsFile builds require Top' }
    $variant = if ($Coverage) { 'cov' } else { 'vl' }
    & (Join-Path $PSScriptRoot 'vl_snapshot.ps1') -SourceDir $SourceDir -Top $Top `
        -ArgsFile $ArgsFile -Variant $variant -DestinationDir $DestinationDir -Jobs $Jobs
    exit $LASTEXITCODE
}

. (Join-Path $PSScriptRoot 'vs_env.ps1')

Set-Location $SourceDir
Write-Host '=== Configure ==='
& $RetrosimCMake -G Ninja -B $BuildDir "-DCMAKE_BUILD_TYPE=$BuildType" `
    "-DCMAKE_MAKE_PROGRAM=$RetrosimNinja" "-DCMAKE_PREFIX_PATH=$env:VERILATOR_ROOT" `
    @CMakeArgs
Write-Host "CFG_RC=$LASTEXITCODE"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host '=== Build ==='
$buildArgs = @('--build', $BuildDir)
if ($Targets.Count -gt 0) { $buildArgs += @('--target') + $Targets }
if ($Jobs -gt 0) { $buildArgs += @('--parallel', "$Jobs") }
& $RetrosimCMake @buildArgs
Write-Host "BUILD_RC=$LASTEXITCODE"
exit $LASTEXITCODE
