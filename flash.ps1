[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$Port,
    [int]$Baud = 460800
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$package = Join-Path $root 'releases\standby-clock-level8-20261007'
$flash = Join-Path $package 'flash-app.ps1'
if (-not (Test-Path -LiteralPath $flash)) { throw "找不到固件烧录脚本: $flash" }

function Test-Esptool([string]$Python) {
    if (-not $Python) { return $false }
    & $Python -m esptool version 1>$null 2>$null
    return $LASTEXITCODE -eq 0
}

$candidates = New-Object System.Collections.Generic.List[string]
if ($env:IDF_PYTHON_ENV_PATH) {
    $candidates.Add((Join-Path $env:IDF_PYTHON_ENV_PATH 'Scripts\python.exe'))
}
foreach ($base in @('E:\Espressif\python_env', 'C:\Espressif\python_env', "$env:USERPROFILE\.espressif\python_env")) {
    if (Test-Path -LiteralPath $base) {
        Get-ChildItem -LiteralPath $base -Directory -ErrorAction SilentlyContinue | ForEach-Object {
            $candidates.Add((Join-Path $_.FullName 'Scripts\python.exe'))
        }
    }
}
foreach ($cmd in @('python', 'py')) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found) { $candidates.Add($found.Source) }
}

$python = $null
foreach ($item in $candidates) {
    if (Test-Esptool $item) { $python = $item; break }
}
if (-not $python) {
    throw "找不到带 esptool 的 Python。请先安装 ESP-IDF 5.5，或执行: python -m pip install esptool"
}
Write-Host "Using Python: $python"
& $flash -Port $Port -Baud $Baud -Python $python
if ($LASTEXITCODE -ne 0) { throw "烧录失败，退出码 $LASTEXITCODE" }
