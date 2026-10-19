# 小念网页管理后台：Claude 前端修改交接包

2026 年 10 月 19 日通过 SSH 从实际阿里云服务器只读提取。这里是网页管理后台的独立源码快照，供 Claude 网页端读取、修改和输出可合并的代码。

**范围已经由项目所有者确认：只处理 manager-web；One-API 不改，移动端暂时不改。** 这不是众筹详情图、广告视频或新建宣传网站的项目。

## 从哪里开始

1. 阅读 `CLAUDE_PROMPT.md`，整段复制给 Claude。
2. 阅读 `PROJECT_SUMMARY.md`，理解页面、业务、样式和接口入口。
3. 阅读 `SOURCE_PROVENANCE.md`，确认这份工作区快照与线上、旧发布目录之间的关系。
4. 真正修改的代码在 `manager-web/`。页面地图在 `PAGE_MAP.md`；接口提取清单在 `API_SURFACE.json`。
5. `VALIDATION.json` 记录本次检查结果及未验证的事项。

仓库分支：`codex/server-frontend-claude-20261019`。只上传这份前端交接包，没有将 ESP32 固件或整个服务端混入此分支。

## 技术栈

- Vue 2、Vue CLI 5、Vue Router 3、Vuex 3。
- Element UI 2、SCSS、Vue I18n 8。
- flyio 封装业务请求；API 模块位于 `src/apis/module/`。
- 服务端目前 Node 20.20.0 / npm 10.8.2；依赖使用原始 `package-lock.json`。
- 当前包含 31 个页面组件、30 个公共组件、16 个 API 模块。

## 本地运行

建议 Node 20，并使用 npm。安装阶段先禁用依赖生命周期脚本：

```sh
cd manager-web
npm ci --ignore-scripts --no-audit --no-fund
# macOS / Linux
cp .env.example .env.local
# Windows PowerShell 用 Copy-Item .env.example .env.local
npm run serve
```

默认访问 `http://localhost:8001/`。路由使用 hash 模式，例如 `http://localhost:8001/#/login`。

```sh
npm run check:i18n-ota
npm run build
```

示例配置将 `/xiaozhi` 代理到本机 `127.0.0.1:8002`。本包不含 Java/Python 后端，所以没有另行启动后端或设置隔离 Mock 时，登录、设备列表等接口不会正常返回。编译通过不代表完成线上登录、支付、OTA 或设备联调。

`/admin/memory` 使用单独的 Python API 路径，开发服务器原配置仅代理 `/xiaozhi`。本地预览该管理页面需单独配置测试服务或隔离 Mock，不要误以为已经包含记忆后端。

## 素材、配置与公开内容

保留了源代码引用的原图标、背景、头像、favicon 和离线页。原始环境文件、npm 配置、日志、依赖、编译产物、缓存和 PC 执行器下载压缩包没有上传；详见 `SOURCE_MANIFEST.json` 的 `excluded`。

`.env.example` 是新建的本机示例，不是线上配置。没有附带账号、登录令牌、阿里云访问密钥、数据库、用户对话、用户记忆或摄像头数据。此分支不提供服务器登录凭据。

上游 MIT 许可证保留在 `UPSTREAM_LICENSE`。原来的项目说明位于 `manager-web/README.md`。

## 建议给 Claude 的工作方式

先改首页和设备管理，建立一致的布局、字阶、颜色、表格、弹窗和按钮规范，再覆盖其他页面。保留现有接口与权限逻辑；预览所需样例数据必须与真实接口明确隔离。最终交付实际 Vue 源文件、修改说明、构建结果和桌面端预览图，而不是一张不可编辑的设计图。
