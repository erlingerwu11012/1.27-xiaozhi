# Realecho ESP-BOX-3 固件

这是面向 ESP-BOX-3（ESP32-S3）的 ESP-IDF 固件工程。当前主构建保留语音对话、屏幕角色动画、触摸交互、摄像头单次拍照、角色 OTA 更新和 Realecho 服务连接。

## 构建

需要 ESP-IDF 5.5.4 和对应的 Python 环境：

```powershell
idf.py set-target esp32s3
idf.py build
```

默认分区表为 `partitions/v2/16m.csv`，出厂资源会由构建过程生成并写入 assets 分区。烧录前请使用你自己的设备端口执行 `idf.py flash monitor`。

默认人物已替换为用户最新 `nvhai.zip` 中的蓝发女孩 `nvhai_builtin`（`main/assets/cubicat_spine_default_42/`），默认壁纸为 320×320 日光房间图（`main/assets/cubicat_home/room.png`）。新角色导出已自带 1.3 倍骨骼缩放，固件额外显示倍率为 1.0，避免重复放大；根据新骨骼坐标补偿衣角与桌沿交点，并保留双线性过滤。构建时会将这些源文件打入 `generated_assets.bin`；要更新设备上的内置资源，需要写入 `assets` 分区，仅更新应用不会替换内置资源。有效的在线 OTA 人物、壁纸仍优先于内置默认资源。

## 服务与密钥

固件继续使用当前 Realecho 服务地址和角色 OTA 公钥，以保持现有设备功能。私钥只允许留在服务端；本仓库通过 `.gitignore` 排除本地开发私钥。公钥校验方式见 [`main/certs/README.md`](main/certs/README.md)。

## 资源与许可证

根目录采用 MIT 许可证。项目方已确认 Spine 软件、角色、背景、开机动画和录音具有正版授权或公开分享许可。第三方运行库仍保留各自目录中的许可证文件；发布衍生版本时请同时遵守这些许可证。

## 发布构建

```powershell
python scripts/release.py esp-box-3 --name esp-box-3
```

发布脚本会使用当前固定的 ESP32-S3 / ESP-BOX-3 配置，并自动生成出厂资源包。
