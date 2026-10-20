# manager-web 前端改版（redesign v1）

基于已确认的 v1 原型（侧栏 + 卡片、浅色控制台）对 manager-web 全部现有页面做的前端改版，仍是原来的 Vue 2 项目：

- 路由、业务逻辑、API 契约（URL、方法、字段、枚举）与权限边界保持不变；
- 新增独立的演示数据层（`src/mock`），默认开启，**不向任何服务发送请求**；
- 后端联调由后续阶段完成，见 [INTEGRATION.md](./INTEGRATION.md)；页面与接口对照见 [PAGE_MAPPING.md](./PAGE_MAPPING.md)；开发约定见 [DEVELOPER_GUIDE.md](./DEVELOPER_GUIDE.md)；功能清单见 [FEATURES.md](./FEATURES.md)；检查记录见 [QA.md](./QA.md)。

> 用演示数据跑通的流程只说明前端交互完整，**不代表真实业务已经联调验证**。

## 本地运行

需要 Node 20（已在 Node 22 上验证）与 npm。

```sh
cd manager-web
npm ci --ignore-scripts --no-audit --no-fund
cp .env.example .env.local          # Windows PowerShell：Copy-Item .env.example .env.local
npm run serve                       # 打开 http://localhost:8001/#/login
```

> `package-lock.json` 里的下载地址是 `registry.npmmirror.com`。如果所在网络访问不了这个镜像，可以临时把 lockfile 中的地址换成 `https://registry.npmjs.org` 再执行 `npm ci`，装完后用 `git checkout package-lock.json` 还原（版本与校验值不变）。

演示账号（只在 mock 模式存在）：

| 账号 | 身份 | 密码 |
|---|---|---|
| `demo_user` | 普通用户 | 任意非空内容 |
| `demo_admin` | 管理员 | 任意非空内容 |

图形验证码按图片填写；短信验证码为 `000000`；设备绑定的演示验证码为 `123456`、`246810`、`135790`、`888888`（每个用一次）。

侧栏底部的 **演示模式** 可以：切换演示身份（普通用户 / 管理员）、切换数据场景（正常 / 空数据 / 服务异常）、切换余额状态（正常 / 可能不是最新 / 暂不可用）、重置演示数据。演示数据保存在本机浏览器的 `localStorage['xn-mock-db-v1']`，不包含任何密码或密钥。

## 构建

```sh
npm run build                 # 输出 dist/，默认是 mock 演示构建
npm run check:i18n-ota        # 原有的 OTA 文案完整性检查
npm run check:mock            # 新增：检查每个接口调用都有演示实现
```

构建产物是纯静态文件（hash 路由），用任意静态服务器打开即可预览，例如：

```sh
npx serve dist                # 或：cd dist && python3 -m http.server 8080
```

### 浏览器检查脚本（可选）

需要 Python 3 与 Playwright（`pip install playwright==1.55.0 && python -m playwright install chromium`；已有 Chromium 时用环境变量 `CHROMIUM=/path/to/chromium` 指定）。先启动 `npm run serve`（或静态打开 mock 构建的 `dist/`）：

```sh
python3 tools/qa/crawl_routes.py --base http://localhost:8001 --out qa-out             # 两种身份逐页检查 + 截图
python3 tools/qa/crawl_routes.py --base http://localhost:8001 --out qa-960 --width 960 --height 800
python3 tools/qa/core_flows.py                                                         # 首页、添加设备、删除确认、设备、账户菜单、演示模式、英文界面
```

`core_flows.py` 默认访问 `http://localhost:8001`、Chromium 路径 `/opt/pw-browsers/chromium`，需要时改 `tools/qa/xnqa.py` 顶部两行；截图写到 `qa-out/core`（可用环境变量 `QA_OUT` 指定）。`qa-out*` 是本地输出，不要提交。

### 切换到真实接口

```sh
# .env.local
VUE_APP_DATA_MODE=real
VUE_APP_API_BASE_URL=/xiaozhi            # 与原来相同
VUE_APP_PROXY_TARGET=http://127.0.0.1:8002
```

`VUE_APP_DATA_MODE` 只有写成小写 `real` 才走真实接口，其他任何值都是 mock。判断是构建期常量：real 构建时 webpack 会整段剔除 `src/mock`、演示模式面板与演示数据，Service Worker 也恢复原来的注册逻辑。

## 主要改动

| 范围 | 说明 |
|---|---|
| 外壳 | `App.vue` + `components/layout/AppLayout.vue`：分组侧栏（管理员分组只对管理员显示）、顶栏（添加设备、余额、账户菜单、语言、修改密码、退出）、演示模式面板、无权限状态。原 `HeaderBar.vue` 的功能全部移入外壳。 |
| 设计规范 | `styles/tokens.scss`、`styles/global.scss`、`styles/element-variables.scss`（Element 主题从 theme-chalk 源码按规范编译）、`assets/fonts`（Noto Serif SC 常用字子集，仅用于页面标题与智能体名称）。 |
| 共用组件 | `common/XnIcon`（线性图标）、`common/PageHeader`、`common/XnEmpty`（空 / 失败状态）、`common/DemoTag`；`DeviceBindDialog`（验证码绑定、恢复连接、手动添加合并为一个弹窗，替代原 `AddDeviceDialog` 与 `ManualAddDeviceDialog`）。 |
| 首页 | 智能体卡片 / 列表视图、按名称 / 设备备注 / MAC 搜索、绑定状态筛选；“已绑定设备数”和“在线设备”分开显示（目前接口没有在线状态，显示“暂不可查”）；去掉独立余额卡片和绑定卡片。 |
| 页面 | 所有页面去掉内嵌 HeaderBar、页脚和装饰背景，统一为“标题区 + 工具栏 + 面板 / 表格 + 分页”的结构；登录、注册、找回密码改为浅色单卡片。 |
| 演示数据层 | `src/mock`：在 `httpRequest.js` 的 `send()` 处接入，API 模块零改动。 |
| 文案 | `src/i18n/redesign/`：新增文案（`xn.` 前缀）与覆盖原文案（去掉 one-api、缓存等实现细节）。 |
| 其他 | `utils/media.js`（音频、下载、图片在 mock 模式下的安全替代）、`config/navigation.js`（侧栏与面包屑）、路由 `meta.adminOnly`、`registerServiceWorker.js`（mock 构建不注册）、`vue.config.js`（只加了 Sass 弃用提示的屏蔽）、`package.json`（`sideEffects` 增加 `src/mock`，新增 `check:mock` 脚本）。 |
