# Build the Windows installer: PyInstaller bundle + Inno Setup.
# Usage: packaging\build-windows.ps1 [-Version 1.0.4]
# Requires: .venv with pyinstaller + project deps, Inno Setup 6.
param([string]$Version = "")
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not $Version) {
    $Version = (Select-String -Path pyproject.toml `
        -Pattern '^\s*version\s*=\s*"(.+)"').Matches.Groups[1].Value
}
if (-not $Version) { throw "could not determine version" }

$PyI = Join-Path $Root ".venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $PyI)) { $PyI = "pyinstaller" }
& $PyI packaging/blackwerx.spec --noconfirm
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$Iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Iscc) { throw "Inno Setup 6 (ISCC.exe) not found" }
& $Iscc "packaging\blackwerx.iss" "/DMyAppVersion=$Version"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "built dist\blackwerx_${Version}_win64_setup.exe"
