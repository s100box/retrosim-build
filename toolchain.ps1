# SPDX-License-Identifier: MIT OR Apache-2.0
# SPDX-FileCopyrightText: 2026 Howard M. Harte
# toolchain.ps1 -- PowerShell side of the workspace toolchain pin. Dot-source
# from any repo script instead of hardcoding a tool install path:
#
#   . "$PSScriptRoot\..\..\retrosim-build\toolchain.ps1"   # depth varies
#
# Parses ..\toolchain.ninja (THE single file a version bump edits) and exports
# the standard tool env vars -- but ONLY where the variable is not already set,
# so an explicit environment override always wins. Missing installs are left
# unset rather than pointed at a dead path.
#
# Exports (when resolvable): GWSH, PROGRAMMER_CLI, GOWIN_ROOT, VERIBLE_ROOT,
# OSS_CAD_SUITE, VS_ROOT, SDCC_ROOT, SDCC_M6809_ROOT, VAX_BINUTILS_ROOT.

$script:_tcPin = Join-Path $PSScriptRoot 'toolchain.ninja'

function script:Get-ToolchainPin([string]$name) {
    if (-not (Test-Path $script:_tcPin)) { return $null }
    foreach ($line in Get-Content $script:_tcPin) {
        if ($line -match "^$name\s*=\s*(.+?)\s*$") { return $Matches[1] }
    }
    return $null
}

# A set-but-DEAD env path (a long-running shell that predates a toolchain
# reinstall) falls through to the pin with a warning -- same contract as
# gowin.sh. An env var that points at a real file always wins.
foreach ($stale in 'GWSH', 'PROGRAMMER_CLI', 'GOWIN_ROOT') {
    $cur = (Get-Item -Path "Env:$stale" -ErrorAction SilentlyContinue).Value
    if ($cur -and -not (Test-Path $cur)) {
        Write-Warning "toolchain.ps1: ignoring stale $stale ($cur does not exist); using the pin"
        Remove-Item -Path "Env:$stale" -ErrorAction SilentlyContinue
    }
}

$gowinRoot = Get-ToolchainPin 'gowin_root'
if ($gowinRoot -and (Test-Path $gowinRoot)) {
    if (-not $env:GOWIN_ROOT) { $env:GOWIN_ROOT = $gowinRoot }
    $gwsh = Join-Path $gowinRoot 'IDE\bin\gw_sh.exe'
    $pcli = Join-Path $gowinRoot 'Programmer\bin\programmer_cli.exe'
    if (-not $env:GWSH -and (Test-Path $gwsh)) { $env:GWSH = $gwsh }
    if (-not $env:PROGRAMMER_CLI -and (Test-Path $pcli)) { $env:PROGRAMMER_CLI = $pcli }
}

$vivadoRoot = Get-ToolchainPin 'vivado_root'
if ($vivadoRoot -and -not $env:VIVADO) {
    $vbat = Join-Path $vivadoRoot 'bin\vivado.bat'
    if (Test-Path $vbat) { $env:VIVADO = $vbat }
}

foreach ($pair in @(
        @{ pin = 'verible_root';  var = 'VERIBLE_ROOT' },
        @{ pin = 'oss_cad_suite'; var = 'OSS_CAD_SUITE' },
        @{ pin = 'vs_root';       var = 'VS_ROOT' },
        @{ pin = 'sdcc_root';     var = 'SDCC_ROOT' },
        @{ pin = 'sdcc_m6809_root'; var = 'SDCC_M6809_ROOT' },
        @{ pin = 'vax_binutils_root'; var = 'VAX_BINUTILS_ROOT' })) {
    if (-not (Get-Item -Path "Env:$($pair.var)" -ErrorAction SilentlyContinue)) {
        $val = Get-ToolchainPin $pair.pin
        if ($val -and (Test-Path $val)) { Set-Item -Path "Env:$($pair.var)" -Value $val }
    }
}
