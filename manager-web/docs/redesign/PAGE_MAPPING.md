# 页面对照（原页面 → 改版页面 → 后端接口 → 状态）

覆盖 manager-web 的全部路由。状态栏的“完成”指**前端改版完成、演示数据下交互可用**；所有页面都**没有连接真实后端验证**。各组的逐组件对照、接口清单与待确认项见 `mapping/` 下的分组文件。

| 路由 | 原页面 | 改版后 | 主要后端接口 | 权限 | 状态 | 详细 |
|---|---|---|---|---|---|---|
| `/login` | login.vue | 浅色单卡片，账号 / 手机号登录 | `/user/captcha`、`/user/pub-config`、`/user/login`、`/user/smsVerification` | 公开 | 完成 | [core](mapping/core.md) |
| `/register` | register.vue | 同上 | `/user/register`、`/user/smsVerification` | 公开 | 完成 | [core](mapping/core.md) |
| `/retrieve-password` | retrievePassword.vue | 同上 | `/user/retrieve-password`、`/user/smsVerification` | 公开 | 完成 | [core](mapping/core.md) |
| 外壳（所有登录后页面） | HeaderBar.vue、VersionFooter | 分组侧栏 + 顶栏（添加设备、余额、账户菜单） | `/user/info`、`/pay/quota/me`、`/user/change-password` | 登录 | 完成；原 HeaderBar 已删除 | [core](mapping/core.md) |
| `/home` | home.vue、DeviceItem.vue | 智能体卡片 / 列表、搜索、绑定筛选、统计 | `/agent/list`、`/agent`、`/device/bind/:agentId`、`/models/names` | 登录 | 完成；在线状态待后端 | [core](mapping/core.md) |
| 添加设备（弹窗） | AddDeviceDialog、ManualAddDeviceDialog | DeviceBindDialog：验证码 / 恢复连接 / 手动添加 | `/device/bind/:agentId/:code`、`/device/manual-add` | 登录 | 完成；原两个组件已删除 | [core](mapping/core.md) |
| `/device-management` | DeviceManagement.vue、DeviceAssetsDialog | 设备表格、备注、解绑、资源 | `/device/*` | 登录 | 完成 | [core](mapping/core.md)、[visuals](mapping/visuals.md) |
| `/role-config` | roleConfig.vue、FunctionDialog、PersonaPresetPicker | 角色设定 + 模型与声音两栏 | `/agent/:id`、`/models/*`、`/agent/mcp/*` | 登录 | 完成 | [agents](mapping/agents.md) |
| 创建智能体（弹窗） | AwakeningWizard.vue | 三步弹窗 | `/agent`、`/models/*`、`/voiceClone/audio/:id` | 登录 | 完成 | [agents](mapping/agents.md) |
| 聊天记录（弹窗） | ChatHistoryDialog.vue | 会话列表 + 消息 + 下载 | `/agent/:agentId/sessions`、`/agent/:agentId/chat-history/*`、`/agent/audio/*` | 登录 | 完成 | [agents](mapping/agents.md) |
| `/unified-user-management` | UnifiedUserManagement.vue、VoicePrintDialog | 成员表格 + 人脸 / 声纹 | `/user-identities/*`、`/face/profiles*`、`/face/enrollment*`、`/agent/voice-print*` | 登录 | 完成 | [visuals](mapping/visuals.md) |
| `/voice-print`、`/face-management` | VoicePrint.vue、FaceManagement.vue | 原样重定向到人员身份 | — | 登录 | 未改（重定向） | [visuals](mapping/visuals.md) |
| `/role-pack-catalog` | RolePackCatalog.vue | 视觉角色卡片、下载到设备、发布（管理员） | `/role-packs/*` | 登录（发布仅管理员） | 完成 | [visuals](mapping/visuals.md) |
| `/wallpaper-pack-catalog` | WallpaperPackCatalog.vue | 同上 | `/wallpaper-packs/*` | 同上 | 完成 | [visuals](mapping/visuals.md) |
| `/official-tts/voices` | OfficialTtsVoices.vue | 音色设计 / 复刻 | `/official-tts/*` | 登录 | 完成 | [billing](mapping/billing.md) |
| `/official-tts/dubbing` | OfficialTtsDubbing.vue、OfficialTtsVoiceLibrary | 配音编辑 + 我的配音 | `/official-tts/*` | 登录 | 完成 | [billing](mapping/billing.md) |
| `/knowledge-base-management` | KnowledgeBaseManagement.vue、KnowledgeBaseDialog | 知识库表格 | `/datasets*` | 登录 | 完成 | [knowledge](mapping/knowledge.md) |
| `/knowledge-file-upload` | KnowledgeFileUpload.vue | 文档、解析、切片、召回测试 | `/datasets/:datasetId/*` | 登录 | 完成 | [knowledge](mapping/knowledge.md) |
| `/billing/packages` | BillingPackages.vue、HardwareCallBills | 余额 + 套餐 + 调用明细；演示支付确认 | `/pay/*` | 登录 | 完成（支付为演示） | [billing](mapping/billing.md) |
| `/billing/result` | BillingResult.vue | 订单状态 | `/pay/order/query/:orderNo` | 登录 | 完成 | [billing](mapping/billing.md) |
| `/billing/orders` | BillingOrders.vue | 订单表格 | `/pay/orders` | 登录 | 完成 | [billing](mapping/billing.md) |
| `/user-management` | UserManagement.vue、ViewPasswordDialog | 用户表格、批量操作、重置密码 | `/admin/users*` | 管理员 | 完成 | [admin](mapping/admin.md) |
| `/model-config` | ModelConfig.vue、AddModelDialog、ModelEditDialog、TtsModel、AudioPlayer | 类别 + 模型表格、音色管理 | `/models/*`、`/ttsVoice*` | 管理员 | 完成 | [admin](mapping/admin.md) |
| `/params-management` | ParamsManagement.vue、ParamDialog | 参数表格 | `/admin/params*` | 管理员 | 完成 | [admin](mapping/admin.md) |
| `/dict-management` | DictManagement.vue、DictTypeDialog、DictDataDialog | 类型 + 数据两栏 | `/admin/dict/*` | 管理员 | 完成 | [admin](mapping/admin.md) |
| `/provider-management` | ProviderManagement.vue、ProviderDialog | 字段管理表格 | `/models/provider*` | 管理员 | 完成 | [admin](mapping/admin.md) |
| `/server-side-management` | ServerSideManager.vue | 服务端表格 + 操作结果 | `/admin/server/*` | 管理员 | 完成（操作为演示） | [admin](mapping/admin.md) |
| `/agent-template-management` | AgentTemplateManagement.vue | 模板表格 | `/agent/template*` | 管理员 | 完成 | [agents](mapping/agents.md) |
| `/template-quick-config` | TemplateQuickConfig.vue | 模板表单 | `/agent/template*` | 管理员 | 完成 | [agents](mapping/agents.md) |
| `/admin/official-tts` | OfficialTtsAdmin.vue | 价格版本、结算 | `/admin/official-tts/*` | 管理员 | 完成 | [billing](mapping/billing.md) |
| `/memory-management` | MemoryManagement.vue | 记忆表格 | `/admin/memory*`（Python 服务） | 管理员（原跳转守卫） | 完成 | [knowledge](mapping/knowledge.md) |
| `/memory-extract-config` | MemoryExtractConfig.vue | 设置表单 | `/admin/params*` | 管理员（原跳转守卫） | 完成；修正了原读取路径 | [knowledge](mapping/knowledge.md) |
| `/habit-management` | HabitManagement.vue | 习惯表格 | `/habits*` | 管理员（原跳转守卫） | 完成 | [knowledge](mapping/knowledge.md) |
| `/habit-analyze-config` | HabitAnalyzeConfig.vue | 设置表单 | `/admin/params*` | 管理员 | 完成 | [knowledge](mapping/knowledge.md) |
| `/ota-management` | — | 原样重定向到视觉角色 | — | — | 未改 | — |
| `/` | welcome | 原跳转逻辑 | — | — | 未改 | — |

## 未改版的组件

`AddWisdomBodyDialog.vue`、`EditVoiceDialog.vue`、`VoiceResourceDialog.vue` 在原代码中已经没有任何引用（不在任何路由或页面中出现），保留原样未改。

## 改版中的“非样式”改动

只列出行为有变化的地方（新功能一律未加）：

- **修正原有缺陷**：记忆设置页读取参数的路径错误（原来读不到已保存设置，保存也不生效）；记忆“清空该设备”按搜索框文字而非已生效的筛选执行；习惯编辑保存提示“已创建”；字段管理弹窗的类别下拉没有文字；字典类型搜索同时过滤了类型列表；多个音频播放器时拖动进度取错元素；DictType / DictData 弹窗 `title` 默认值的 `this` 为空。
- **交互调整**：默认角色模板搜索从“只过滤当前页”改为按名称从第 1 页查询（原请求本来就带该参数）；创建向导点遮罩不再关闭；删除某页最后一条后回到上一页；重置密码结果改用 ViewPasswordDialog 显示，不再用 HTML `$alert`；视觉角色页补上了与壁纸页相同的下载任务进度轮询；人员身份页把原本隐式取第一个智能体的“声纹样本来源”显示为可选下拉（仍写入 `?agentId`）；人脸“设备抓拍”的丢弃 / 刷新从原 FaceManagement 页移入人员身份页。
- **未加的入口**：API 模块里有视觉角色 / 壁纸包的 `detail`、`disable` 与配音的 `cancelJob`，原页面没有入口，改版也没有加。
