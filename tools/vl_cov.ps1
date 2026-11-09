# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
# vl_cov.ps1 -- the standard Verilator code-coverage suite driver: build the
# coverage twins of a repository's self-checking benches (its sim/vl
# CMakeLists with VL_COVERAGE=ON) into sim/vl/build/cov, run every vl-*.exe
# twin (plus any -Extra exe), merge, and render the lcov .info and the
# --annotate tree under build/cov/report. A repository's sim/vl/cov.ps1 is:
#
#   param([switch]$NoBuild)
#   & "$PSScriptRoot\..\..\..\retrosim-build\tools\vl_cov.ps1" -VlRoot $PSScriptRoot -NoBuild:$NoBuild
#   exit $LASTEXITCODE
#
# Each twin runs from sim/ (or -WorkDir), with Verilator's own
# +verilator+coverage+file+ plusarg naming its .dat; the verdict rules are
# Invoke-VlCovRun's in vl_cov_lib.ps1. Exit 1 when the build fails, nothing is
# produced, or any run reports FAIL. Opt-in, not a gate: instrumentation costs
# sim speed. doc/coverage.md is then refreshed by `python tools/cov_summary.py`.

param(
    [Parameter(Mandatory = $true)][string]$VlRoot,
    [switch]$NoBuild,
    [string[]]$Targets = @(),          # cmake --build --target (default: all)
    [string[]]$Extra = @(),            # further twin exe names under build/cov to run
    [string]$WorkDir = '',             # run directory (default: sim/)
    [string]$PassPattern = 'PASS',
    [string]$FailPattern = 'FAIL|%Error|%Fatal',
    [switch]$RequirePass               # a run that prints neither pattern FAILs
)

. (Join-Path $PSScriptRoot 'vl_cov_lib.ps1')
Initialize-VlCov -VlRoot $VlRoot

if (-not $NoBuild) {
    if (-not (Build-VlCov -Targets $Targets)) { exit 1 }
}

$exes = @(Get-ChildItem -Path $VlCov.Cov -Filter 'vl-*.exe' | Sort-Object Name)
foreach ($x in $Extra) {
    $p = Join-Path $VlCov.Cov $x
    if (Test-Path $p) { $exes += Get-Item $p }
}
if ($exes.Count -eq 0) { Write-Host "cov: FAIL -- no vl-*.exe twins in $($VlCov.Cov)."; exit 1 }

foreach ($exe in $exes) {
    $name = $exe.BaseName -replace '^vl-', ''
    Invoke-VlCovRun -Name $name -Exe $exe.FullName -WorkDir $WorkDir `
        -PassPattern $PassPattern -FailPattern $FailPattern -RequirePass:$RequirePass
}
exit (Complete-VlCov)
