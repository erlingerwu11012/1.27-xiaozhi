# ESP32-S3 绘制、屏幕传输和双核组合测试固件

日期：2026-10-02。本次已完成代码、桌面正确性测试和 ESP-IDF 编译。025 的 24 FPS、064 的 30% 提升以及语音、摄像头、触摸、字幕和在线资源下载，等待真机验收。

## 1. 固件与烧录

- 应用文件：build/render_optimization_release_20261002/spine_render_combined_20261002.app.bin
- **写入地址：0x10000；串口：COM10。** 这是固件应用 BIN。
- 大小：4,850,112 字节（4.625 MiB）；5 MiB 应用分区余量 392,768 字节。
- SHA256：bea0cbe05ab5f522e8acea361cd753629562fa989013b1a26eea10f0e36875cf
- 现有 4.30 分区表和 assets 保持兼容，应用更新保留网络、账号、当前角色和壁纸。
- build/merged-binary.bin 是另一个完整镜像输出，地址 0。此次 COM10 更新使用上面的应用文件和 0x10000 地址。

关闭占用 COM10 的监视器，在 PowerShell 中执行：

```powershell
& 'E:\github\github_code\all\4.30\build\render_optimization_release_20261002\flash_COM10.ps1'
```

同目录 COM10烧录提示词.md 可直接复制给 Cursor。没有操作本次真机烧录。

编译配置：ESP-IDF v5.5.4；ESP-BOX-3 / ESP32-S3；240 MHz；16 MB Flash；Octal PSRAM 80 MHz；320×320 ST7796 RGB565；LCD SPI 30 MHz；FreeRTOS 1000 Hz。工程原有 PROJECT_VER=2.0.5 保留，工作目录仍是 4.30。完整配置及依赖锁文件保存在本目录的 sdkconfig.snapshot、dependencies.lock.snapshot。

## 2. 五种对照模式

| 模式 | 绘制 | LCD 提交 | Core0 绘制 |
|---|---|---|---|
| baseline | 原算法、原深度缓冲 | 同步 | 关闭 |
| render | 优化 | 同步 | 关闭 |
| pipeline | 优化 | 两张快照异步传输 | 关闭 |
| dual | 优化 | 同步 | 开启 |
| combined | 优化 | 两张快照异步传输 | 开启 |

未设置过诊断模式时默认 combined。NVS 独立命名空间 render_diag，键 mode。重启后按保存的模式创建任务；保存操作不会自动重启。实际启用状态以 get_render_status 和日志为准，资源不足时可降级。

通过已有的用户专用 MCP 通道调用，参数示例：

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"self.screen.set_render_mode","arguments":{"mode":"baseline"}}}
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"self.screen.get_render_status","arguments":{}}}
```

set_render_mode 返回 ok、requires_reboot 和 next_boot_mode。保存成功后手动重启，再确认 get_render_status.mode。用户专用工具继续受原有账号权限检查；访客不能调用。未增加服务器接口或普通产品页面。

get_render_status 同时返回 mode、next_boot_mode、optimized_drawing、dual_enabled、pipeline_enabled、三类 reason、fallback_count、core0_share_pct、两个新任务的栈余量、internal_free、psram_free。返回 false 的功能必须结合 reason 判断。

## 3. 实现内容

### 绘制

- 先在主任务准备只读绘制包：贴图地址/格式/尺寸、材质、变换及边信息；工作任务使用各自的裁剪、交点缓存和计时上下文。
- RGB565/RGBA 普通纹理直接读取，调色板、特殊纹理保留原路径；双线性采样沿用原计算结果。
- 普通 Region 使用六条三角形边的专用扫描；复杂网格按扫描行更新活动边，并按原边顺序求交；特殊几何和资源准备失败时回到原算法。
- 优化模式移除未用于二维绘制的深度缓冲，减少约 200 KiB 的分配与清空；baseline 保留它。
- 绘制顺序、透明混合、旋转图集、翻转、裁剪和显示尺寸保持。现有 Spine 材质默认 nearest，普通图片的双线性规则及编译开关保留；没有通过关闭原有滤波取得收益。

### 屏幕传输

- 两张 320×320 RGB565 PSRAM 快照共 409,600 字节（400 KiB），仅复制待刷新区域；原渲染缓冲和内部 DMA 分块缓冲保留。
- 队列最多一帧传输、一帧等待。无空闲快照时等待释放；接受提交不等于完成显示，完成计数只在 DMA 全部结束后增加。
- 第一帧、开机动画和立即显示操作同步完成后才亮背光。停止、休眠、角色切换重启和销毁前等待绘制及在途传输结束。
- LCD 失败后保留资源并降级；下一次提交同步重发完整画面，包括角色暂时不动的情况。
- DMA 或工作线程超时后先等完成/取消确认；没有强制删除仍访问内存的任务。

### 双核

- 原 Core1 主绘制任务保持优先级 1、12 KiB 栈；骨骼、动作、顶点和界面只在主任务更新一次，回调也只执行一次。
- 新 Core0 绘制任务 home_raster0：优先级 1、6 KiB 栈。新 Core0 传输任务 home_lcd0：优先级 1、4 KiB 栈。原音频和摄像头任务分配保留。
- Core0 初始画上方约 1/3 行，Core1 画其余行；按各核心移动平均耗时每 16 个双核帧最多调整一次，差异超过 10% 才调整，Core0 份额限 25%～50%。
- 刷新面积小于 8,192 像素或高度小于 16 行时单核绘制。各分区遵循相同附件顺序、屏幕行互不重叠，合并完成后才提交和修改绘制数据。
- 主任务遇到超过周期的慢帧会阻塞至少一个 tick，给空闲任务运行时间；五种模式采用同样规则，避免异步提交后出现追赶帧的忙循环。
- 缓冲、队列或任务创建失败时降级并记录原因；创建新任务前检查内部 RAM 的预留。

## 4. 日志怎么读

每约 30 秒输出一次。时间字段单位为微秒；1000 微秒 = 1 毫秒。

| 日志/字段 | 含义 |
|---|---|
| HOMEPERF display_fps、completed | DMA 已完成的显示帧率和窗口帧数；验收用这个 FPS |
| HOMEPERF draw_fps | 实际调用绘制的帧率；不能替代显示帧率 |
| HOMEPERF accepted | 已接受提交的帧数；异步时可与 completed 差一两帧 |
| HOMEPERF sram、psram | 当前内部 RAM、PSRAM 空闲字节数 |
| SPINEPERF anim_us / mesh_update_us | 动作计算 / 网格顶点更新平均耗时 |
| SPINEPERF draw_us | 实际经过的绘制平均时间，双核重叠计算一次 |
| SPINEPERF alpha_est_us | 透明混合抽样估算，包含在绘制内；不能再相加 |
| LCDPERF snapshot_copy_us / snapshot_wait_us | 复制快照 / 等待空闲槽或队列的平均耗时 |
| LCDPERF accept_us | 提交调用耗时；同步模式包括等传输，异步模式通常只包括复制、排队及背压 |
| LCDPERF transfer_us | 从实际传输开始到全部 DMA 完成的平均时间 |
| LCDPERF wait_per_frame_us / queue_per_frame_us | DMA 等待 / 驱动提交耗时；驱动提交可能包含之前 DMA 的串行等待 |
| LCDPERF queue_blocks / failures / rejected / timeouts | 背压次数 / 传输失败 / 提交失败 / 等待超时 |
| DUALPERF core0_work_us / core1_work_us | 两核心各自工作的经过时间；可能包含被高优先级任务抢占 |
| DUALPERF draw_wall_us / join_wait_us | 整体绘制经过时间 / 主任务等待另一核心的时间 |
| DUALPERF polygon_work_us | 两核心多边形工作时间之和，与实际经过时间不同 |
| DUALPERF core0_share_pct / worker_timeouts / fallbacks | 分区比例 / 工作线程超时次数 / 本次启动累计降级次数 |
| DUALPERF raster_stack_free / LCDPERF lcd_stack_free | 新任务最小栈余量（ESP-IDF 单位为字节） |
| FRAMEPERF frame_work_us | 引擎更新开始到提交接口返回；同步含传输等待，异步含接受提交，不能当作异步端到端显示延迟 |
| FRAMEPERF display_period_us | 窗口经过时间 ÷ DMA 完成帧数，即平均完成帧间隔；无完成帧时为 0 |

两核心累计工作、绘制实际时间、透明混合估算、LCD 子项之间有包含或重叠关系，不能全部直接相加。LCD 统计在帧边界同步汇总，绘制统计在工作任务完成后合并。

## 5. 已完成验证与实际限制

ESP-IDF build 和 merge-bin 成功，应用大小检查通过；生成的分区表与 baseline 相同。主机测试开启 AddressSanitizer，未检测到本次测试范围内的越界或释放后访问。测试报告见 host-test-results.txt，其中告警来自主动注入的故障测试。未做泄漏检测。

- 与 75fbc1ba 中原始 renderer.cpp 另编译的参考实现逐像素比较。
- 40 组场景 × 4 种模式：缩放、旋转、旋转 UV、翻转、掩码、调色板、特殊纹理、半透明叠加、混合方式、网格、退化几何、裁剪和模拟字幕的位图叠加；缓存边界和回调检查通过。
- 100 帧持续绘制：刷新历史、附件移除、资源替换、分区自适应上下限检查通过。
- 传输测试：103 帧 FIFO、两张快照背压、在途画面未覆盖、同步完成、区域边界、失败后整帧恢复、暂停/恢复/销毁等待检查通过。
- 任务创建失败、快照分配失败、内部 RAM 不足、绘制包分配失败和 Core0 超时取消后重画检查通过。
- 真实 hero_025_bg_512_idle、hero_064_s01h_bg_512_idle：每个 6 个固定动作时间点 × 两种滤波设置 × 三种绘制模式，并对照保存的原版参考，逐像素相同。

主机用线程模拟 FreeRTOS 和 LCD 接收端；真实角色在固定 320×320 测试画布中比较。结果证明这些输入下的算法和所有权行为，不能证明真实 LCD 时序、ESP32 调度、设备实际布局/字体或 24 FPS。语音、摄像头、触摸和在线角色切换要在设备实测。

重新运行桌面检查：

```powershell
& 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -X utf8 tools/run_home_render_host_tests.py --sanitize --role 'C:\Users\Administrator\.codex\visualizations\2026\09\28\01a0e758-5351-7181-9956-ebf67ef22628\hero_025_bg_512_idle' --role 'C:\Users\Administrator\.codex\visualizations\2026\09\28\01a0e758-5351-7181-9956-ebf67ef22628\hero_064_s01h_bg_512_idle'
```

需要本机 C++ 编译器及 Pillow；此次临时 LLVM-MinGW 位于 build/host_mingw，未改系统设置。删掉 build 后需重新准备该测试编译器。生产 ESP-IDF 编译不依赖它。

## 6. 真机测试步骤

1. 烧录应用，确认 [RENDERMODE] 和 get_render_status。先用已上传的 hero_025_bg_512_idle，保持相同显示比例、壁纸、亮度、滤波、联网和语音/摄像头设置。
2. 按 baseline → render → pipeline → dual → combined 依次保存模式、手动重启。等启动和联网完成，剔除包含开机过程的统计窗口。
3. 每种模式静置 120 秒、对话 60 秒；combined 继续运行至少 10 分钟。记录所有完整 30 秒窗口。
4. 025 验收：combined 每个正式窗口 display_fps ≥ 24，常规 SPINEPERF draw_us ≤ 35000。出现降级、超时或异常窗口时先查明原因。
5. 将同一设备换为 hero_064_s01h_bg_512_idle，至少重复 baseline 和 combined，保持相同状态和显示比例。用多个完整窗口的总时间 / 总 completed 比较平均完成帧间隔；降低比例 = 1 - combined间隔 / baseline间隔，目标 ≥ 30%。同时报告 frame_work_us 的变化，但异步模式的这个字段不包含之后的完整显示等待。
6. combined 连续 20 轮对话，其间 20 次拍照，并观察字幕、触摸、休眠/恢复以及在线角色下载和重启；无新增音频丢帧、明显断音、摄像头错误、看门狗重启或分配失败。
7. 稳态 PSRAM ≥ 2,097,152 字节、内部 RAM ≥ 16,384 字节；两个新任务最低栈余量 ≥ 1,024 字节。
8. 观察人物边缘和分区接缝：无撕裂、残影、错层或字幕异常。若未达标，按 draw_wall、core0/core1、join_wait、snapshot_wait、transfer 和 TaskDiag 的同一窗口继续定位。

本轮必须采集同一测试固件的 baseline；之前混有启动/对话或截断的日志只用于参考。

收集日志：关闭其他 COM10 监视器，在工程目录运行以下命令。脚本不烧录或自动复位。

```powershell
& 'E:\Espressif\python_env\idf5.5_py3.11_env\Scripts\python.exe' tools/capture_home_render_logs.py --port COM10 --seconds 240 --output build/hero025-baseline.txt
```

combined 长测可用 --seconds 900，并将输出名改为 hero025-combined.txt。完整保留 HOMEPERF、SPINEPERF、LCDPERF、DUALPERF、FRAMEPERF、TaskDiag、告警及状态切换行。

## 7. 本地保存和回滚

优化分支：codex/spine-render-pipeline-dualcore-20261002。本地发布标签：test/4.30-render-combined-20261002；实际提交号记录在发布目录 manifest.json。没有推送远端。

快速对照：设置 baseline 并手动重启，使用原绘制算法及同步传输。它仍包含本次诊断和统一的慢帧让出规则，公平性能比较应重新实测。

完整源码回滚点：75fbc1ba，标签 baseline/4.30-before-render-optimization-20261002。先保存当前工作，再检出该标签；根目录 sdkconfig 和 dependencies.lock 被忽略，需从 docs/baselines/spine-render-before-optimization-20261002 对应快照恢复，再 reconfigure / build。新分支返回时使用本目录的两份优化配置快照重新配置构建。

```powershell
git switch --detach baseline/4.30-before-render-optimization-20261002
Copy-Item -LiteralPath docs/baselines/spine-render-before-optimization-20261002/sdkconfig.snapshot -Destination sdkconfig
Copy-Item -LiteralPath docs/baselines/spine-render-before-optimization-20261002/dependencies.lock.snapshot -Destination dependencies.lock
# 在 ESP-IDF 5.5.4 环境中执行 idf.py reconfigure，然后 idf.py build
```

本次改动、测试代码和配置快照纳入本地 Git；build、生成 BIN 和临时测试编译器不纳入 Git。角色包格式、服务器上传接口和已有资源包保持兼容。
