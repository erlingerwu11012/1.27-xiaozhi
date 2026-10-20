# 系统管理（admin 分组）改版对照

范围：用户管理、模型配置（含音色管理）、参数管理、字典管理、字段管理（供应器）、服务端管理。
所有页面都去掉了 `HeaderBar` / `version-footer`、整页渐变背景、毛玻璃、药丸按钮与自绘分页，改为 `xn-page` 骨架 + `el-table` + `el-pagination`；
批量操作统一放在工具栏右侧，勾选后才出现（“已选 N 项” + 操作按钮）；弹窗统一为标准 `el-dialog`（标题 + 底部按钮），表单一律 `label-position="top"`。
API 模块（`src/apis/module/*`）未改动；URL、方法、请求字段、回调读取方式均保持原样。

## (a) 对照表

| 原页面 / 组件 | 路由 | 改版后 | 后端接口 | 状态 |
|---|---|---|---|---|
| `views/UserManagement.vue` | `/user-management` | 工具栏搜索 + 表格（账号/手机号、用户 ID、设备数、注册时间、状态标签、操作）；表头勾选当前页；批量启用 / 禁用 / 删除；重置密码结果改用 `ViewPasswordDialog` 显示（原来用 `$alert` + `dangerouslyUseHTMLString`，已去掉） | GET `/admin/users`；DELETE `/admin/users/{id}`；PUT `/admin/users/{id}`（重置密码）；PUT `/admin/users/changeStatus/{status}`（在 handlers/user.js） | 完成 |
| `components/ViewPasswordDialog.vue` | — | 标准弹窗：说明 + 只读密码 + 复制；mock 模式显示“演示密码，未保存”；剪贴板不可用时给出手动复制提示；不再直接改写 prop | — | 完成 |
| `views/ModelConfig.vue` | `/model-config` | 左侧类别列表（≤1100px 时变为横向标签）+ 右侧工具栏 / 表格；“是否默认”开关改为“默认”标签或“设为默认”按钮（仍调用同一接口）；新增按钮移到页头 | GET `/models/list`；PUT `/models/enable/{id}/{status}`；PUT `/models/default/{id}`；DELETE `/models/{id}`；POST `/models/{type}/{provideCode}`（新增 / 复制）；PUT `/models/{type}/{provideCode}/{id}` | 完成 |
| `components/AddModelDialog.vue` | — | 两段式表单（模型信息 / 调用信息），未选供应器时给出提示；mock 模式提示密钥不保存 | GET `/models/{type}/provideTypes` | 完成 |
| `components/ModelEditDialog.vue` | — | 同上；密钥字段下方说明“只显示掩码，不修改保持原值”；复制模式说明 | GET `/models/{id}`；GET `/models/{type}/provideTypes` | 完成 |
| `components/TtsModel.vue` | — | 弹窗内工具栏（搜索音色、批量删除、新增音色）+ 表格行内编辑；新增“取消”编辑（新行直接移除，已有行还原）；去掉自绘滚动条（滚动方法保留，容器原生滚动）；声音克隆类模型显示参考音频列 | GET `/ttsVoice`；POST `/ttsVoice`；PUT `/ttsVoice/{id}`；POST `/ttsVoice/delete` | 完成 |
| `components/AudioPlayer.vue` | — | 紧凑播放条；地址经 `playableUrl()`（mock 下为浏览器内生成的提示音）；拖动进度改用 ref（原代码 `querySelector('.progress-bar')` 在多个播放器时会拿错元素）；音量浮层改为相对定位 | — | 完成 |
| `views/ParamsManagement.vue` | `/params-management` | 页头“新增参数”；表格增加“值类型”列；密钥类参数掩码 + 查看 / 隐藏；删除最后一页全部数据后自动回到上一页 | GET `/admin/params/page`；POST `/admin/params`；PUT `/admin/params`；POST `/admin/params/delete` | 完成 |
| `components/ParamDialog.vue` | — | 标准弹窗 + 校验 + 重置（恢复为打开时的内容）+ 取消 / 保存；`custom-class` 改为 `xn-param-dialog`（VoicePrintDialog 仍用全局 `.custom-param-dialog` 样式，避免互相影响）；保存按钮 8 秒兜底复位 | — | 完成 |
| `views/DictManagement.vue` | `/dict-management` | 左右两栏：字典类型面板（勾选批量删除、新增、编辑）+ 字典数据面板（搜索、批量删除、分页）；刷新后保留当前选中的类型 | GET `/admin/dict/type/page`；POST `/admin/dict/type/save`；PUT `/admin/dict/type/update`；POST `/admin/dict/type/delete`；GET `/admin/dict/data/page`；POST `/admin/dict/data/save`；PUT `/admin/dict/data/update`；POST `/admin/dict/data/delete` | 完成 |
| `components/DictTypeDialog.vue`、`DictDataDialog.vue` | — | 标准弹窗 + 重置 / 取消 / 保存；修复 `title` 默认值用箭头函数导致 `this` 为空的问题 | — | 完成 |
| `views/ProviderManagement.vue` | `/provider-management` | 工具栏：类别下拉（替代原来两个下拉菜单）+ 名称搜索；字段列显示“N 个字段 + 字段名摘要”，悬停看明细与“敏感”标记；传给弹窗的类别改为已翻译的列表（原来传 `labelKey`，下拉选项无文字） | GET `/models/provider`；POST `/models/provider`；PUT `/models/provider`；POST `/models/provider/delete` | 完成 |
| `components/ProviderDialog.vue` | — | 两列基本信息 + 字段表格（添加字段、勾选批量删除、行内编辑 / 完成）；原硬编码“已取消删除”改为 i18n | — | 完成 |
| `views/ServerSideManager.vue` | `/server-side-management` | 页头“刷新”；mock 模式顶部说明“只返回模拟结果”；新增“本次操作结果”列（发送中 / 已发送 / 失败 + 时间 + “演示结果”标记，只存在于页面内存）；确认框带目标地址；去掉原来无任何批量操作的勾选列 | GET `/admin/server/server-list`；POST `/admin/server/emit-action` | 完成 |

Mock（共 35 个接口）：`src/mock/handlers/admin.js`（9，新建）、`handlers/model.js`（+12，保留原 4 个只读接口不变）、`handlers/dict.js`（+10，保留按类型读取）、`handlers/timbre.js`（4，新建）；演示数据 `src/mock/seed/admin.js`（新建，`ensureAdminData(db)` 幂等合并，旧的浏览器演示库也会补齐）。
所有管理接口先 `requireAdmin`；`/models/names`、`/models/llm/names`、`/models/{id}/voices`、`/models/provider/plugin/names`、`/admin/dict/data/type/{type}` 保持对普通用户开放。列表接口在 `scenario.data === 'empty'` 时返回空。

密钥与密码：
- 模型调用配置、参数、供应器字段默认值中的密钥类字段（含 api_key / secret / token / password / private_key / signature_key / access_key）只保存占位值 `sk-demo-****` / `demo-****`。带 `*` 的掩码值视为“未修改”沿用旧值，新输入的任何值都替换为占位值，不落库。占位值使用 `*` 而不是 `•`，因为 ModelEditDialog 的原逻辑以 `*` 判断掩码（聚焦时清空）。
- 重置密码返回 `demo-xxxxxx`，只在内存生成、直接返回给页面，不保存。
- 演示地址统一用保留域名 `*.demo.example`；`memory_extract.base_url` / `habit_analyze.base_url` 沿用页面自带默认值 `https://api.deepseek.com/v1`（只是文本，不会被请求）。

## (b) 待确认 / pending questions for backend integration

1. **用户列表 `mobile` 字段**：mock 返回 `mobile = 手机号 || 账号名`（推测后端 AdminPageUserVO.mobile 取自 username）。列名改为“账号 / 手机号”。请确认后端返回内容。
2. **`user.invalidUserId` 校验**：原代码 `isNaN(id)` 要求用户 ID 为数字。演示账号 ID 为 `demo-u-xxxx`，因此仅在 mock 构建放宽为“非空”（`IS_MOCK`），real 构建保持数字校验。
3. **业务错误不回调**：`RequestService` 对 `code !== 0` 只弹出错误、不调用 success 回调，各 API 模块也没有传 fail 回调。页面无法得知加载失败，因此列表页加了 8 秒兜底：仍在加载则显示失败状态（`xn-empty error` + 重试）；批量删除中未回调的请求 8 秒后按失败计。联调时建议 API 模块补 `.fail()`，届时可去掉兜底。
4. 新增模型时 AddModelDialog 隐藏的“设为默认”默认是开启的（`isDefault: 1`）。mock 不因此改变本类别已有的默认模型，只有该类别还没有默认模型时才设为默认。后端实际行为待确认。
5. 删除模型：mock 拒绝删除默认模型、拒绝删除仍被智能体引用的模型；删除 TTS 模型时同时删除其音色。后端规则待确认（含 Memory / Intent 配置里 `llm` 字段引用 LLM 的情况，mock 未检查）。
6. 删除音色：mock 拒绝删除仍被智能体使用的音色。后端规则待确认。
7. 删除供应器：mock 拒绝删除仍被模型（`configJson.type`）或智能体插件引用的供应器；修改已被引用供应器的类别 / 编码也会被拒绝。后端规则待确认。
8. 参数值校验：mock 对 number / boolean / json 做格式校验，对重复编码报错。后端是否校验待确认。
9. 字典：删除字典类型会连带删除其数据（mock 行为）；重复的类型编码 / 同类型下重复的字典值会报错。后端行为待确认。
10. 字段管理的类别列表沿用原页面（ASR、TTS、LLM、Intent、Memory、VAD、Plugin、RAG），**不含 VLLM**，但模型配置有“视觉模型”类别。演示数据里有 VLLM 供应器（类别列显示原始值 VLLM），无法在字段管理里新建 VLLM 供应器。是否补上 VLLM 待产品确认。
11. `/admin/server/server-list` 在 mock 中取自参数 `server.websocket`（分号分隔），与后端实现推测一致，待确认。emit-action 的真实返回值（是否有 data）待确认；页面只读 `code`。
12. 原字典页把右侧“字典标签”搜索词同时传给了左侧类型列表的 `dictName`，搜索后新增类型会导致左侧列表被过滤为空；改版后类型列表不再带该过滤条件（类型列表一次取 100 条，与原来一致）。

## (c) 未完成 / 需要其他同学处理

- `views/MemoryExtractConfig.vue`（其他分组）读取参数用的是 `res.data.list`，而 `getParamsList` 回调拿到的是完整响应（列表在 `res.data.data.list`，HabitAnalyzeConfig 读法正确）。因此 MemoryExtractConfig 在 mock 与真实接口下都读不到参数值。mock 按 ParamsManagement / HabitAnalyzeConfig 的读法返回，没有为它改响应结构。
- `views/DeviceManagement.vue`（参考实现）表头勾选框用的是非作用域 `slot="header"`，Element 不会在数据变化后重新渲染这个表头，`:disabled` / 选中态会停在首次渲染的值。本分组页面已改为 `slot-scope` 写法，建议参考实现同步修改。
- 开发构建下 el-form 校验失败时，async-validator 会在控制台输出 `async-validator: [... is required]` 警告（Element 依赖的行为，生产构建不输出）。
- 字段管理、模型弹窗里供应器字段的占位文字（`请输入${key}`）为原代码硬编码中文，未做 i18n。
