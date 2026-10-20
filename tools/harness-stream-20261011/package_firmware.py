from pathlib import Path
import json,shutil,hashlib,zipfile
ROOT=Path(__file__).resolve().parents[2];S=Path(__file__).parent
assert (S/'firmware-build02.exit').read_text().strip()=='0'
B=ROOT/'build-experience-repair-20261009';D=S/'delivery/firmware-20261011';D.mkdir(parents=True,exist_ok=True)
config=json.loads((B/'flasher_args.json').read_text());rows=[]
for address,name in config['flash_files'].items():
 src=B/name;dst=D/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
 rows.append({'address':address,'file':name,'size':dst.stat().st_size,'sha256':hashlib.sha256(dst.read_bytes()).hexdigest()})
(D/'SHA256.json').write_text(json.dumps(rows,indent=2))
(D/'flash.ps1').write_text('''param([string]$Port = "COM9")
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$manifest = Get-Content -LiteralPath "SHA256.json" -Raw | ConvertFrom-Json
foreach ($item in $manifest) {
  if ((Get-FileHash -LiteralPath $item.file -Algorithm SHA256).Hash.ToLower() -ne $item.sha256) { throw "Checksum mismatch: $($item.file)" }
}
$python = "E:/Espressif/python_env/idf5.5_py3.11_env/Scripts/python.exe"
& $python -m esptool --chip esp32s3 --port $Port --baud 460800 write_flash --flash_mode dio --flash_size 16MB --flash_freq 80m 0x0 bootloader/bootloader.bin 0x8000 partition_table/partition-table.bin 0x20000 xiaozhi.bin 0x530000 generated_assets.bin
if ($LASTEXITCODE -ne 0) { throw "Flash failed" }
''',encoding='utf8')
(D/'README.md').write_text('''# ESP32-S3 16MB 固件

本包修复 WebSocket hello 就绪标志和视觉凭据绑定时序，保持当前分区及用户数据布局。保留工作区已有显示和设备工具改动。

关闭占用串口的软件，解压后在 ESP-IDF PowerShell 中执行：

```powershell
./flash.ps1 -Port COM9
```

脚本先核对 SHA256，随后按清单地址写入；不执行 erase_flash，不写 NVS 或用户数据分区。若设备仍使用更早的分区布局，请先完成该布局对应的迁移，不能用本包代替迁移工具。

本包已编译并通过主机协议测试，尚未烧录，摄像头和实际音频效果仍待实机验证。
''',encoding='utf8')
with zipfile.ZipFile(S/'delivery/firmware-20261011.zip','w',zipfile.ZIP_DEFLATED) as z:
 for p in D.rglob('*'):
  if p.is_file():z.write(p,p.relative_to(D))
print(json.dumps({'package':'delivery/firmware-20261011.zip','files':rows},ensure_ascii=False))
