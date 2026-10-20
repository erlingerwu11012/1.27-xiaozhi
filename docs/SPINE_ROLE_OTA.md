# 视觉资源 OTA：Spine 角色与壁纸

## 产品行为

`assets` 是出厂固定资源，包含主页、字体、图标、`room.png` 和默认 Spine
角色。它不会接受在线 OTA 写入。

在线可更新资源各自使用一个独立的**单槽**分区：

| 资源 | 在线分区 | 开机优先级 | 单槽更新失败后的结果 |
| --- | --- | --- | --- |
| Spine 角色 | `spine` | 有效的 `spine` → `assets` 中的默认角色 | 已下载角色可能不可用，自动回退出厂角色 |
| 壁纸 | `wallpaper` | 有效且已选中的 `wallpaper` 项目 → `assets/room.png` | 已下载壁纸可能不可用，自动回退 `room.png` |

因此，角色和壁纸可以分别更新，也可只更新其中一个；两者的下载过程互斥，避免同时擦写 Flash。这里没有 A/B 槽，也不保留上一版在线资源。出厂资源始终保留在 `assets`，是单槽方案的安全回退。

## 16 MB 分区布局

来源：[partitions/v2/16m.csv](../partitions/v2/16m.csv)。

| 分区 | 偏移 | 大小 | 用途 |
| --- | ---: | ---: | --- |
| `factory` | `0x10000` | 5 MiB | 固件 |
| `userdata` | `0x510000` | 128 KiB | 行为日志 |
| `assets` | `0x530000` | 4.8125 MiB | 固定出厂资源、默认 `room.png` 和默认角色 |
| `spine` | `0xA00000` | 4 MiB | 单槽在线 Spine 角色包 |
| `wallpaper` | `0xE00000` | 2 MiB | 单槽在线壁纸包，最多 16 张 |

当前生成的出厂 `assets` 为 3,197,856 字节（约 3.05 MiB），包含默认角色的
`role.json`、`.skel`、`.atlas`、`texture.png`，约剩 1.76 MiB。在线角色包上限为
4 MiB，壁纸包上限为 2 MiB；壁纸包中的全部图片和清单合计不得超过该上限。

## 出厂与旧设备迁移

首次使用此布局必须通过 USB / 产线一次性完整刷写：bootloader、partition table、
应用和 `generated_assets.bin`。旧版分区表不能通过 OTA 重新排列。

在线 `spine` / `wallpaper` 分区在出厂时可保持空白，因为默认角色与默认壁纸都在
`assets`。`update_assets` 指令会被固件忽略，避免固定资源被网络覆盖。

## 壁纸选择逻辑

- `room`、`default`、`bg_idle` 或 `sunny_day`：强制使用出厂
  `assets/room.png`。这些是既有主页使用的默认背景 ID。
- 在线壁纸包有效时，选择与壁纸 ID 相同的背景 ID；选择会写入 NVS。
- 新壁纸包 OTA 成功后，默认显示其 `wallpaper.json.default_id`；若 NVS 中的旧 ID
  同名，则保留该用户选择。
- 包不存在、校验失败、图片不存在或未选中时，都显示 `room.png`。

壁纸包的 `wallpaper.json` 示例：

```json
{
  "format": 1,
  "pack_id": "summer_2026",
  "version": "1.0.0",
  "default_id": "beach",
  "items": [
    {"id": "beach", "file": "beach.png"},
    {"id": "night", "file": "night.jpg"}
  ]
}
```

## 打包

默认角色随 `generated_assets.bin` 自动生成。在线包在服务端打包：

```bash
# Spine（最大 4 MiB）
python scripts/pack_spine.py \
  --source-dir path/to/role \
  --role-id my_role \
  --version 1.0.0 \
  --skin default \
  --spine-runtime-version 4.2 \
  --output my_role.bin

# 壁纸（最大 2 MiB，最多 16 张 png/jpg/jpeg）
python scripts/pack_wallpaper.py \
  --source-dir path/to/wallpapers \
  --pack-id summer_2026 \
  --version 1.0.0 \
  --default-id beach \
  --image beach=beach.png \
  --image night=night.jpg \
  --output summer_2026.bin
```

## OTA 协议与安全约束

下行 `system` 指令分别为 `update_spine` 和 `update_wallpaper`。壁纸任务字段为：

```json
{
  "task_id": "wallpaper-001",
  "pack_id": "summer_2026",
  "version": "1.0.0",
  "size": 123456,
  "sha256": "<64 个小写十六进制字符>",
  "signature": "<ES256 raw r||s 的 Base64>",
  "url": "https://cdn.xiaozhi.me/wallpapers/summer_2026.bin?token=...",
  "min_fw": "0.0.1"
}
```

Spine 任务继续携带 `role_id`，其余字段相同。两类任务均强制 HTTPS、固定官方
host 白名单、无显式端口/重定向、SHA-256、ES256 P-256 签名、最低固件版本和包
内清单校验。壁纸签名 canonical 的第三行固定为 `wallpaper`，避免已签名的角色任务
被重放为壁纸任务。

状态上报分别为 `spine_ota_status`、`wallpaper_ota_status`；成功后服务端应回传：

```json
{"type":"spine_ota_ack","task_id":"...","status":"completed"}
{"type":"wallpaper_ota_ack","task_id":"...","status":"completed"}
```

收到匹配 ACK（或本地 ACK 超时）后设备重启，从而重新挂载刚写入的单槽资源。

## 验证

```bash
python scripts/test_spine_role_ota.py
python scripts/pack_wallpaper.py --help
idf.py build
```
