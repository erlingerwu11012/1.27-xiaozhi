# One API 百炼记忆接口接入记录

日期：2026-09-29。范围：只接入 API 到现有网关并测试连通性。

## 当前结果

**记忆服务现已开通，网关实际写入、Lite 检索、读取和删除已验证通过。**

开通后复测结果：渠道 2、7 直连 Lite Search 均 HTTP 200；通过正式网关写入 1 条随机临时实体的记忆，Lite Search 在等待 3 秒后召回该条记忆，节点读取与删除均 HTTP 200，最后复查条数为 0。全部临时测试记录已清理。

- 成功写入 request_id：e81bac46-055a-9b77-971e-d1d6c3099b07。
- Lite 召回 1 条 request_id：028b1c74-a3e2-9f49-bd3f-558fcb7f11c4。
- 删除 request_id：f5e8deba-6ad0-95a0-8a21-a5887b968bef。
- 清理后条数为 0 request_id：e02895c3-72e4-9776-a6d4-e0f6f934418b。

新写入后立即 Search 的首轮结果为空，等待 3 秒再检索成功；该观察仅描述此次测试，不承诺固定的索引延迟。异步添加、PATCH 更新、画像提取和真实大模型工具调用仍未验证。设备业务尚未接入自动记忆调用。

## 开通前的结果（历史记录）

通过正式域名 `api.realecho.cn` 实测：

| 请求 | 结果 | 结论 |
| --- | --- | --- |
| 记忆列表 GET /memory_nodes | HTTP 200，临时实体为空 | 读取端点有响应 |
| 画像模板列表 GET /profile_schemas | HTTP 200 | 读取端点有响应 |
| 写入 POST /add | HTTP 403，ServiceNotOpened | 百炼服务未开通 |
| Lite 检索 POST /memory_nodes/search | HTTP 403，ServiceNotOpened | 百炼服务未开通 |
| 无令牌调用 | HTTP 401 | 认证生效 |
| 普通 One API 账号调用 | HTTP 403 | 后端凭证边界生效 |
| 浏览器 Origin 调用 | HTTP 403 | 服务端调用边界生效 |
| 原 /api/status | success=true | 原 One API 管理入口仍有响应 |

现有渠道 2、7 直接调用阿里 Lite Search 也均返回 ServiceNotOpened，排除了 Nginx 或网关转发造成该错误的可能。列表返回 200 不代表 Add/Search 已开通。

测试使用随机临时实体，不使用真实用户资料。写入被阿里拒绝，复查临时实体条数为 0；未产生测试记忆。单节点读取、更新、删除及异步任务查询已注册路由，但没有有效云端记忆可供成功验证；画像提取和真实大模型工具调用也尚未验证。

## 调用入口

Base URL：

```text
https://api.realecho.cn/bailian/api/v2/apps/memory/
```

请求头：

```text
Authorization: Bearer <现有管理员账号生成的 One API 令牌，含 sk- 前缀>
Content-Type: application/json
```

服务端从已配置的 One API 阿里渠道 2 读取上游 Key；Key 不下发到设备。记忆是独立的原生 HTTP API，不是 `/v1/chat/completions` 的模型，也没有新增渠道类型或修改模型列表。

现有网关还服务其他普通账号，而阿里原生记忆 API 存在账号范围的节点与模板访问能力。因此这条转发路由仅接受现有管理员角色的 One API 令牌，供可信设备服务后端统一使用；没有 Device ID、MAC 或设备名单限制。此处没有接入任何设备业务调用。

### 已注册的相对路径

| 方法 | 路径 |
| --- | --- |
| POST | add、add-async、memory_nodes/search |
| GET | memory_nodes、memory_nodes/{id}、events/{id} |
| PATCH、DELETE | memory_nodes/{id} |
| POST、GET | profile_schemas |
| GET、PATCH | profile_schemas/{id} |
| GET | profile_schemas/{id}/user_profile |

请求与响应按阿里原生格式转发，不改写 `user_id`，不自动决定人物，不自动上传、不自动检索、不自动重试，不添加记忆计费规则。搜索的 `plan_version` 原样转发；若要 Lite，调用方须明确传入 `"plan_version":"lite"`，阿里默认是 Pro。该转发目前不从 One API 余额扣除记忆费用；阿里账号仍按百炼规则计费。

Lite Search 请求体示例（此处仅是接口示例）：

```json
{
  "user_id": "test_entity",
  "messages": [{"role": "user", "content": "以前提过什么偏好？"}],
  "plan_version": "lite",
  "top_k": 5
}
```

## 开通前的阿里侧阻塞与排查信息（已解除）

开通前两个现有渠道的检索接口均返回 ServiceNotOpened。开通需在**现有渠道 Key 所属的阿里账号与业务空间**的百炼记忆库页面完成。以下为历史错误 request_id：

- 网关 Add：9d78b59c-773d-964a-bceb-18e99f04d11c
- 网关 Lite Search：51fd3814-f961-90b3-99ce-99f0019f9be2
- 渠道 2 直连 Lite Search：5671e398-7f58-927e-9482-cd3e2eb8a75e
- 渠道 7 直连 Lite Search：2b5cb6f5-b0f6-9e52-bf26-40964cb010ff

开通后已使用相同网关入口及现有渠道 Key 复测成功，没有安装第二个网关，没有替换 Key。控制台开通由用户操作，本次只执行网关 API 测试并更新记录。

## 部署改动与回滚

远端仅涉及百炼网关扩展：

- `/root/prjs/one-api-bailian/bailian/memory.go`：新增原生接口转发。
- `/root/prjs/one-api-bailian/bailian/memory_test.go`：网关验证。
- `/root/prjs/one-api-bailian/cmd/bailian/main.go`：只新增 `g.MemoryRoutes(r)` 一行。
- `/etc/one-api-bailian.env`：只追加 `BAILIAN_MEMORY_CHANNEL_ID=2`。
- `/etc/nginx/sites-available/api.realecho.cn`：新增上述记忆路径到 127.0.0.1:3011 的转发。
- `/opt/one-api-bailian/one-api-bailian`：更新编译后的扩展二进制。

没有数据库迁移，没有修改设备服务、习惯分析、人物记录、智控台、固件或产品需求稿。主 One API 容器未重建、未重启。仅重启百炼扩展服务并重新加载 Nginx。

验证：`go test ./bailian -run '^TestMemoryNativeForwarding$' -count=1` 通过；构建成功；`nginx -t` 通过；扩展 `/healthz` HTTP 200。

备份（服务器 root 专用，含原环境文件，不导出到本地）：

```text
/root/backups/oneapi-memory-20260929-001333
```

运行中的新二进制 SHA256：

```text
7d29706edc53fa6c371467185be3db0a21b652de3b1a2193921cc56c3f7349a6
```

## 官方参考

- [百炼长期记忆 API 目录](https://help.aliyun.com/zh/model-studio/long-term-memory-api-reference)
- [百炼记忆 API 鉴权](https://help.aliyun.com/zh/model-studio/memory/authentication)
- [错误码：403 检查所属业务空间是否已开通](https://help.aliyun.com/zh/model-studio/memory/errors)
- [计费与 Pro/Lite 参数](https://help.aliyun.com/zh/model-studio/memory/billing)

## 文件用途

`stage_gateway.py`、`publish_gateway.py` 为本次部署脚本，包含重复部署保护；不应无条件重复执行。`probe_upstream.py` 与 `probe_search_permission.py` 不写记忆；`probe_gateway.py` 在服务开通后会写入并清理一条随机实体的临时测试记忆，用于检验完整读写链路。它会内部读取现有令牌，但不会打印凭证或真实用户内容。
