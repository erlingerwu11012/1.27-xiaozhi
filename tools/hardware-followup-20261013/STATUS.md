# 本轮实施状态（已完成上线）

最新状态覆盖下面的实施期间记录：

- 已完成定向修复、自动验收与正式发布，完整范围及限制见delivery/REPORT.md。
- 正式目录/root/prjs/releases/harness-followup-20261013；新PM2 id11（API）和id12（服务端）在线。旧id9、id10已停止并保留回滚。
- 最终账本800/800条测试、652/700次主模型、10/12次真实TTS、0次视觉。测试条数已用完，不再自动新增测试。不得把本地旧budget.sqlite3上传覆盖远端账本。
- 181轮业务证据通过，按用户授权复用未受影响版本；18个回复位置补验，另6轮主体、人脸及闹钟专项通过。没有宣称全部在同一最终版本重跑。
- 工具P95 5.18→5.11秒；匹配4条真实首音频P50 2.29→2.19秒；首文本1.67→1.73秒，略慢。
- build02固件完整编译通过，delivery/firmware-20261013.zip已交付未烧录。COM9未恢复；CPU/FPS、未来告知和声纹策略未修改。
- 历史资料只读差异已生成，未批量恢复。492条旧材料召回资格由允许变禁用，材料本体仍在，不全部直接判误删；01:23全量遗忘标记仍保留。
- 正式HTTPS、负向WebSocket鉴权、模型／人格／计费／根配置与同一生产账本已核对，未进行30分钟观察。正向业务只在隔离API／软件设备验证。
- 交付见delivery/REPORT.md、delivery/evidence/COMPLETE_DIALOGUES.md及delivery/delivery-evidence.tgz。硬件效果仍待用户实测。

以下为旧实施记录，计数和待办已经过期，保留用于审计：

用户授权：2026-10-13，修复18类问题，定向自动验收通过后部署正式域名。

- 基线：harness-stream-20261012；本目录work从上轮work复制，baseline/source-manifest.json保留初始哈希。
- 独立预算：case800/model600/TTS12/vision0；开发模型180，最终保留420；TTS4/6/2。旧账本不使用。
- 正式进程尚未修改。COM9保持停止，不烧录。CPU/FPS和未来告知机制不修改。
- 候选已实现：Decision语义授权、任务参数接续、记忆ID/版本读回、限定集合遗忘、分页、命令过滤、自然回复；播报来源保护；TTS上游独立任务和下游请求隔离；相机hello代次及USB有限恢复；人脸终态及未知启动核对；OTA忙原因及重复回执去重；历史并发幂等。
- 隔离API候选05在18006，独立数据库bailian_memory_test_followup20261013、Redis16382。21项记忆/授权API、9项OTA、20项生命周期及7项真实分块网络回归已通过。固件完整编译成功；hello10、USB7、人脸5、TTS24及OTA锁9项主机模拟已通过，均未烧录。
- 真实模型开发阶段发现的问题及失败证据保留；最终批次01/02/03分别因相对调节虚报、待办查询未执行、取消提醒未执行而停止。修复尚在复验，不代表满足上线门槛。
- 已完成20条速度基线、4次真实TTS。最近账本读数case433/model223/TTS4/vision0；以服务器budget.sqlite3为唯一实时依据，开发模型已用176/180，后续付费只用于最终验收及受影响重跑。
- 待完成：最终181轮组合验收及完整体验审阅、补充历史失败和人脸/闹钟模型场景、候选测速、发布空间/备份恢复/候选协议验收、正式切换与即时检查。正式进程未切换。
- 服务器SSH可用；生产PM2 manager-api id9、xiaozhi-server id10。正式目录/root/prjs/releases/harness-stream-20261012。
- 上轮隔离环境/root/prjs/tmp/harness-stream-20261011，源码manager-api及private-test-env.json。本轮应建立独立目录及数据库/缓存，禁止写生产用户数据。
- 磁盘最近可用约283MiB。已清理已验证停止且可恢复的测试构建副本，正式回滚包与业务数据保留。候选03/04 JAR已下载本地并核对SHA后仅删除远端副本。此前复制基线时误带937MB模型导致磁盘紧张并令网关计费事务阻塞；仅删除与正式原件哈希一致的本轮模型副本后恢复，失败调用计入账本。具体清单见远端rebuildable-cleanup-*.json。
- 历史上报根因：manager-api-out.log在01:53~01:56重复CannotAcquireLockException/MySQLTransactionRollbackException deadlock，位置AccountIdentityStateService.lock的INSERT IGNORE接FOR UPDATE。候选改为获取排他锁的ON DUPLICATE KEY UPDATE；仍需并发回归证明。
- 相机启动正常作为基线；相关固件修复已编译未烧录。设备实际拍照、音频、OTA效果仍由用户后续实机验证。

修改后必须补测试并维护预算；不要把本状态文件当验收报告。
