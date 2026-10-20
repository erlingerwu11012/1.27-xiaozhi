param([string]$Port = "COM9")
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$manifest = Get-Content -LiteralPath "SHA256.json" -Raw | ConvertFrom-Json
foreach ($item in $manifest) {
  if ((Get-FileHash -LiteralPath $item.file -Algorithm SHA256).Hash.ToLower() -ne $item.sha256) { throw "Checksum mismatch: $($item.file)" }
}
$python = "E:/Espressif/python_env/idf5.5_py3.11_env/Scripts/python.exe"
& $python -m esptool --chip esp32s3 --port $Port --baud 460800 write_flash --flash_mode dio --flash_size 16MB --flash_freq 80m 0x0 bootloader/bootloader.bin 0x8000 partition_table/partition-table.bin 0x20000 xiaozhi.bin 0x530000 generated_assets.bin
if ($LASTEXITCODE -ne 0) { throw "Flash failed" }
