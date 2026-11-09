# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
# vl_cov_lib.ps1 -- the shared steps of a repository's Verilator code-coverage
# suite (sim/vl/cov.ps1). Dot-source it, then:
#
#   Initialize-VlCov -VlRoot $PSScriptRoot          # paths + the toolchain pin
#   if (-not $NoBuild) { if (-not (Build-VlCov)) { exit 1 } }
#   Invoke-VlCovRun -Name tb_x -Exe (Join-Path $VlCov.Cov 'vl-tb_x.exe')
#   ...
#   exit (Complete-VlCov)                           # merge + .info + annotate
#
# Layout under <VlRoot>\<BuildDir> (default build\cov): the CMake build of the
# coverage twins, dat\cov_<run>.dat per run, and report\ holding
# merged_<group>.dat, cov_<group>.info and annotate_<group>\ for the group
# "all" (every run) plus each group a run was tagged with. A repository's
# tools/cov_summary.py (retrosim-build/tools/cov_summary_lib.py) renders
# doc/coverage.md from report\.
#
# A repository whose suite is "run every vl-*.exe twin" needs none of this
# directly: tools/vl_cov.ps1 is the whole driver.

$ErrorActionPreference = 'Continue'

# Native stderr arrives as ErrorRecords under 2>&1; take their text (an empty
# stderr line would otherwise print as "System.Management.Automation.RemoteException").
filter ConvertTo-VlCovLine {
    if ($_ -is [System.Management.Automation.ErrorRecord]) { $_.Exception.Message } else { "$_" }
}

function Initialize-VlCov {
    param(
        [Parameter(Mandatory = $true)][string]$VlRoot,
        [string]$BuildDir = 'build\cov'
    )
    . (Join-Path $PSScriptRoot '..\toolchain.ps1')
    $oss = if ($env:OSS_CAD_SUITE) { $env:OSS_CAD_SUITE } else { "$HOME/oss-cad-suite" }
    $vroot = ($oss -replace '\\', '/') + '/share/verilator'
    $cov = Join-Path $VlRoot $BuildDir
    $script:VlCov = [pscustomobject]@{
        VlRoot   = $VlRoot
        Sim      = Split-Path $VlRoot -Parent
        Cov      = $cov
        Dat      = Join-Path $cov 'dat'
        Rep      = Join-Path $cov 'report'
        VRoot    = $vroot
        # The verilator_coverage wrapper is perl; call the binary directly.
        VCov     = "$vroot/bin/verilator_coverage_bin_dbg.exe"
        Produced = [System.Collections.ArrayList]::new()
        Fails    = [System.Collections.ArrayList]::new()
    }
    if (-not (Test-Path $script:VlCov.VCov)) {
        Write-Host "cov: FAIL -- $($script:VlCov.VCov) not found (OSS_CAD_SUITE / toolchain pin)."
        exit 1
    }
    New-Item -ItemType Directory -Force -Path $script:VlCov.Dat | Out-Null
}

# Configure + build the coverage twins (VL_COVERAGE=ON) into $VlCov.Cov, or
# into -BuildDir (relative to VlRoot) for a repository that builds one tree
# per bench. Returns $false on a failed configure/build, on an UNOPTFLAT
# warning under -FailOnUnoptflat (an UNOPTFLAT under -Wno-fatal splits a comb
# loop and silently over-counts comb coverage), or when a -Require'd exe is
# missing afterwards.
function Build-VlCov {
    param(
        [string]$BuildDir = '',
        [string[]]$CMakeArgs = @(),
        [string[]]$Targets = @(),
        [string[]]$Require = @(),
        [switch]$FailOnUnoptflat
    )
    $v = $script:VlCov
    $bdir = if ($BuildDir) { Join-Path $v.VlRoot $BuildDir } else { $v.Cov }
    $env:VERILATOR_ROOT = $v.VRoot
    . (Join-Path $PSScriptRoot 'vs_env.ps1')
    Write-Host "=== Configure (VL_COVERAGE=ON -> $bdir) ==="
    $cfg = & $RetrosimCMake -G Ninja -S $v.VlRoot -B $bdir -DCMAKE_BUILD_TYPE=Release -DVL_COVERAGE=ON `
        "-DCMAKE_MAKE_PROGRAM=$RetrosimNinja" "-DCMAKE_PREFIX_PATH=$($v.VRoot)" @CMakeArgs 2>&1 | ConvertTo-VlCovLine
    $rc = $LASTEXITCODE
    $cfg | Select-Object -Last 3 | ForEach-Object { Write-Host "    $_" }
    if ($rc -ne 0) {
        $cfg | Select-Object -Last 30 | ForEach-Object { Write-Host "    $_" }
        Write-Host "cov: FAIL -- configure error (rc=$rc)."; return $false
    }
    Write-Host '=== Build (coverage twins) ==='
    $build = if ($Targets.Count -gt 0) {
        & $RetrosimCMake --build $bdir --target @Targets 2>&1 | ConvertTo-VlCovLine
    } else {
        & $RetrosimCMake --build $bdir 2>&1 | ConvertTo-VlCovLine
    }
    $rc = $LASTEXITCODE
    if ($rc -ne 0) {
        $build | Select-String -Pattern 'error|FAILED|%Error' | Select-Object -Last 20 |
            ForEach-Object { Write-Host "    $_" }
        Write-Host "cov: FAIL -- build error (rc=$rc)."; return $false
    }
    $build | Select-Object -Last 2 | ForEach-Object { Write-Host "    $_" }
    if ($FailOnUnoptflat) {
        $unopt = @($cfg + $build) -match 'UNOPTFLAT'
        if ($unopt) {
            Write-Host 'cov: FAIL -- UNOPTFLAT in the coverage build (would over-count comb coverage):'
            $unopt | ForEach-Object { Write-Host "    $_" }
            return $false
        }
        Write-Host 'cov: UNOPTFLAT-clean.'
    }
    foreach ($r in $Require) {
        if (-not (Test-Path (Join-Path $bdir $r))) {
            Write-Host "cov: FAIL -- the coverage build produced no $r."; return $false
        }
    }
    return $true
}

# Run one coverage twin; it writes $VlCov.Dat\cov_<Name>.dat. Verdict: FAIL
# when the exe exits nonzero or its output case-sensitively matches
# -FailPattern, PASS when it matches -PassPattern, otherwise "done" (a
# coverage-only run that does not self-check; FAIL under -RequirePass). -Show prints the last output
# line matching it; -Tail prints the last N lines (always 15 on a FAIL).
# -DatArg is the plusarg that names the .dat: Verilator's own by default, or a
# bench main's (e.g. '+covdat=').
function Invoke-VlCovRun {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Exe,
        [string[]]$Arguments = @(),
        [string]$Group = '',
        [string]$WorkDir = '',
        [string]$DatArg = '+verilator+coverage+file+',
        [string]$PassPattern = 'PASS',
        [string]$FailPattern = 'FAIL|%Error|%Fatal',
        [string]$Show = '',
        [int]$Tail = 0,
        [switch]$RequirePass,
        [switch]$AllowFail
    )
    $v = $script:VlCov
    if (-not (Test-Path $Exe)) { Write-Host ("cov: {0,-22} SKIP (no twin: {1})" -f $Name, $Exe); return }
    $d = Join-Path $v.Dat "cov_$Name.dat"
    if (Test-Path $d) { Remove-Item $d -Force }
    $wd = if ($WorkDir) { $WorkDir } else { $v.Sim }
    Push-Location $wd
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $out = @(& $Exe @Arguments "$DatArg$d" 2>&1 | ConvertTo-VlCovLine)
    $rc = $LASTEXITCODE
    $sw.Stop()
    Pop-Location
    $text = $out -join "`n"
    $verdict = if ($rc -ne 0 -or ($FailPattern -and $text -cmatch $FailPattern)) { 'FAIL' } `
               elseif ($PassPattern -and $text -match $PassPattern) { 'PASS' } else { 'done' }
    if ($verdict -eq 'done' -and $RequirePass) { $verdict = 'FAIL' }
    if ($verdict -eq 'FAIL' -and $AllowFail) { $verdict = 'done (fail allowed)' }
    $tag = if ($Group) { " [$Group]" } else { '' }
    $nodat = if (Test-Path $d) { '' } else { ' (NO .dat)' }
    Write-Host ("cov: {0,-22} {1}{2}{3} ({4:N1}s, rc={5})" -f $Name, $verdict, $tag, $nodat, $sw.Elapsed.TotalSeconds, $rc)
    if ($Show) {
        $out | Where-Object { $_ -match $Show } | Select-Object -Last 1 | ForEach-Object { Write-Host "    $_" }
    }
    $n = if ($verdict -eq 'FAIL') { [Math]::Max($Tail, 15) } else { $Tail }
    if ($n -gt 0) { $out | Select-Object -Last $n | ForEach-Object { Write-Host "    $_" } }
    if ($verdict -eq 'FAIL') { [void]$v.Fails.Add($Name) }
    if (Test-Path $d) { [void]$v.Produced.Add([pscustomobject]@{ Name = $Name; Group = $Group; Dat = $d }) }
}

# Record a failure the caller detected itself (e.g. an oracle divergence).
function Add-VlCovFail([string]$Name) { [void]$script:VlCov.Fails.Add($Name) }

function Merge-VlCovGroup([string]$Label, [string[]]$Dats) {
    $v = $script:VlCov
    $Dats = @($Dats)
    if ($Dats.Count -eq 0) { return }
    $merged = Join-Path $v.Rep "merged_$Label.dat"
    $info = Join-Path $v.Rep "cov_$Label.info"
    $ann = Join-Path $v.Rep "annotate_$Label"
    Write-Host "=== merge [$Label] : $($Dats.Count) dat ==="
    & $v.VCov --write $merged @Dats 2>&1 | Select-Object -Last 2 | ForEach-Object { Write-Host "    $_" }
    & $v.VCov --write-info $info $merged 2>&1 | Out-Null
    if (Test-Path $ann) { Remove-Item $ann -Recurse -Force }
    & $v.VCov --annotate $ann --annotate-min 1 $merged 2>&1 | Out-Null
    Write-Host "cov: [$Label] merged=$merged info=$info annotate=$ann/"
}

# Merge every run into "all" and each tagged group into its own, then report.
# Returns the exit code: 1 when nothing was produced or any run failed.
function Complete-VlCov {
    $v = $script:VlCov
    if ($v.Produced.Count -eq 0) { Write-Host 'cov: FAIL -- no coverage .dat produced.'; return 1 }
    New-Item -ItemType Directory -Force -Path $v.Rep | Out-Null
    Get-ChildItem $v.Rep -Filter 'merged_*.dat' -ErrorAction SilentlyContinue | Remove-Item -Force
    Merge-VlCovGroup 'all' ($v.Produced | ForEach-Object { $_.Dat })
    $groups = $v.Produced | Where-Object { $_.Group } | ForEach-Object { $_.Group } | Select-Object -Unique
    foreach ($g in $groups) {
        Merge-VlCovGroup $g ($v.Produced | Where-Object { $_.Group -eq $g } | ForEach-Object { $_.Dat })
    }
    Write-Host ''
    Write-Host "cov: DONE. $($v.Produced.Count) runs merged. Reports in $($v.Rep)"
    Write-Host 'cov: refresh the committed baseline with:  python tools/cov_summary.py'
    if ($v.Fails.Count -gt 0) {
        Write-Host "cov: FAIL -- runs reporting FAIL: $($v.Fails -join ', ')"
        return 1
    }
    return 0
}
