# Harness 修复候选，2026-10-17

状态：已于北京时间 2026-10-17 20:16:23 同批发布到正式服务。API 为 PM2 16，Python 为 PM2 17，均 online。正式前端为 www.realecho.cn，正式 API 为 api.realecho.cn。没有向生产数据库写入测试数据，也没有修改固件。

首次验收误用 www 域名访问内部 API，得到前端页面，已自动回滚；随后核实 api 域名的既有代理规则并重新发布成功。未修改 nginx 或 DNS。最终验收见 deployment-final.json，首次回滚记录保留在服务器。

## 已确认的问题

- 提醒：实际运行版的声明要求 `add_reminder`，但它只声明来自可选的 server MCP。会话中没有该工具，即使设备已经支持 `note_add`，既有定时提醒适配层也无法被发现和调用。
- 记忆：运行中的 Python 使用 `/person-memory/internal/add`、按 ID 读回、分页和批量遗忘契约，而当前运行 API 及其工作区源码缺少对应能力。Python 与 API 发布版本不配套。不是通过放宽成功判断解决。
- 延迟：现网实际发布版已有流式输出。操作开始播报前仍可能经过多次完整规划；简单设置成功后还会额外调用模型改写回执。
- 运行来源：Python 由 `/root/prjs/releases/tts-spine-sync-20261013/serve.py` 启动，优先加载其 `runtime`。只修改普通工作区不会修复实际运行版。

## 修改

- `active/core/providers/tools/device_reminder_adapter.py`：设备在线且具有真实 `note_add` 时提供定时提醒入口。既有 server MCP 工具不覆盖；基础工具存在歧义时不适配。
- `active/core/providers/tools/unified_tool_manager.py`、`active/core/utils/tool_harness/registry.py`：把上述入口加入真实目录与受审核来源；执行仍经既有时间、收件人、设备回执检查。目标 Schema 进入绑定快照，变更时重新校验。
- `active/core/utils/tool_harness/reply_composer.py`：单次音量/亮度成功回执直接生成实际数值确认，省去一次结果改写模型请求。失败、未知、混合目标和普通查询保留原处理。
- `active/core/utils/tool_harness/runtime.py`：提示相对调节直接规划设置步骤；程序本来就会读取实时状态并计算，避免模型先查状态再重新规划。没有取消完整计划校验。
- `api/src/main/java/xiaozhi/modules/personmemory/`：在当前 API 源码上合并匹配运行版 Python 的记忆保存、精确读回、范围查询、批量遗忘及显式事实处理。保留当前设备恢复协议和鉴权实现。

## 验证

最终结果见 `verification.json`：Python 69 项通过；Java/API/独立数据库 53 项通过，失败、错误、跳过均为 0。

新增用例覆盖本次“呃，你提醒我一下，两分钟后喝水”经完整 Harness、身份未确认不写、设备失败不说成功、设备目录变更、简单设置不额外调用模型、HTTP 新增接口、按 ID 读回、保存幂等、错误事实和过期身份拒绝。

原跨日测试原先把写入和查询放在同一个 turn。现在增加同轮原文不可作为历史记忆的断言，再使用新 turn 验证跨日检索。数据库测试只使用新建的 `bailian_memory_test_harnessrepair20261017`，未连接生产数据进行测试。

候选 API 已打包。56 个设备模块 Java 源文件与当前鉴权工作区一致。路径及 SHA-256 见 `manifest.json`。本次没有真实模型计费请求、没有让实机创建测试提醒；不能把离线通过当作实机已恢复。

## 交付和下一步

Python 候选目录：`/root/prjs/tmp/harness-repair-20261017/python`。

API 候选目录：`/root/prjs/tmp/harness-repair-20261017/manager-api`。

`review-diffs/` 为本次 Python 实际差异。`api/baseline/` 为本次合并前的 Java 对照，API 源码和测试在 `api/src/`。

Python 与匹配的 API 已作为同一批次发布，保留当前 auth 协议、密钥、设备绑定及生产数据。已验收正式 HTTPS 200、API 新增接口存在且拒绝无效请求、WSS 拒绝无效 token、服务端口正常。尚需真实设备验证创建提醒、记忆保存后查询及回复首音频时间。

只读记忆核查：当前设备“爸爸”身份使用 Memory_mem_local_short；显式事实和更正记录为 0，有效短摘要为 0；对话档案有 50 条用户原话和 61 条助手回复。“我最爱喝咖啡”在对话历史中，但当时的显式保存失败。没有补写或重放旧保存操作。摘要见 memory-summary.json。

音频断续和 Spine 低帧率没有在本候选中处理，也没有承诺此服务端修复能消除它们。
