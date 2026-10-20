# 分组：billing（充值、账单、官方语音）

## (a) 页面与接口对照

| 原页面 / 组件 | 路由 | 改版后的位置 / 变化 | 后端接口（METHOD path） | 状态 |
|---|---|---|---|---|
| `views/BillingPackages.vue` | `/billing/packages` | 去掉 HeaderBar、渐变余额卡、套餐阴影。顶部左侧是余额面板（正常 / 可能不是最新 / 暂不可用，不显示余额来源名称），右侧是套餐单选卡加支付按钮。下面是“用量趋势 + 账单明细”面板（单色柱状图、7/30 天切换、按日倒序的表格），最后是调用明细。mock 构建里把支付宝表单换成页面内的“确认付款（演示）”弹窗，提供模拟成功 / 模拟失败 / 取消三个选项，选完跳到 `/billing/result?out_trade_no=…`。real 构建的 payForm 流程没有改动。 | GET `/pay/billing/summary?days=`；GET `/pay/packages`；POST `/pay/order/create` `{packageId, channel:'alipay'}` | 完成 |
| `components/HardwareCallBills.vue` | （嵌在套餐页） | 改成 `.xn-panel`，加空状态和失败状态（可重试），状态用 `.xn-tag` 显示，展开行改成键值网格。原来写死的中文文案移到 i18n；“缓存命中 token”改为“复用的输入 token”。 | GET `/pay/billing/calls?page=&limit=20` | 完成 |
| `views/BillingResult.vue` | `/billing/result` | 页面骨架加返回链接。状态区包含图标、状态文字、说明和“演示结果”标记，下方是订单键值表。加了无订单号、查询失败两种状态。到账后发 `xn:quota-changed` 让外壳刷新余额。订单号参数除 `out_trade_no` / `outTradeNo` 外也接受 `orderNo`。保留 3 秒轮询。 | GET `/pay/order/query/{orderNo}` | 完成 |
| `views/BillingOrders.vue` | `/billing/orders` | 页头的主按钮是“立即充值”。余额条和 `balanceCacheHint` 提示放在页头下方。“充值订单”表格增加到账点数列、“查看”（跳到结果页）和每页条数切换。“回响现实官方服务费用”表格的文案移到 i18n，并补了空状态和失败状态。 | GET `/pay/orders?page=&limit=`；GET `/pay/quota/me`；GET `/pay/memory-bills?page=&limit=10` | 完成 |
| `components/OfficialTtsStudioShell.vue` | — | 去掉 HeaderBar、hero 大标题、旋转彩虹描边（`ot-composer__ring`）和渐变。现在是 page-header（标题取导航名，`hero` 插槽作为说明文字）、分段 tab（语音合成 / 音色设计 / 音色复刻）、警告 el-alert 和白色面板 composer。props、插槽名不变，另外新增 `actions` 插槽。 | — | 完成 |
| `views/OfficialTtsVoices.vue` | `/official-tts/voices?mode=design\|clone` | 设计模式：textarea 加“试听文本”按钮和主按钮“开始设计”。复刻模式：上传 / 录制两张卡、文件条、录音条、主按钮“开始复刻”。资产列表改为 el-table（试听、状态标签、错误提示、去合成、重命名、删除并二次确认），有加载、空和失败三种状态。复刻模式里原来不起作用的“文本预览”入口已去掉（复刻上传并不提交 previewText）。 | GET `/official-tts/capabilities`；GET `/official-tts/voices`；POST `/official-tts/voices`（设计）；POST `/official-tts/assets`（复刻，FormData file/kind/name）；PUT `/official-tts/voices/{id}`；DELETE `/official-tts/voices/{id}`；GET `/official-tts/voices/{id}/preview`（blob） | 完成 |
| `views/OfficialTtsDubbing.vue` | `/official-tts/dubbing` | 编辑器下方的工具条包含语气标签、音色、语言/方言、音量、语速、导出格式、字数和主按钮“生成配音”。“灵感”卡片去掉了色块。“我的配音”改为 el-table（内容与参数、状态标签、内嵌播放器、下载 / 再次编辑 / 删除），有加载、空和失败三种状态。mock 模式下载的文件扩展名如实写成 `.wav`。 | GET `/official-tts/capabilities`；GET `/official-tts/voices`；GET `/official-tts/jobs`；POST `/official-tts/jobs`；DELETE `/official-tts/jobs/{id}`；GET `/official-tts/jobs/{id}/download`（blob） | 完成 |
| `components/OfficialTtsVoiceLibrary.vue` | （配音页弹窗） | 标准 el-dialog。顶部是分段切换（官方 / 我的设计 / 我的复刻），配搜索框和“创建音色”按钮（跳到我的音色）。卡片可单选并能试听，底部是取消和“使用这个音色”。原来的三个筛选下拉（全场景 / 全性别 / 全语言）只有“全部”一个选项，没有作用，已去掉。props（visible / value / officialVoices）和事件（update:visible / input / confirm）不变。 | GET `/official-tts/voices`；GET 和 POST `/official-tts/voices/{id}/preview`（blob） | 完成 |
| `views/OfficialTtsAdmin.vue` | `/admin/official-tts`（adminOnly） | 规则提示、概览统计、价格版本表格（中文标签、状态 tag）。编辑草稿从 `$prompt` 改为表单弹窗（金额必须是大于 0 的数字），发布也改为弹窗（显示版本信息，理由选填）。人工备注表单带必填校验和重置。结算面板改为读取账单、键值表、表单、预览、二次确认。保留全部 `data-testid` 和幂等 operationId 逻辑。“网关 / ack / 灰度 / 令牌”等文案改成管理员能看懂的说法。 | GET `/admin/official-tts/overview`；PUT `/admin/official-tts/prices`；POST `/admin/official-tts/prices/draft-from`；POST `/admin/official-tts/prices/publish`；POST `/admin/official-tts/prices/sync`；GET `/admin/official-tts/jobs/{jobId}/ledger`；POST `/admin/official-tts/notes`；POST `/admin/official-tts/settle` | 完成 |
| `styles/official-tts-studio.scss` | — | 重写，只用 `--xn-*` 变量。没有渐变、发光、旋转动画；`.ot-delete-confirm` 仍由 global.scss 提供。行数从 1928 降到约 230。 | — | 完成 |

Mock：`src/mock/handlers/pay.js`（扩展，8 个路由）、`src/mock/handlers/officialTts.js`（新增，22 个路由）、`src/mock/seed/billing.js`、`src/mock/seed/officialTts.js`。共 30 个接口。如果本机的旧演示数据里缺少这些集合，handler 会自动补齐。

演示规则：
- 套餐固定为“演示套餐 A/B/C”，页面上有“演示套餐”标记。
- 下单只生成本地订单。订单状态流转：pending →（模拟成功）paid → 约 2.5 秒后查询时变为 delivered，演示余额同时增加；pending →（模拟失败）failed；pending 超过 15 分钟 → closed。
- 配音任务：queued 约 2 秒后变为 running，约 7 秒后变为 done。完成时按“演示价格”扣演示点数，并写入一条调用明细。
- 试听和下载用的是浏览器内生成的 WAV 提示音。复刻上传只记录文件名、大小和类型。
- 所有 `/admin/official-tts/*` 先调用 `requireAdmin`。
- `scenario.data === 'empty'` 时，列表类接口返回空。

## (b) 待确认 / 联调问题

1. **余额来源与界面状态的对应**（外壳余额条、套餐页、账单页统一按这套规则；界面上不显示来源名称）：
   - 请求失败、`balance`/`balancePoints` 为 null、`balanceSource` 为 null 或 `'none'`：显示“余额暂不可用”（`billing.balanceUnavailable`）。原套餐页把 `'none'` 显示成“暂无余额记录”。需要确认 `'none'` 是否可能对应“新账号、余额为 0”，如果是，应该显示 0。
   - `balanceSource === 'cache'` 或 `balanceRealtime === false`：照常显示数值，另加“可能不是最新”标签和 `billing.balanceCacheHint` 提示。
   - `'oneapi'` 或 `'hardware_ledger'`（且 `balanceRealtime !== false`）：正常显示，不加标签。
   - `/pay/billing/summary` 是否返回 `balanceRealtime` 待确认。目前只有 mock 返回这个字段，页面以 `balanceSource` 为准。
2. **请求层不回调业务错误**：`pay.*` 中除 `hardwareCalls` 外，以及 `officialTts.*` 的 capabilities、listVoices、createVoice、listJobs、createJob、cancelJob、adminOverview、updatePrice、publishPrice 等，都没有 `.fail()`。返回 code≠0 时，请求层只弹 `showDanger`，页面回调不会执行。为了不让页面一直加载，页面加了 10 秒“无响应即显示失败”的兜底；管理员弹窗按钮的 loading 状态 3 秒后自动复位。建议由 API 模块的负责人给这些方法补上 `.fail()`（属于共享文件，本组没有改）。在此之前，createJob 等提交如果返回业务错误，按钮会在兜底时间后才恢复。
3. 真实环境的 `createOrder` 返回什么、支付宝 `return_url` 带回的参数名（`out_trade_no` 还是其他）需要确认。结果页三种参数名都接受。
4. `/pay/orders` 是否支持按状态筛选：页面没有加筛选，只用 page/limit 分页。
5. `/official-tts/voices/{id}/bind?agentId=` 在前端没有任何调用方。mock 只把音色记到 agent 上（`officialVoiceId`），真实行为待确认。
6. 价格表 `status` / `lifecycleStatus` 的完整取值待确认。页面已映射的取值：draft、published、publish_ack_pending、publish_failed / active、draft、superseded、retired；其余取值原样显示。
7. 复刻音色生成后是否自动带 `hasPreview`：mock 中设计音色为 true，复刻音色为 false。复刻音色可以在音色库里按需生成试听（POST preview）。
8. 配音下载的真实文件格式和 `requestJson.format` 一致。mock 只能生成 WAV，所以 mock 模式下下载的文件名用 `.wav`。
9. API module exposes detail/disable (role & wallpaper packs) and cancelJob (dubbing) but the original pages have no entry for them; not added in the redesign (no new features).（mock 仍保留 `POST /official-tts/jobs/{id}/cancel`。）

## (c) 未完成 / 已知问题

- 官方语音页面脚本里的提示消息（`$message` / `$confirm` 文案、状态名、校验文案）已移到 `xn.tts.*`（zh_CN 和 en）；服务端返回的 `msg` 仍原样显示。
- 管理员备注表单校验失败时，控制台会出现 Element 自带的 `async-validator` warning，属于正常校验行为。
- 外壳余额条只在进入 `/billing/*` 页面或收到 `xn:quota-changed` 事件时刷新。配音完成扣除的演示点数，要到下次进入账单页才会体现。
- 已验证：1440×900 和 960 宽度下无横向滚动；正常、空数据、服务异常三种场景，以及余额可能不是最新、暂不可用两种状态；整个过程没有任何非 localhost 的网络请求。
