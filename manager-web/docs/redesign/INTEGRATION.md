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

<!-- 以下各节由各页面组的联调说明合并而来 -->
