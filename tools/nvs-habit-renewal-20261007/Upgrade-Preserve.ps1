param(
    [Parameter(Mandatory=$true)][string]$Port,
    [string]$PythonPath='E:\Espressif\python_env\idf5.5_py3.11_env\Scripts\python.exe',
    [int]$Baud=460800
)
$ErrorActionPreference='Stop'
if (!(Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw 'Specify -PythonPath with the Python interpreter that has esptool and pyserial installed.'
}
& $PythonPath (Join-Path $PSScriptRoot 'upgrade_preserve.py') --port $Port --baud $Baud
if ($LASTEXITCODE -ne 0) { throw 'Upgrade stopped. Preserve the backups and upgrade.log. Do not erase the device.' }
