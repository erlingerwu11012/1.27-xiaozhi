# 摄像头照片统一使用 PSRAM（2026-10-02）

## 修改范围

- USB 摄像头接收的四块 88 KiB 缓冲原本已显式使用 PSRAM。
- 原先普通 STL JPEG 容器使用系统 malloc，当前配置优先 PSRAM，但可能回退内部 RAM。现已改为 `CameraJpegBuffer`，只允许 `SPIRAM | 8BIT`。
- 共享照片、拍照识物副本、识别人脸副本、人脸录入单帧及引导录入候选组使用同一分配策略。
- JPEG 旋转所用 RGB888、编码输出缓冲直接使用 PSRAM。
- 项目内链接包装软件 JPEG 库四个分配入口，编码/解码工作缓冲只用 PSRAM，不修改自动管理的依赖。原库的 `jpeg_calloc_align_inner` 会先申请内部 RAM；640×480、420 编码的 20,480 字节工作缓冲走此入口。
- 含照片的 multipart 上传请求体使用 PSRAM 字符串，并直接移交 HTTP 客户端所有权，发送时不复制为普通堆字符串。HTTP 长度、字节内容和认证方式保持原协议。
- 分配失败时释放旋转缓冲和摄像头帧锁；识别及录入任务报告失败并走已有摄像头释放/会话清理流程。PSRAM 不足时不占用内部 RAM 兜底。

硬件传输描述符、网络控制结构、TLS/Wi-Fi 底层缓冲及任务控制块仍按照驱动要求分配。此修改针对照片及软件 JPEG 的图像工作内存，不表示整个拍照功能完全不使用内部 RAM。

## 烧录后的确认

启动日志应有：

```text
[PHOTO_PSRAM] policy=strict jpeg=psram rgb=psram codec_workspace=psram upload=psram internal_fallback=0
```

第一次触发对应 JPEG 工作缓冲应有：

```text
[PHOTO_PSRAM] JPEG workspace bytes=20480 caps=0x404 task=...
```

`0x404` 为 `MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT`。若分配失败，新日志会标明图像 PSRAM 不足并显示字节数，不再按此图像路径尝试 `0x804` 的内部 RAM。

普通拍照、人脸识别、人脸录入分别操作后采集 `[PHOTO_PSRAM]`、`[TASKHEAP]`、`[ALLOCFAIL]` 和摄像头/录入结果日志。对照拍照前后的内部 RAM 和 PSRAM 余量，并检查失败后的下一次操作能否正常开始。

这次修改的主要收益是减少图像路径对内部 RAM 的占用与失败尝试。PSRAM 访问速度与缓存竞争可能影响拍照耗时，实际帧率和峰值内存需要烧录实测。

## 固件及回滚

本次在现有本地渲染优化分支上修改。修改前提交为 `433cd71b`，回滚此轮可本地恢复该提交并重新编译。首轮渲染优化前原始回滚点仍为 `75fbc1ba`。

使用本次交付的应用固件，写入应用分区 `0x10000`。应用分区大小 `0x500000`（5 MiB）；无需擦除 NVS 或覆盖在线角色、壁纸分区。完整烧录脚本应遵循工程的分区与资源参数，不能直接使用历史 `merged-binary.bin` 代替本次固件。

交付目录中的 `manifest.json` 记录本次固件大小、SHA256、源码提交及编译结果。
