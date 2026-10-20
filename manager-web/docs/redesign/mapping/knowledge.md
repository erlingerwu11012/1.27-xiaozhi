# 改版映射：知识库、记忆、习惯（knowledge 组）

## (a) 页面 / 组件对照

| 原页面 / 组件 | 路由 | 新位置 / 改动 | 后端接口（METHOD path） | 状态 |
|---|---|---|---|---|
| KnowledgeBaseManagement.vue | /knowledge-base-management（所有登录用户） | 去掉 HeaderBar / VersionFooter / 毛玻璃背景；改为 page-header（主操作“新建知识库”）+ 搜索工具栏（勾选后出现“删除所选”）+ 表格面板 + el-pagination；名称可点击进入文档页；新增加载失败（重试）、无数据、无搜索结果状态；删空最后一页后回到上一页 | GET /datasets?page&page_size&name；POST /datasets；PUT /datasets/{datasetId}（编辑与启用开关）；DELETE /datasets/{datasetId}；DELETE /datasets/batch?ids= | 完成 |
| KnowledgeBaseDialog.vue | （弹窗） | 标签置顶表单、统一弹窗样式；props / submit / update:visible 不变；“RAG模型”改称“检索服务”并加说明；按钮“创建知识库 / 保存修改” | GET /datasets/rag-models（model.js 的 getRAGModels） | 完成 |
| KnowledgeFileUpload.vue | /knowledge-file-upload?datasetId&knowledgeBaseName | 子页面：page-header 带返回知识库；操作“召回测试”“上传文档”；文档表（类型标识、状态 xn-tag、切片数、解析/查看切片/删除）；上传弹窗（拖拽 / 选择、已选列表、演示说明）；切片弹窗改为列表 + el-pagination；召回测试弹窗（问题 + 执行、结果列表带相似度和来源文档、“演示结果”标记）；缺少 datasetId 时显示引导返回列表而不是空请求。轮询、解析、批量上传/删除、切片计数等脚本逻辑保留；硬编码中文提示改为 i18n | GET /datasets/{id}/documents?page&page_size&name；POST /datasets/{id}/documents（FormData file）；POST /datasets/{id}/chunks {document_ids}（解析）；DELETE /datasets/{id}/documents/{docId}；GET /datasets/{id}/documents/{docId}/chunks?page&page_size&keywords；POST /datasets/{id}/retrieval-test {question} | 完成 |
| MemoryManagement.vue | /memory-management（管理员，路由守卫） | page-header + 设备 ID 筛选工具栏（当前筛选以标签显示，可一键清除）+ 表格 + 分页；类别标签改 xn-tag；“清空该设备记忆”只在已生效的筛选下出现（原来按输入框内容判断，可能清空到未生效的 ID，已修正）；加载失败状态 | GET /admin/memory?page&limit&device_id；DELETE /admin/memory/{id}；DELETE /admin/memory/device/{device_id}（前缀 VUE_APP_PYTHON_API_URL） | 完成 |
| HabitManagement.vue | /habit-management（管理员，路由守卫） | page-header（主操作“添加习惯”）+ 表格面板；同步状态 xn-tag 按状态着色，已删除行置灰划线；新建/编辑共用弹窗（标题、按钮按模式区分；编辑成功提示不再显示“创建成功”）；设备与接收人选项加载失败提示；15 秒自动刷新保留（刷新时不再闪遮罩）；硬编码中文改 i18n | GET /habits?enabledOnly=false；GET /habits/options；POST /habits；PUT /habits/{id}；DELETE /habits/{id}（软删除） | 完成 |
| MemoryExtractConfig.vue | /memory-extract-config（管理员，路由守卫） | page-header + 面板表单；“API 地址 / API Key”改称“服务地址 / 访问密钥”；新增“恢复已保存的设置”（重新读取）；修正读取参数的取值路径（原代码读 res.data.list，而 admin.js 回调的是完整响应，导致从未读到参数、保存时全部跳过却提示成功） | GET /admin/params/page?paramCode=memory_extract；PUT /admin/params | 完成（接口 mock 由 admin 组提供） |
| HabitAnalyzeConfig.vue | /habit-analyze-config（meta.adminOnly，外壳显示无权限） | 同上 | GET /admin/params/page?paramCode=habit_analyze；PUT /admin/params | 完成（接口 mock 由 admin 组提供） |

Mock：`src/mock/handlers/knowledgeBase.js`（12 条）、`memory.js`（3 条）、`habit.js`（5 条），演示数据 `src/mock/seed/knowledge.js`；旧的浏览器演示库缺少这些字段时由各 handler 的 ensure 补齐。

演示行为：上传只记录文件名、大小、类型，文档初始“未开始”；点“解析”后“处理中”，之后约两次列表刷新（页面每 5 秒轮询）变为“已完成”并生成写明“演示切片”的示例文字；0 字节文件解析失败。召回测试按问题与切片的字词重合度打分（不是向量检索），结果标“演示结果”。习惯新建/修改/删除后先“待同步”，约两次刷新后“已同步 / 已停止提醒”。记忆内容均以“（演示）”开头。`scenario.data=empty` 时列表接口返回空。

## (b) 待确认 / pending questions for backend integration

1. `GET /datasets` 是否按当前用户划分？管理员能否看到所有人的知识库？mock 按创建者划分。
2. 文档列表是否返回 `progress`、失败原因等字段？页面目前只读 `parseStatusCode`（0 未开始 / 1 处理中 / 2 已取消 / 3 已完成 / 4 失败）；“失败”状态下原逻辑禁用“解析”，无法重试，是否需要放开。
3. `POST /datasets/{id}/documents` 的大小上限：前端校验 10MB；提示里原写“单次不超过 32 个文件”但前端从未校验，已从提示中去掉 32 的说法，请确认后端限制。
4. 召回测试响应 `chunks[]` 是否带 `document_name` / `document_keyword`（页面有则显示来源文档）；是否有 `similarity_threshold`、`top_k` 等参数（原页面只传 question）。
5. 已停用（status=0）的知识库能否做召回测试、能否被智能体使用。
6. `GET /datasets/rag-models` 的数据来源：mock 读模型配置中 modelType=RAG 的启用模型，没有时给一个“默认知识库检索（演示）”。
7. `/admin/memory?device_id=` 是完整匹配还是模糊匹配；device_id 是设备记录 id 还是 MAC（mock 用 demo-d-* 并完整匹配，不区分大小写）。
8. `/admin/memory/*` 走 Python 服务，是否同样认 Bearer token 与管理员身份（mock 用 requireAdmin）。
9. `/habits*` 是否要求管理员（页面仅管理员可进，mock 未要求，按当前账号的设备划分）；`/habits/options` 的 people 来自哪个人员目录（mock 用独立演示名单 demo-p-*，与人员身份模块无关联）。
10. 删除习惯后 `syncState` 的变化（mock：pending → synced，显示“已停止提醒”）；没有设备的旧记录删除后直接 synced。
11. MemoryManagement / HabitManagement 的 API 模块没有 `.fail()` 回调，业务错误时页面回调不执行，只由全局提示报错；页面现在在这种情况下保持加载状态、不显示“没有数据”。如需页面内失败状态，需要 API 模块补 fail 回调（本次未改 API 模块）。
12. 两个配置页保存时，若某个参数在系统参数表里不存在（id 为空），原逻辑：记忆提取跳过、习惯分析仍提交无 id 的更新——行为保留，需后端确认。

## (c) 未完成 / 其他

- 无未完成页面。`async-validator` 的控制台 warning 来自 Element 表单校验失败的正常输出（未通过校验时）。
- 共享文件改动：`src/mock/handlers/index.js` 末尾追加三行 import。
