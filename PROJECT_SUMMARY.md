# 项目结构与修改入口

## 项目是什么

这是小念 AI 桌面伙伴现有的网页控制台，包含智能体与设备配置、人员身份、视觉角色与壁纸、知识库、计费、官方 TTS 和管理员配置等功能。用户本轮要求把当前前端交给 Claude 修改，没有授权在交接过程中改线上业务或部署新页面。

## 主要文件

- `manager-web/src/main.js`：Vue、Element UI、i18n、Vuex 和全局样式初始化；还包装了全局删除确认弹窗。
- `manager-web/src/App.vue`：路由出口、全局背景、移动端跳转、Matrix 转场和 CDN 缓存查看相关逻辑。
- `manager-web/src/router/index.js`：hash 路由、旧路径跳转、登录检查和部分管理员页面限制。
- `manager-web/src/components/HeaderBar.vue`：目前的主导航、用户入口及按管理员状态显示的菜单。
- `manager-web/src/views/home.vue`：智能体主界面。
- `manager-web/src/views/DeviceManagement.vue`：设备管理和相关操作入口。
- `manager-web/src/views/roleConfig.vue`：LLM 人设、模型和角色配置；与屏幕上的视觉 Spine 角色不是同一个概念。
- `manager-web/src/views/UnifiedUserManagement.vue`：统一人员管理，整合人脸和声纹身份。
- `manager-web/src/components/DeviceAssetsDialog.vue`：设备视觉资源操作。
- `manager-web/src/components/AwakeningWizard.vue`：唤醒词等向导。
- `manager-web/src/components/PersonaPresetPicker.vue`、`src/constants/personaPresets.js`：人设预设。
- `manager-web/src/styles/global.scss`：全局组件和消息框覆盖。
- `manager-web/src/views/auth.scss`：认证页面共用样式。
- `manager-web/src/styles/official-tts-studio.scss`：官方 TTS 工作台样式。
- `manager-web/src/i18n/`：简中、繁中、英文、德文和越南语文案；中文与英文 OTA 文案有独立完整性检查。
- `manager-web/vue.config.js`：开发代理、构建、CDN 和 Service Worker。

## 现有业务分组

### 登录与账户

`login.vue`、`register.vue`、`retrievePassword.vue`，以及修改密码、查看密码等弹窗。登录涉及验证码、公共配置、SM2 等既有流程。改视觉时不要把这些替换为假登录。

### 智能体、设备与身份

`home.vue`、`roleConfig.vue`、`DeviceManagement.vue`、`UnifiedUserManagement.vue`。保留设备绑定、配置、人员归属、向导和状态展示的实际请求。人脸与声纹旧路由已重定向至统一人员管理，不应重新制作成互不关联的用户体系。

### 视觉素材

`RolePackCatalog.vue`、`WallpaperPackCatalog.vue` 和 `DeviceAssetsDialog.vue`。屏幕角色包与壁纸包的上传、版本、设备下发和 OTA 状态属于业务流程，不能仅保留漂亮的卡片。不要把屏幕角色包误当成人设提示词。

### 记忆、习惯与知识库

`MemoryManagement.vue`、`MemoryExtractConfig.vue`、`HabitManagement.vue`、`HabitAnalyzeConfig.vue`、`KnowledgeBaseManagement.vue`、`KnowledgeFileUpload.vue`。

当前源码存在管理员记忆管理页面，不代表普通用户已有查看个人记忆的入口。路由明确限制部分记忆和习惯页面只供管理员进入。不要在这次美化时自动开放个人记忆列表、导出功能或改变后台提取策略。

### 余额、账单与支付

`BillingPackages.vue`、`BillingOrders.vue`、`BillingResult.vue` 和 `HardwareCallBills.vue`。这里的“充值套餐”是充值购买额度的页面，不是新增月租订阅。现有订单、支付结果、调用费用等语义需保留；不要写死余额、支付成功或价格。

### 官方 TTS

`OfficialTtsVoices.vue`、`OfficialTtsDubbing.vue`、`OfficialTtsAdmin.vue`，以及音色库和工作台组件。需要保留音色权限、试听、合成、下载、失败和等待状态。

### 管理员工具

用户管理、模型配置、参数、服务提供商、字典、服务端配置、默认人设模板和快速配置等。视觉统一时保留管理员可见条件，不要将全部管理工具展示给普通用户。

## 请求与状态约定

1. `src/apis/api.js` 聚合 16 个业务模块，读取 `VUE_APP_API_BASE_URL`。
2. `src/apis/httpRequest.js` 使用 flyio，默认 30 秒超时，从 Vuex token 中读取 JSON 对象的 `token` 字段，以 `Authorization: Bearer ...` 发送。
3. 请求包含 `Accept-Language`；现有成功响应兼容 `code: 0`、`code: 'success'` 或无 code。回调处对 `res` / `res.data` 的使用并不完全相同，重构时须逐处核对。
4. `src/store/index.js` 保留 token、userInfo、isSuperAdmin 和公共配置，部分值存入 localStorage。
5. 页面上的管理员显示条件属于 UI 逻辑；不能通过伪造管理员 localStorage 绕过实际权限去操作线上接口。
6. 记忆模块单独使用 `VUE_APP_PYTHON_API_URL` 访问 `/admin/memory`；不要把它的响应结构改造成与其他模块完全相同而不核对。

## 样式改造建议

目前样式分散在 App、全局 SCSS、各页面的 scoped 样式和 Element UI 覆盖中。先定义颜色、间距、字号、圆角、阴影和状态语义，再调整共享导航、工具栏、卡片、表格和弹窗，最后逐页覆盖。减少全局 `!important` 继续叠加，验证已有弹窗和浮层没有被新样式压住。

默认建议是清晰、精致的浅色控制台。众筹图的温暖风格可以作为品牌气质参考，但业务后台应优先保证信息密度、可读性、状态辨识和操作效率。具体视觉方向由用户与 Claude 在修改时确认。
