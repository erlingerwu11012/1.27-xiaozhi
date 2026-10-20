# 后端联调说明

本改版**没有改动任何接口契约**：`src/apis/module/*.js` 中的 URL、HTTP 方法、请求字段、回调读取方式保持原样（对比源分支可确认 `git diff codex/server-frontend-claude-20261019 -- manager-web/src/apis/module` 为空）。改版期间所有页面只在演示数据下运行过，**没有连接过任何真实后端**，因此下列每一项在联调前都应视为“未验证”。

> 演示数据跑通 = 前端交互完整；不等于真实业务逻辑正确。

## 1. 切换开关

| 变量 | 取值 | 作用 |
|---|---|---|
| `VUE_APP_DATA_MODE` | `mock`（默认，任何非 `real` 的值都按 mock 处理） | `httpRequest.js` 的 `send()` 改走 `src/mock`，不发任何网络请求；显示“演示模式”入口与“演示”标记；不注册 Service Worker |
| | `real` | 恢复 `fly.request`，webpack 在构建期剔除 `src/mock`、演示模式面板、演示媒体替身 |
| `VUE_APP_API_BASE_URL` | 原值（如 `/xiaozhi`） | 不变 |
| `VUE_APP_PROXY_TARGET` | 原值 | 只影响 `npm run serve` 的代理，不变 |

判断写成 `process.env.VUE_APP_DATA_MODE !== 'real'` 的构建期常量，所以**切换后必须重新构建**，不能在运行时切换。已核对 real 构建产物中不包含演示数据与 mock 路由（构建结果见交付说明）。

联调步骤建议：

1. `.env.local` 写 `VUE_APP_DATA_MODE=real` 与原有代理配置，`npm run serve`。
2. 浏览器清掉本站的 `localStorage['xn-mock-db-v1']`、`localStorage['xn-mock-scenario-v1']`（只在 mock 模式写入，real 模式不读，但留着容易混淆）。
3. 按第 4 节逐页核对；“待确认”项优先。

## 2. 请求适配层

- 接入点只有一处：`src/apis/httpRequest.js`。mock 模式下 `mockRequest(url, data, options)` 与 `fly.request` 签名、返回结构相同：成功 `{ status: 200, data: <后端 JSON> }`，网络失败 reject `{ status }`，所以原来的 `success / fail / networkFail` 回调、`code: 401` 跳登录、重试逻辑都没有改。
- mock 登录也走原流程：图形验证码 → SM2 加密 `captcha + password` → `/user/login` → `token`。SM2 密钥对在每次页面加载时于内存中生成，**不写入任何存储**；演示账号接受任意非空密码。真实模式下用的仍是 `/user/pub-config` 返回的 `sm2PublicKey`。
- `npm run check:mock` 静态扫描所有 API 调用，确认每个调用在 mock 层都有对应实现（防止 mock 模式下页面打到未实现的接口）。

## 3. 权限

- 管理员菜单只在 `isSuperAdmin`（来自 `/user/info`，字段与原逻辑相同）为真时显示。
- 路由 `meta.adminOnly`（13 个管理员页面，见 `src/router/index.js`）：普通用户进入时外壳显示“没有访问权限”，不渲染页面组件，也就不会发出该页的接口请求。这是**界面层**拦截，真实权限以后端返回为准，联调时需确认后端对这些接口返回 401/403 或业务错误码。
- 原有 `HabitManagement / MemoryManagement / MemoryExtractConfig` 的跳转守卫保留未改。
- 演示模式里的“切换演示身份”只存在于 mock 构建，real 构建中不存在该代码。

## 4. 页面与接口

各页面用到的接口、字段与状态见 [PAGE_MAPPING.md](./PAGE_MAPPING.md)。这里只列需要后端注意或确认的地方。

### 4.1 外壳 · 首页 · 设备 · 登录

| 位置 | 接口 | 说明 / 待确认 |
|---|---|---|
| 顶栏余额 | `GET /pay/quota/me` | 读取 `balance`、`balanceRealtime`、`balanceSource`。显示规则：请求失败或 `balance`/`balanceSource` 为空 → “余额暂不可用”；`balanceRealtime === false` 或 `balanceSource === 'cache'` → “余额可能不是最新”；否则显示数值。**待确认**：`balanceSource` 的全部取值（目前只按 `cache` 判断），以及 `balance` 的单位与 `formatPoints` 的换算是否与充值页一致。界面上不再出现 one-api、缓存、接口来源等字样。 |
| 首页统计 “在线设备” | 无 | **待后端**：现有接口没有设备在线状态字段，首页显示“暂不可查”并说明“已绑定 ≠ 在线”。后端提供字段后替换 `views/home.vue` 顶部 `home-stats__online` 处的“暂不可查”，并在设备行加在线标记。 |
| 首页智能体列表 | `GET /agent/list`、`GET /device/bind/:agentId` | 列表行的 `deviceCount` 用于统计“已绑定设备”；每个已绑定设备的智能体再请求一次 `/device/bind/:agentId` 取设备明细（搜索备注 / MAC 需要）。**待确认**：智能体较多时这是 N+1 请求，若后端能在列表中返回设备摘要可替换。 |
| 首页记忆名称、设备型号名称 | `GET /models/names`（Memory）、`GET /admin/dict/data/type/FIRMWARE_TYPE` | 只用于显示名称；普通用户调用字典接口在原代码中已存在，**待确认**普通用户有权读取 `FIRMWARE_TYPE`。 |
| 添加设备弹窗 · 验证码 / 恢复连接 | `POST /device/bind/:agentId/:deviceCode` | 两个入口调用同一接口（与原 `AddDeviceDialog` 的 recovery 模式相同），只有文案不同。 |
| 添加设备弹窗 · 手动添加 | `POST /device/manual-add` | `{ agentId, board, appVersion, macAddress }`，校验规则与原 `ManualAddDeviceDialog` 相同。 |
| 设备管理 | `GET /device/bind/:agentId`、`POST /device/unbind`、`PUT /device/update/:id` | 备注行内编辑提交 `{ alias }`；批量解绑逐条调用 `unbind`（与原逻辑一致）。 |
| 设备资源 | `GET /device/assets/list`、`POST /device/assets/upload`、`POST /device/assets/sync-assets` | **待确认**：mock 中资源列表的字段形状是按页面读取方式推断的，没有后端样例。 |
| 登录 / 注册 / 找回密码 | `/user/captcha`、`/user/pub-config`、`/user/login`、`/user/smsVerification`、`/user/register`、`/user/retrieve-password` | 字段不变。备案信息在 mock 中返回字符串 `'null'`（与原 `VersionFooter` 的判断一致）。 |
| 账户菜单 · 修改密码 | `PUT /user/change-password` | 逻辑不变，只换了弹窗外观。 |

### 4.2 其他页面

每组的接口、字段、演示规则与“待确认”清单（共 58 项）在分组文件里，联调时请逐条核对：

| 分组 | 页面 | 待确认在 |
|---|---|---|
| 智能体 | 角色配置、创建向导、聊天记录、默认角色模板 | [mapping/agents.md](mapping/agents.md) “(b) 待确认” |
| 人员与视觉 | 人员身份、声纹、视觉角色、壁纸包、设备图片资源 | [mapping/visuals.md](mapping/visuals.md) “(b) 待确认” |
| 充值与官方语音 | 充值、订单、支付结果、调用明细、音色、配音、官方语音管理 | [mapping/billing.md](mapping/billing.md) “(b) 待确认” |
| 知识库、记忆、习惯 | 知识库、文档上传、记忆管理、习惯管理、两个设置页 | [mapping/knowledge.md](mapping/knowledge.md) “(b) 待确认” |
| 系统管理 | 用户、模型、参数、字典、字段、服务端 | [mapping/admin.md](mapping/admin.md) “(b) 待确认” |

## 5. 跨页面问题（联调前请先处理或确认）

1. **业务错误不回调页面。** `httpRequest.js` 在 `code !== 0` 时只弹出全局提示，只有调用方传了 `failCallback` 才会通知页面；而大部分 API 模块方法没有传。结果是：接口返回业务错误时页面拿不到结果。改版页面为此加了 8–10 秒的兜底（之后显示“加载失败”并恢复按钮），所以**错误场景下失败状态要等几秒才出现**；记忆、习惯两个页面没有兜底，会保持加载状态。根治需要在 `src/apis/module/*` 的方法里补 `.fail()` 回调——本次按约定没有改 API 模块，留给联调阶段决定。
2. **在线状态缺字段**：见 4.1。首页只能显示“已绑定”。
3. **首页 N+1 请求**：见 4.1。
4. **余额来源取值**：`balanceSource` 为 `none` 时目前显示“余额暂不可用”；若 `none` 表示新账号余额为 0，应改为显示 0。
5. **支付**：mock 模式下不生成支付宝表单、不打开任何外部地址，改为“演示付款确认”弹窗；real 模式保留原逻辑（`/pay/order/create` 返回的表单），**真实支付链路完全未验证**。
6. **上传与设备指令**：知识库文档、人脸、复刻音频、视觉角色 / 壁纸包、设备图片资源在 mock 模式下只记录文件名、大小、类型；下载到设备、同步资源、服务端重启 / 更新配置只返回“演示结果”。上传大小限制、格式校验、任务状态枚举均按页面原有代码推断，需后端确认。
7. **管理员接口的普通用户访问**：`GET /agent/template`、`GET /admin/dict/data/type/{type}`、`/habits*` 是否允许普通用户调用，需后端确认（页面层面已按原代码处理）。
8. **用户 ID 校验**：用户管理页原有的“用户 ID 必须是数字”检查只在 mock 构建中放宽（演示 ID 形如 `demo-u-1001`），real 构建保持原检查。
9. **字段管理类别缺 VLLM**：与原代码一致，未改；需产品确认是否应加入。
10. **English 界面**：新文案都有中英文；原有页面里少量写死的中文（例如官方语音页的语气标签、方言列表、示例文案等数据类内容）保持原样。德语、越南语沿用英文覆盖文案，繁体中文沿用简体覆盖文案，未做专门翻译。

## 6. mock 层的边界

- 不发任何网络请求（QA 脚本对每个页面检查外部请求，结果为 0）。
- 不保存密码或密钥：登录密码只在内存中解密校验；模型 / 参数 / 字段里的密钥输入被替换为 `sk-demo-****`、`demo-****` 再保存；重置密码结果 `demo-xxxxxx` 只在内存生成。
- 浏览器只保存两项：演示数据库 `xn-mock-db-v1`（演示业务数据）与场景 `xn-mock-scenario-v1`；其余都是原代码已有的项：`token`（mock 下是 `mock-…` 随机串）、`isSuperAdmin`、`userLanguage`、`currentAgentId`、`sessionStorage.awakeningWizardSkipped`；改版只新增了首页视图偏好 `xn.home.view`（card / list）。
- real 构建中会保留少量 i18n 文案（如演示模式说明、“演示环境不保存密钥”），不会显示，也不含数据。
