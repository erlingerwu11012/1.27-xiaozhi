import hashlib,json,shutil,struct,zipfile
from pathlib import Path
from upgrade_preserve import FLASH_SIZE,PROTECTED,partitions,verify_package
stage=Path(__file__).parent;build=Path('build-nvs64');out=Path('releases/nvs64-habit-renewal-20261007');out.mkdir(parents=True,exist_ok=True)
files={'bootloader.bin':build/'bootloader/bootloader.bin','partition-table.bin':build/'partition_table/partition-table.bin','xiaozhi.bin':build/'xiaozhi.bin','generated_assets.bin':build/'generated_assets.bin','upgrade_preserve.py':stage/'upgrade_preserve.py','Upgrade-Preserve.ps1':stage/'Upgrade-Preserve.ps1'}
for name,p in files.items():shutil.copy2(p,out/name)
layout=partitions((out/'partition-table.bin').read_bytes().ljust(0x1000,b'\xff'))
assert layout['nvs']==(0x9000,0x10000) and layout['phy_init']==(0x19000,0x1000) and layout['factory']==(0x20000,0x4f0000)
for name,span in PROTECTED.items():assert layout[name]==span
assert (out/'bootloader.bin').stat().st_size<=0x8000
assert (out/'xiaozhi.bin').stat().st_size<=layout['factory'][1]
assets=(out/'generated_assets.bin').read_bytes();count,checksum,length=struct.unpack_from('<III',assets)
assert len(assets)==length+12 and sum(assets[12:])&0xffff==checksum and len(assets)<=layout['assets'][1]
names=[];data_start=12+count*44
for i in range(count):
 entry=assets[12+i*44:12+(i+1)*44];name=entry[:32].split(b'\0')[0].decode();size,offset=struct.unpack_from('<II',entry,32)
 assert data_start+offset+2+size<=len(assets) and assets[data_start+offset:data_start+offset+2]==b'\x5a\x5a';names.append(name)
assert len(set(names))==count
merged=bytearray(b'\xff'*FLASH_SIZE)
for start,name in [(0,'bootloader.bin'),(0x8000,'partition-table.bin'),(0x20000,'xiaozhi.bin'),(0x530000,'generated_assets.bin')]:
 data=(out/name).read_bytes();merged[start:start+len(data)]=data
reset=out/'new-device-reset';reset.mkdir(exist_ok=True);(reset/'merged-reset-16mb.bin').write_bytes(merged)
app_size=(out/'xiaozhi.bin').stat().st_size
readme=f'''# ESP32-S3 16MB：NVS64KB、习惯同步固件

编译目标是当前工程的 ESP-BOX-3 配置。程序 {app_size:,} 字节，分区 0x4F0000（5,177,344 字节），剩余 {0x4f0000-app_size:,} 字节。资源包 {count} 个文件，结构、长度和校验和均通过检查。

## 旧设备：默认保留数据升级

1. 解压整个 ZIP 到本地文件夹。关闭串口日志窗口，确认设备 COM 端口；不要用普通“合并镜像全量烧录”覆盖旧机。
2. 本机已安装 ESP-IDF Python（含 esptool、pyserial）。在解压目录打开 PowerShell，运行（把 COM9 换成实际端口）：

```powershell
powershell -ExecutionPolicy Bypass -File .\\Upgrade-Preserve.ps1 -Port COM9
```

其他 Python 环境可以显式指定：

```powershell
.\\Upgrade-Preserve.ps1 -Port COM9 -PythonPath '你的Python完整路径'
```

3. 脚本检测 ESP32-S3、16MB Flash、未启用安全启动/Flash加密，检查安装包 SHA256 和旧分区表。先把完整 16MB Flash 读取两次，校验一致后才开始写入。
4. 旧16KB NVS原样保留在0x9000，新增加48KB填充0xFF；旧PHY数据搬到0x19000。按地址分段写入引导、分区表、NVS/PHY、程序和固定资源；用户数据、在线角色、壁纸分区不写。
5. 所有写入段再次校验，并读取全Flash，逐字节核对NVS、PHY、用户数据、角色、壁纸。成功后拔插USB启动。

备份在 `backups/时间/flash-before.bin`，并有SHA256、升级日志和最终核验记录。备份可能含Wi-Fi及设备凭据，请只保留在本机。已经升级为64KB的设备再次运行时会保留完整64KB NVS。

如果写入中断，不要擦除设备；保留原始备份及日志。可在下载模式用同一Python的 esptool 将该设备的 `flash-before.bin` 写回0x0，恢复升级前完整Flash。示例（路径和端口替换为自己的）：

```powershell
& 'E:\\Espressif\\python_env\\idf5.5_py3.11_env\\Scripts\\python.exe' -m esptool --chip esp32s3 --port COM9 write_flash --flash_size 16MB 0x0 'backups\\时间\\flash-before.bin'
```

## 新机／明确清空数据

`new-device-reset/merged-reset-16mb.bin` 是16MB合并镜像，写到0x0。它会清空NVS、用户数据、已下载角色和壁纸，仅供新机或明确要清空数据的设备使用，不能用作默认旧机升级。

## 烧录地址与核验

|内容|地址|说明|
|---|---|---|
|bootloader.bin|0x0|引导|
|partition-table.bin|0x8000|新分区表|
|旧NVS扩容生成文件|0x9000|由升级脚本从设备备份生成，64KB|
|旧PHY搬迁生成文件|0x19000|由升级脚本从设备备份生成|
|xiaozhi.bin|0x20000|新程序|
|generated_assets.bin|0x530000|固定资源|

用户数据0x510000/0x20000、角色0xA00000/0x400000、壁纸0xE00000/0x200000保持不变。`manifest.json`与`SHA256SUMS.txt`提供各文件校验值。

本包已完整编译、通过主机故障注入和迁移算法测试。尚未在设备执行烧录；真实存储迁移、提醒播放及交互续期需用户烧录后验收。
'''
(out/'README.md').write_text(readme,encoding='utf-8')
hashes={p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*') if p.is_file() and p.name not in ('manifest.json','SHA256SUMS.txt')}
metadata={'chip':'esp32s3','flash_size':FLASH_SIZE,'app_size':app_size,'app_capacity':0x4f0000,'app_margin':0x4f0000-app_size,'asset_files':names,'asset_bytes':len(assets),'partitions':layout,'sha256':hashes,'device_flashed':False}
(out/'manifest.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
hashes['manifest.json']=hashlib.sha256((out/'manifest.json').read_bytes()).hexdigest()
(out/'SHA256SUMS.txt').write_text(''.join(h+'  '+name+'\n' for name,h in sorted(hashes.items())),encoding='utf-8')
verify_package(out)
dest=out.with_suffix('.zip')
with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 for p in out.rglob('*'):
    if p.is_file():z.write(p,p.relative_to(out))
result={'zip':str(dest.resolve()),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'app_bytes':app_size,'app_margin':metadata['app_margin'],'asset_count':count,'asset_bytes':len(assets)}
(stage/'firmware-package-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
