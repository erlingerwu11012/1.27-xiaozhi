# 页面与路由地图

从实际 `src/router/index.js` 提取；权限和回调的最终依据仍是源码。路由为 Vue Router 默认 hash 模式。

- `/` — `../views/login.vue`
- `/role-config` — `../views/roleConfig.vue`
- `/voice-print` — 重定向路径
- `/face-management` — 重定向路径
- `/unified-user-management` — `../views/UnifiedUserManagement.vue`
- `/login` — `../views/login.vue`
- `/home` — `../views/home.vue`
- `/register` — `../views/register.vue`
- `/retrieve-password` — `../views/retrievePassword.vue`
- `/device-management` — `../views/DeviceManagement.vue`
- `/user-management` — `../views/UserManagement.vue`
- `/model-config` — `../views/ModelConfig.vue`
- `/params-management` — `../views/ParamsManagement.vue`；参数管理
- `/memory-extract-config` — `../views/MemoryExtractConfig.vue`；记忆提取配置
- `/habit-analyze-config` — `../views/HabitAnalyzeConfig.vue`；习惯分析配置
- `/habit-management` — `../views/HabitManagement.vue`；习惯管理
- `/role-pack-catalog` — `../views/RolePackCatalog.vue`；视觉角色
- `/wallpaper-pack-catalog` — `../views/WallpaperPackCatalog.vue`；壁纸包
- `/memory-management` — `../views/MemoryManagement.vue`；记忆管理
- `/knowledge-base-management` — `../views/KnowledgeBaseManagement.vue`；知识库管理
- `/knowledge-file-upload` — `../views/KnowledgeFileUpload.vue`；文档上传管理
- `/server-side-management` — `../views/ServerSideManager.vue`；服务端管理
- `/ota-management` — 重定向路径
- `/dict-management` — `../views/DictManagement.vue`
- `/provider-management` — `../views/ProviderManagement.vue`
- `/agent-template-management` — `../views/AgentTemplateManagement.vue`
- `/template-quick-config` — `../views/TemplateQuickConfig.vue`
- `/billing/packages` — `../views/BillingPackages.vue`；充值套餐
- `/billing/result` — `../views/BillingResult.vue`；支付结果
- `/billing/orders` — `../views/BillingOrders.vue`；账单
- `/official-tts/voices` — `../views/OfficialTtsVoices.vue`；我的音色
- `/official-tts/dubbing` — `../views/OfficialTtsDubbing.vue`；配音工作台
- `/admin/official-tts` — `../views/OfficialTtsAdmin.vue`；官方TTS管理

## 旧文件与当前路由

`VoicePrint.vue` 与 `FaceManagement.vue` 仍保留在源码中，但对应旧路由目前会跳转到统一人员管理。不要因为看到了旧文件就重新启用独立入口。

管理员、登录状态、已有设备关联关系应按路由和页面中的原条件保留。仅静态存在一个 .vue 文件不代表每个账号都能访问。
