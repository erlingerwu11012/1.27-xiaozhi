# 直接复制下面的内容给 Claude

请读取我的小念网页管理后台源码，并直接修改这份真实 Vue 项目。

GitHub 分支：
https://github.com/erlingerwu11012/1.27-xiaozhi/tree/codex/server-frontend-claude-20261019

如果 GitHub 连接器只能看到默认分支，请直接获取这个分支的源码压缩包：
https://raw.githubusercontent.com/erlingerwu11012/1.27-xiaozhi/codex/server-frontend-claude-20261019/claude-manager-web-handoff.zip

先读取根目录 README.md、PROJECT_SUMMARY.md、SOURCE_PROVENANCE.md、PAGE_MAP.md、API_SURFACE.json、VALIDATION.json，然后检查 manager-web/src 下的实际文件。不要只根据说明自行重写一个与现有项目无关的示范页面。

这次范围只有 manager-web 网页管理后台。One-API 不用改，移动端暂时不用改，也不做众筹图片或宣传视频。

当前技术栈是 Vue 2 + Vue CLI 5 + Vue Router 3 + Vuex 3 + Element UI 2 + SCSS + Vue I18n。沿用现有技术栈、package-lock.json 和 API 模块，不迁移到 React / Vue 3，不用静态图片或全假数据替代原来的应用。

我要你把界面做得更精致、清楚、统一。默认先以现代简洁的浅色控制台为方向，改善导航层级、布局、字体、间距、按钮、卡片、表格、弹窗、空状态、加载状态和错误反馈。不要只换背景或添加大量发光装饰。先建立统一视觉规范，再落实到真实源码。

请按以下步骤工作：

1. 先梳理当前首页、设备管理、人员身份、角色与壁纸、账单、TTS 和管理员页面，指出实际入口和共享组件。
2. 先制作首页与设备管理的可运行修改，建立共享设计规范，并提供清晰的桌面预览；用户确认方向后再扩展其他页面。
3. 保留原有登录、验证码、权限、设备绑定、人设配置、人员归属、角色包与壁纸 OTA、账单和 TTS 流程。角色包是屏幕视觉形象，人设配置是 LLM 行为设置，不要混为一谈。
4. 保留现有 API 地址拼接、HTTP 方法、请求字段、响应结构和错误处理。需要修改接口时先说明原因，不要编造服务端已经存在的新接口。
5. 保留普通用户与管理员界面的区别。不要给普通用户新增查看后台记忆、修改后台提取策略或管理全站用户等入口。当前用户也没有已交付的记忆导出功能，不要擅自加入。
6. 本包没有服务器密钥、生产环境配置、后台服务、真实账号和个人数据。默认仅使用本地服务或隔离 Mock 进行预览；Mock 必须在开发测试层单独实现，明确标注演示数据，正式代码继续调用原有 API。禁止通过伪造登录/支付成功或返回假设备列表来宣称功能完成。
7. 请沿用本来的 i18n，检查简体中文与英文中相关文案，运行 npm run check:i18n-ota 和 npm run build。没有运行的检查要说明，不要宣称已通过。
8. 不连接生产数据库，不读取用户记忆或摄像头数据，不部署到我的阿里云服务器，不提交或推送代码到 GitHub。你先交付可下载的修改后源码和预览；后续我会另行安排上线。

运行方法在 README.md。建议 Node 20，先 npm ci --ignore-scripts --no-audit --no-fund，再复制 .env.example 为 .env.local，npm run serve，默认 localhost:8001。

如果没有后端，登录和受保护页面无法真实联调是正常的。请用独立开发测试数据展示布局，并明确列出真实接口尚未验证的流程；不要改掉鉴权保护来让演示“看起来能用”。

最终请交付：修改后的 Vue/JS/SCSS 文件、可下载源码 ZIP、关键页面预览图、变更清单、运行与构建记录，以及仍需真实后端联调的项目。请从读代码与首页/设备管理开始，不要再次向我索要此包中已经提供的资料。
