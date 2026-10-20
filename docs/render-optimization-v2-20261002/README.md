# 第二轮复杂角色与屏幕传输测试固件

## 先烧录，再比较

代码、主机测试和ESP-IDF编译已完成。实际帧率、40 MHz屏幕稳定性、连续语音/摄像头和峰值内存仍需要真机确认。

- 固件：spine_render_v2_20261002.app.bin；大小 **4,864,880字节**；5 MiB应用分区剩余 **378,000字节**。
- SHA256：6e27d0dd8a53d28156a79381c5e9df11b9dd038621fb8899b0dbdef38e0c4d8b。
- **COM10写入地址：0x10000。此文件是固件应用，供串口烧录。**
- 继续使用现有4.30分区表；只写应用分区，保留NVS、当前角色、壁纸、网络与账号。
- ESP-IDF 5.5.4 / ESP-BOX-3 / ESP32-S3 / CPU 240 MHz / 16 MB Flash / Octal PSRAM 80 MHz / ST7796 320×320 RGB565。
- 默认 combined + v2 + 30 MHz + pixel_diff=true；已保存的mode继续保留，首次烧录请确认启动日志。
- spi_mhz表示配置请求值，实际SPI分频由IDF驱动确定；40 MHz仅作实验。
- 原PROJECT_VER=2.0.5保持，4.30是当前工程目录版本。

交付目录包含 flash_COM10.ps1、COM10烧录提示词.md、manifest.json。关闭串口监视器后执行烧录脚本，先核对SHA256再写入；随后打开115200波特率日志。

## 本轮实现

1. **连续传输**：每个刷新矩形只设置一次CASET/RASET窗口，首块RAMWR，后续块使用IDF的lcd_cmd=-1路径排队。仍用两个16行内部DMA块；复制和RGB565换序合并。保留MADCTL方向与窗口偏移。
2. **精确像素比较**：复用两张快照，比较完再覆盖同一槽；快照保留原刷新范围，发送范围可以更小。超出上一张有效范围的像素按变化处理，无哈希判断，无额外整张画面缓存。
3. **FIFO与恢复**：无变化帧排队确认完成但不发DMA；前一帧失败会作废后续依赖差分的帧。排空队列后同步重发最新完整画面。错误后连续传输退回原路径、像素比较及异步提交关闭；DMA结束前保留资源。
4. **网格复用**：按实际索引/UV内容跳过相同数据的重复写入，顶点每帧更新。相同地址中的UV/索引变更、顶点缓冲扩容均更新缓存。同一纹理避免重复字符串映射与绑定。
5. **准备过程**：复用刷新区域记录、两帧历史列表节点和边排序缓存。大网格按屏幕行稳定分桶，小网格保留排序，原边顺序不变。
6. **安全修正**：顶点位置缓存原本malloc分配却用delete[]释放，现统一使用free。
7. **双核**：Core1更新角色；两核心按原策略绘制不同屏幕行；Core0传输。原优先级、栈、音频/摄像头分配和Wi-Fi缓冲数量保留。
8. **内存**：两张快照仍为400 KiB、DMA块仍为20 KiB；新增少量配置、队列元数据及可复用准备缓存，没有新增任务或整张画面缓存。

画质、滤波、透明效果、动作时间推进、附件顺序、尺寸、包格式和服务器接口保持。原来不支持的Spine附件裁剪与Screen混合模式保留原行为；测试中的裁剪指屏幕区域裁剪。

续传协议参考：[ST7796S数据手册](https://files.waveshare.com/wiki/common/ST7796S_Datasheet.pdf)。API成功不能识别所有屏幕信号问题；花屏、颜色错误、新增撕裂需真机观察并回到30 MHz/v1。

## 五种模式和两套实现

| 模式 | 绘制 | 屏幕提交 | Core0绘制 |
|---|---|---|---|
| baseline | 原始算法 | 原同步路径，固定30 MHz | 关闭 |
| render | 选定版本优化 | 原同步路径 | 关闭 |
| pipeline | 选定版本优化 | 快照流水线 | 关闭 |
| dual | 选定版本优化 | 原同步路径 | 开启 |
| combined | 选定版本优化 | 快照流水线 | 开启 |

- v1保留第一轮正常运行的绘制与传输路径，用于与26cfcc19对照；共享新增统计和安全恢复，不能称为旧固件的逐字节副本。
- v2加入本轮准备优化；连续传输和像素比较在pipeline/combined中启用。
- baseline始终保持原算法与30 MHz，即使保存选项为40 MHz。
- pixel_diff=false可单独关闭像素比较；连续传输仍启用，便于衡量比较成本。

### 用户专用MCP调用

通过现有用户专用通道调用；没有产品页面，不自动重启。

~~~json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"self.screen.set_render_mode","arguments":{"mode":"combined"}}}
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"self.screen.set_render_options","arguments":{"profile":"v2","spi_mhz":30,"pixel_diff":true}}}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"self.screen.get_render_status","arguments":{}}}
~~~

选项三个字段必填：profile仅v1/v2，spi_mhz仅30/40，pixel_diff为布尔值，无效参数不写NVS。命名空间render_diag，mode保持原键，选项使用单个options字符串，默认v2:30:1。

保存返回ok与requires_reboot。保存后手动重启，再查询状态。当前profile/lcd_spi_mhz/stream_enabled/pixel_diff_enabled与next_boot_*分别表示当前状态和待重启设置；失败原因、双核、流水线也会返回。资源不足可降级，须检查reason。

切换时更换上述arguments，通常保持mode=combined：

- 旧版：{"profile":"v1","spi_mhz":30,"pixel_diff":false}
- 新版：{"profile":"v2","spi_mhz":30,"pixel_diff":true}
- 新版关闭比较：{"profile":"v2","spi_mhz":30,"pixel_diff":false}
- 提频实验：{"profile":"v2","spi_mhz":40,"pixel_diff":true}

每次保存后重启。

## 日志与真机步骤

保留30秒日志，新增RENDER2：

| 字段 | 含义 |
|---|---|
| profile / spi_mhz | 当前实现与配置频率 |
| stream / pixel_diff及reason | 实际启用功能、降级原因 |
| unchanged | 无变化、没有发DMA的帧 |
| original_pixels / sent_pixels | 每个成功处理帧的原刷新量/发送量，含无变化帧 |
| compare_us | 每个处理请求平均比较耗时，未比较时为0 |
| copy_swap_us | 每次实际传输平均复制换序时间 |
| traversal_us | 场景更新总时间，包含动作与网格 |
| collect_us | 收集可见对象时间，包含边计算 |
| edge_calc_total_us | 每次引擎更新所有对象边计算累计时间 |
| edge_schedule_us | 每次绘制所有附件分桶/排序累计时间 |
| sram_min / psram_min | 开机以来最低空闲内存 |

单位微秒，1000微秒=1毫秒。display_fps只统计DMA完成帧；不变画面可以低于draw_fps，结合unchanged判断。嵌套统计不能重复相加；other_us保留原定义，新增计时用于解释余项。

### 建议顺序

1. 当前001复杂角色，v2/combined/30观察2分钟，再对话1分钟，检查画面、字幕、接缝并保存日志。
2. 切v1/combined/30并重启；同一包、显示比例、状态、摄像头连接，静置120秒、对话60秒。
3. v2/combined/30重复并运行10分钟。比较同状态完整30秒窗口，排除启动、切换窗口。
4. 比较耗时大而发送量未下降时，切pixel_diff=false重测，在相同画质下选择实测较快配置。
5. 单独切40 MHz测提频，检查花屏、颜色、残影、新增撕裂；异常回到30 MHz，必要时v1。
6. 换025、064，同样比较；025再覆盖五种模式，定位剩余瓶颈。
7. 连续20轮对话、20次拍照，测试人脸录入、触摸、字幕和在线下载。录入须得到完成结果，不能只凭上传成功认定完成。

目标：001同频平均整帧时间比第一轮降低≥30%；025每个稳定30秒窗口实际显示≥24 FPS。稳态PSRAM≥2 MiB、内部RAM≥16 KiB、新任务栈余量≥1 KiB，无新增音频丢帧、摄像头错误、看门狗重启、分配失败或画面错误。未达标如实记录瓶颈。

采集日志，只采集、不烧录、不主动重启：

~~~powershell
& 'E:\Espressif\python_env\idf5.5_py3.11_env\Scripts\python.exe' 'E:\github\github_code\all\4.30\tools\capture_home_render_logs.py' --port COM10 --seconds 720 --output 'E:\github\github_code\all\4.30\build\render_v2_logs\001_v2_30.txt'
~~~

## 离线验证与限制

- 分别编译75fbc1ba原渲染器、26cfcc19第一轮渲染器，逐像素比较。
- 40组合成场景×2实现×4优化模式，覆盖缩放、旋转图集、翻转、透明、调色板、特殊纹理、屏幕裁剪、退化网格和文字形状叠加。
- 001/025/064全部动作×6固定时间×2滤波×2实现×3绘制模式，像素一致。
- 生产SpineNode加载/动作/网格/纹理路径，三个角色全部动作×2滤波×6连续时间，v1/v2像素一致。
- 100帧持续绘制与动态分界、删除/替换资源；103帧FIFO/回压，90帧精确差分。
- 生产DMA循环模拟命令、队列、槽位、完成等待失败，覆盖偏移、字节序、奇数宽度、末尾短块及所有权。
- 模式选项、分配/任务失败、暂停/恢复、前驱失败使后续差分失效及同步全屏恢复均通过。
- AddressSanitizer同样测试通过，泄漏检测未启用；不等同于完整泄漏证明。
- 主机模拟不能证明真实SPI信号、设备栈余量、实际帧率或语音摄像头稳定性。
- 原有RTTI返回限定符等编译警告保留，无构建错误。

本目录保存普通/ASAN结果、配置与依赖快照。来源提交、SHA和大小见交付目录manifest.json。

## 本地版本与回滚

- 本轮分支：codex/spine-render-v2-20261002；标签test/4.30-render-v2-20261002。
- 第一轮：26cfcc19，标签test/4.30-render-combined-20261002。
- 原始版本：75fbc1ba，标签baseline/4.30-before-render-optimization-20261002。

快速对照：保存v1/30并重启。
固件回滚：第一轮spine_render_combined_20261002.app.bin写回COM10的0x10000。
源码回滚：没有未保存修改时，切回codex/spine-render-pipeline-dualcore-20261002；保留当前分支，不用reset或删除版本。所有提交仅本地保存，没有推送远端。
