# 改版映射：智能体（角色配置 · 默认角色模板 · 创建向导 · 聊天记录）

负责范围：`src/views/roleConfig.vue`、`src/views/AgentTemplateManagement.vue`、`src/views/TemplateQuickConfig.vue`、
`src/components/AwakeningWizard.vue`、`src/components/ChatHistoryDialog.vue`、`src/components/PersonaPresetPicker.vue`、
`src/components/FunctionDialog.vue`；mock：`src/mock/handlers/agent-extra.js`、`src/mock/seed/agent-extra.js`；
文案：`src/i18n/redesign/groups/agents.js`。

所有页面：去掉 `HeaderBar` / `VersionFooter`、整页背景、毛玻璃、渐变、胶囊按钮和 PNG 图标；改用 `xn-page` + `page-header` + `xn-panel` 骨架与 `--xn-*` 变量。API 模块（`src/apis/module/agent.js`）未改动，请求的 URL、方法、字段不变。

## (a) 页面与接口对照

| 原页面 / 组件 | 路由 / 入口 | 改版后的位置与变化 | 使用的后端接口 | 状态 |
|---|---|---|---|---|
| roleConfig.vue（角色配置） | `/role-config?agentId=…`（首页“配置角色”） | 返回“我的智能体”；左栏“角色设定”（称呼、人格模板、人格文字），右栏“模型与声音”（语音识别、语言模型 + 已启用功能、视觉模型、记忆模式 + 聊天记录保存方式、语音合成、音色）。页头：放弃修改 / 恢复默认模型（二次确认）/ 保存配置（无修改时禁用）；未保存时显示“需重启设备生效”提示。新增状态：无 agentId 的空状态、读取失败（getDeviceConfig 的 failCallback）带重试。隐藏的语言编码 / 交互语种输入框删除（值仍原样提交）。人格为空时内联校验 + 原提示。音色试听用 `playableUrl()`。 | GET `/agent/{id}`；PUT `/agent/{id}`；GET `/models/names?modelType=`；GET `/models/llm/names`；GET `/models/{modelId}/voices`；GET `/models/provider/plugin/names` | 已有 mock（agent.js / model.js），未改动 |
| FunctionDialog.vue（功能管理抽屉） | 角色配置“编辑功能” | 标准 el-drawer（标题 + 右上关闭 = 取消）；三栏：未选功能（勾选加入，悬停看参数说明）/ 已选功能（点名称配置参数）/ 参数配置；底部“设备工具接入”状态标签 + 刷新 + 工具列表；底部 取消 / 确定。第二栏原来误用“全选”文案，改为“全部移除”。props / 事件不变（`value`、`functions`、`allFunctions`、`agentId`；`input`、`update-functions`、`dialog-closed`）。 | GET `/agent/mcp/tools/{agentId}` | mock 已实现 |
| PersonaPresetPicker.vue | 角色配置、创建向导第 3 步 | 卡片样式改为设计规范；文案进 i18n；替换自定义文字前仍二次确认。v-model 接口不变。 | 无 | — |
| AwakeningWizard.vue（创建向导） | 首页“添加智能体”、首页无智能体时自动打开 | 自绘遮罩改为 el-dialog（标题、步骤条、底部 取消 / 上一步 / 下一步 / 创建智能体）；三步与原逻辑一致：名字与称呼 → 音色与记忆模式 → 人格（模板 / 自己写 / 更多生成方式：模组、塔罗、盲盒）。塔罗的 3D 翻牌改为点选显示；去掉终端风行号、叙事文案和“A · B”式标题。第 1 步改为表单内联校验（保留原提示）。点遮罩不再关闭（避免误触丢失输入），Esc / 右上角 = 取消。`mode="update"` 逻辑保留，但当前没有调用方。克隆音色试听：POST `/voiceClone/audio/{id}` 后用 `playableUrl()` 播放。 | POST `/agent`；PUT `/agent/{id}`；GET `/agent/{id}`（update 模式）；GET `/models/names?modelType=TTS|Memory`；GET `/models/{id}/voices`；POST `/voiceClone/audio/{id}` | mock 已实现（voiceClone 在 agent-extra.js） |
| ChatHistoryDialog.vue（聊天记录） | 首页卡片 / 列表“聊天记录” | 960px 弹窗：左侧会话列表（滚动到底或“加载更多”分页加载，每页 20），右侧消息气泡、时间分隔、语音播放 / 停止；标题带 MAC 与“演示数据”标记；底部两个下载按钮。PNG 头像换成首字 / 图标头像。新增状态：会话加载中、无记录空状态、会话 / 消息加载失败带重试。语音用 `playableUrl()`；下载用 `openDownload(url, 文件名, 文本)`，演示模式下生成写明“演示数据”的会话文本（“本会话及之前 20 个”会依次读取已加载会话的消息）。props / 事件不变（`visible`、`agentId`、`agentName`；`update:visible`）。 | GET `/agent/{agentId}/sessions?page&limit`；GET `/agent/{agentId}/chat-history/{sessionId}`；POST `/agent/audio/{audioId}`；POST `/agent/chat-history/getDownloadUrl/{agentId}/{sessionId}`（之后打开 `/agent/play/{id}`、`/agent/chat-history/download/{uuid}/current|previous`） | mock 已实现 |
| AgentTemplateManagement.vue（默认角色模板，管理员） | `/agent-template-management` | 页头“创建模板”；工具栏搜索 + 已选数量 + 批量删除；表格：勾选（表头全选 / 半选）、序号、模板名称（点击编辑）、人格设定摘要、编辑 / 删除；分页（Vue 3 写法的 `v-model:current-page` 改为 Vue 2 的 `:current-page`）。空状态（无模板 / 搜索无结果）与失败状态。删除、批量删除二次确认。搜索由“只过滤当前页”改为从第 1 页按 `agentName` 参数查询（原请求本来就带此参数）。删光最后一页时自动回到上一页。 | GET `/agent/template/page?page&limit&agentName`；DELETE `/agent/template/{id}`；POST `/agent/template/batch-remove`（body 为 id 数组） | mock 已实现 |
| TemplateQuickConfig.vue（新建 / 编辑模板，管理员） | `/template-quick-config[?templateId=]` | 返回“默认角色模板”；表单：模板名称（必填、≤64 字）、人格设定（≤2000 字）；底部 取消 / 恢复上次保存（二次确认）/ 保存模板（防重复提交）。编辑时读取失败显示失败状态。同一路由切换 templateId 时重新加载。新建保存成功后回列表，编辑保存后留在本页（同原逻辑）。 | GET `/agent/template/{templateId}`；GET `/agent/template`（计算排序号）；POST `/agent/template`；PUT `/agent/template` | mock 已实现 |
| —（其他组的调用方） | VoicePrintDialog / VoicePrint / UnifiedUserManagement | 页面不归本组；只提供接口 mock，且导出 `ownVoicePrints()` / `voicePrintRow()` 供 `handlers/userIdentity.js` 复用同一份声纹数据 | POST/PUT `/agent/voice-print`；GET `/agent/voice-print/list/{agentId}`；DELETE `/agent/voice-print/{id}`；GET `/agent/{agentId}/chat-history/user`；GET `/agent/{audioId}/chat-history/audio`；POST `/agent/audio/{audioId}` | mock 已实现，已在“人员身份”页验证录入声纹 |

agent-extra.js 共 20 个接口：模板 7、会话 / 聊天记录 / 语音 / 下载 6、MCP 2、声纹 4、`/voiceClone/audio/{id}` 1。

### 演示数据（seed/agent-extra.js）

- `agentChats`：demo-a-1 26 个会话（超过一页，演示滚动加载；文字 + 语音）、demo-a-2 6 个（只上报文字）、demo-a-4 2 个（英文）、demo-a-9 3 个（管理员）。demo-a-3 为“无记忆”，首页本来就禁用聊天记录入口，故无数据。最近会话时间与首页“最近对话”一致。
- `agentTemplates`：12 个“（演示）”模板，覆盖两页分页。
- `voicePrints`：demo-a-1 下 2 条。
- 浏览器里已有旧演示数据库时，`ensure()` 按需补上以上集合，不需要重置演示数据。
- 播放 / 下载凭证只存在内存里；音频为本地生成的提示音，下载为本地生成的文本，均不访问网络。

## (b) 待确认（联调时请后端确认）

1. **业务错误不进 success 回调**：`httpRequest.js` 在 `code !== 0` 时只弹错误提示、不调用 success 回调，而 `agent.js` 的列表类方法没有 failCallback 参数。为了让“加载失败”状态可见，聊天记录、模板列表、模板详情使用了 10 秒的超时兜底（期间按钮 / 列表显示加载中）。角色配置使用了 `getDeviceConfig` 自带的 failCallback，立即显示失败状态。建议后续给 API 模块补 failCallback。
2. `GET /agent/template` 的权限：mock 允许普通用户读取（原系统新建智能体时可能使用），其余模板接口（page / 详情 / 增删改 / 批量删除）要求管理员。请确认。
3. `GET /agent/template/page` 是否支持 `agentName` 模糊查询、返回字段是否为 `{ list, total }`（页面按此读取）。
4. `POST/PUT /agent/template` 的返回 `data`：页面只读 `code`，mock 返回 `null`。名称 ≤64 字、人格 ≤2000 字的校验是前端假设。
5. `GET /agent/{agentId}/sessions` 每项字段假设为 `{ sessionId, createdAt, chatCount }`；是否倒序（新→旧）。
6. `GET /agent/{agentId}/chat-history/{sessionId}` 每项假设为 `{ chatType(1 用户 / 2 智能体), content, audioId, macAddress, createdAt }`，按时间正序；mock 额外带 `id`。真实接口若没有 `id`，组件已用下标兜底作为 key。`chatHistoryConf = 1` 时是否不返回 `audioId`。
7. `GET /agent/{id}/chat-history/audio` 的路径参数实际是 **audioId**（VoicePrintDialog 这样调用），返回该语音的文字。请确认路径语义。
8. `GET /agent/{id}/chat-history/user`：mock 返回该智能体最近 50 条“带语音的用户消息” `[{ audioId, content }]`。
9. 声纹：`POST /agent/voice-print` 由“人员身份”页调用时带 `userId`（成员 id），mock 原样保存，并由 userIdentity mock 归到对应成员；真实后端是否自动绑定请确认。删除声纹时 mock 不改成员数据（由 userIdentity mock 的同步逻辑剔除失效 id）。
10. `GET /agent/mcp/tools/{agentId}` 返回字符串数组；mock 只给 demo-a-1 返回 3 个设备工具名（显示“已连接”），其他为空（“未连接”）。`GET /agent/mcp/address/{agentId}` 页面没有使用，mock 返回 `.invalid` 占位地址。
11. 下载接口 `/agent/chat-history/download/{uuid}/current|previous` 的真实文件格式未知；演示文本格式为“[时间] 说话人：内容”。
12. `POST /voiceClone/audio/{id}` 若与音色克隆组的 mock 重复注册，按路由表规则先注册者生效；两者返回同为字符串 id。

## (c) 未完成 / 说明

- 角色配置里“恢复默认模型”会把称呼恢复为原代码中的默认值“主人”、设备名为“小智”（原逻辑，未改）。
- `AwakeningWizard` 的 `mode="update"`（新用户唤醒）保留，但仓库内没有调用方；按“不新增功能”原则，没有在角色配置页加入口。
- 记忆模式下拉的选项名称来自模型数据（例如“长期记忆 · 回响现实官方服务”），由模型配置组的 seed 决定。
- 音色试听：`/models/{id}/voices` 的 mock 返回空 `voiceDemo`，所以系统音色不显示试听按钮（与真实数据有关，未伪造试听地址）。
- 错误场景下角色配置仍会出现外壳（余额、用户信息）各自的错误提示，不属于本组页面。
