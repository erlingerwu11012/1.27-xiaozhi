# 映射说明：visuals（人员身份 · 声纹 · 视觉角色 · 壁纸包 · 设备图片资源）

## (a) 页面 / 组件对照

| 原页面 / 组件 | 路由 | 新位置 / 改动 | 后端接口（METHOD path） | 状态 |
|---|---|---|---|---|
| `views/UnifiedUserManagement.vue` | `/unified-user-management?agentId=` | 侧栏“我的小念 › 人员身份”。去掉 HeaderBar / VersionFooter / 卡片墙，改为页面骨架 + 表格（成员 / 人脸 / 声纹 / 操作），搜索、筛选（未绑定人脸 / 未录入声纹）、分页；加载 / 空 / 无匹配 / 失败状态。成员—人脸—声纹的统一身份模型不变。新增“声纹语音来源”智能体选择（原来只能用 `?agentId` 或第一个智能体），同步到 `?agentId`。人脸弹窗三页签：上传照片 / 设备采集 / 已有人脸资料；设备采集页签补上了原 FaceManagement 里的“丢弃”与“刷新”。所有文案进 i18n。 | GET `/user-identities/users`、GET `/user-identities/voiceprints`、POST `/user-identities/users`、PUT `/user-identities/users/{id}/display-name`、DELETE `/user-identities/users/{id}`、POST/DELETE `/user-identities/users/{id}/faces/{faceId}`、POST/DELETE `/user-identities/users/{id}/voiceprints/{vpId}`；GET `/face/profiles?include_draft=true`、POST `/face/profiles`、POST `/face/profiles/{id}/faces`、POST `/face/profiles/{id}/activate`、GET `/face/enrollment/sessions`、GET `/face/enrollment/sessions/{id}/preview`(blob)、POST `/face/enrollment/sessions/{id}/confirm`、DELETE `/face/enrollment/sessions/{id}`；POST/PUT `/agent/voice-print`；GET `/agent/list` | 完成 |
| `components/VoicePrintDialog.vue` | （弹窗） | 普通 el-dialog（标题 + 取消 / 保存声纹），去掉自绘关闭按钮、渐变与内联样式；样本下拉带试听按钮，空样本提示；校验文案 i18n。props / 事件不变（`submit({form, done})`、`cancel`），另外 emit `update:visible`（修复原来在组件内 `.sync` 改 prop 的告警）。试听改用 `playableUrl()`。 | GET `/agent/{id}/chat-history/user`、GET `/agent/{audioId}/chat-history/audio`、POST `/agent/audio/{audioId}`，播放 `/agent/play/{id}` | 完成 |
| `views/RolePackCatalog.vue` | `/role-pack-catalog` | 侧栏“屏幕与声音 › 视觉角色”。页面骨架 + 搜索 + 卡片网格（封面、名称、版本、简介）；新增详情弹窗（调用原有但未使用的 `detail` 接口，失败时退回目录信息）；下载到设备弹窗（无设备时引导去设备管理）；任务弹窗加入与壁纸页相同的 `getTask` 轮询与进度；管理员：发布（文件选择、自动识别、可选简介）与“停用”（原 API 已有 `disable`，原界面无入口）。与 roleConfig（人设）的区别写在页首说明里。 | GET `/role-packs/catalog`、GET `/role-packs/{packId}`、POST `/role-packs/{packId}/deploy/{deviceId}`、GET `/role-packs/tasks/{taskId}`、POST `/role-packs/inspect`、POST `/role-packs/publish`、POST `/role-packs/{packId}/disable`；GET `/agent/list`、GET `/device/bind/{agentId}` | 完成 |
| `views/WallpaperPackCatalog.vue` | `/wallpaper-pack-catalog` | 与视觉角色页同构（2 MB 上限、识别字段 default_id / 图片数量）。原有任务轮询保留。 | `/wallpaper-packs/*`（同上 7 个） | 完成 |
| `components/DeviceAssetsDialog.vue` | （设备管理 › 资源管理） | 普通弹窗：类型分段选择 + 上传按钮、已上传图片网格（类型筛选、版本号）、底部“关闭 / 同步到设备”。图片地址经 `imageUrl()`；成功提示优先显示服务端 msg（演示模式会写明“未下发”）。props / 事件不变。 | GET `/device/assets/list?device_id=`、POST `/device/assets/upload`(FormData device_id, file_type, file)、POST `/device/assets/sync-assets?device_id=` | 完成 |
| `views/FaceManagement.vue`、`views/VoicePrint.vue` | `/face-management`、`/voice-print` → 重定向到 `/unified-user-management` | 只去掉 HeaderBar / VersionFooter 引用，便于删除 HeaderBar；未改版。 | — | 完成（遗留） |

Mock：`src/mock/handlers/face.js`、`userIdentity.js`、`rolePack.js`（含 `registerPackRoutes`）、`wallpaperPack.js`；种子 `src/mock/seed/identity.js`、`visualPacks.js`（含 `deviceAssets` 初始图片）；`handlers/device.js` 末尾三个设备资源接口按 DeviceAssetsDialog 的字段（`id / fileType / fileUrl / version`）重写。共 27 个接口（user-identities 9、face 9、role-packs 7 + wallpaper-packs 7 由同一工厂注册、device assets 3 → 实际注册 35 条路由）。

## (b) 待确认 / 后端联调问题

1. **声纹与成员的自动关联**：页面新建声纹时 POST `/agent/voice-print` 带 `userId`（成员 id），之后不再调用 bindVoiceprint。演示里假定后端会据此把声纹归到该成员（GET users 时归并）。需确认真实后端行为。
2. **删除成员**是否连带删除人脸资料与声纹记录（确认文案这样写；演示照此实现）。
3. **业务错误不回调**：`rolePack / wallpaperPack / face / userIdentity` 的 API 模块只有 `success` 与 `networkFail`，code≠0 时请求层直接弹出 `msg`、页面回调不执行。页面加了 10 秒超时用于恢复按钮 / 显示失败状态。建议后端对 OTA 错误同时返回可读的 `msg` 与 `errorCode`，或在 API 模块加 `.fail()`（不在本组范围）。
4. **视觉包目录字段**：页面会显示 `description / version / size / previewImageUrl / previewVideoUrl / publishedAt`，详情还读 `spineRuntimeVersion / defaultSupportedBoards / minFirmware`（壁纸 `defaultId / itemCount`）。真实接口返回哪些字段待确认；缺失的字段不显示。
5. **发布时的 `description`**：API 原本支持，原界面未提供输入框，现已加可选输入。同一 `packId` 重复发布时，演示按“新版本覆盖”处理，真实行为待确认。
6. **停用后**目录是否对管理员仍可见、能否重新启用：原接口只有 disable，演示中停用后从目录消失。
7. **任务状态值**：演示推进 `queued → sent → downloading → verifying → applying → succeeded`（按创建后经过时间，每 2 秒一步）；`E_BUSY` 在同设备有未结束任务时返回。真实状态集合以 `visualOta.state.*` 为准。
8. **设备资源**：`version` 是否按“设备 + 类型”递增、列表排序、`sync-assets` 是否已在后端实现（原代码注释写着“占位，后端稍后实现”）待确认。
9. **人脸照片上传**：演示只计数，不做人脸检测；真实后端对“每张只含一张人脸”的校验结果与错误文案待确认。

## (c) 未完成 / 说明

- 演示模式下“查看演示”不加载视频文件，显示封面占位图并注明；real 模式行为与原来一致（`<video>` 播放服务端地址）。
- 遗留页 `FaceManagement.vue` / `VoicePrint.vue` 仍是旧样式（路由已重定向，用户进不去），后续可整体删除。
- 演示种子里没有“已过期”的采集草稿，过期状态只在样式上支持。
