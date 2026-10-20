# xiaozhi-server 数据库审计报告

## 1. 审计结论

**xiaozhi-server 不直接使用任何数据库。**

- 未使用 aiomysql、pymysql 或其他 MySQL 驱动
- 未使用 SQLite、Redis 等本地/远程存储
- 所有持久化数据通过 **HTTP API** 提交给 **manager-api（Java 后端）**，由 manager-api 写入 MySQL

## 2. 数据流与间接依赖表

xiaozhi-server 通过 `config/manage_api_client.py` 调用以下接口：

| 接口 | 用途 | manager-api 写入的表 |
|------|------|----------------------|
| POST /config/server-base | 获取服务器配置 | 无写入（读取 sys_params 等） |
| POST /config/agent-models | 获取智能体模型配置 | 无写入（读取 ai_agent、ai_device 等） |
| PUT /agent/saveMemory/{macAddress} | 保存短期记忆 | 更新 ai_agent.summary_memory |
| POST /agent/chat-history/report | 上报对话/语音记录 | ai_agent_chat_history、ai_agent_chat_audio |

因此，**xiaozhi-server 正常运行依赖的 MySQL 表均由 manager-api 的 Liquibase 变更脚本创建**，不涉及 xiaozhi-server 自行建表。

## 3. 本地缓存说明

xiaozhi-server 使用 `core/utils/cache/manager.py` 的 **内存缓存**（`Dict` + `OrderedDict`）：

- 配置、IP 信息、意图、天气、声纹等
- **不落盘**，重启即清空
- 与数据库无关

## 4. 依赖表清单（manager-api 创建）

以下为 xiaozhi-server 间接依赖的核心表（由 manager-api 初始化）：

| 表名 | 用途 |
|------|------|
| ai_agent | 智能体配置、短期记忆 |
| ai_device | 设备信息、绑定关系 |
| ai_agent_chat_history | 对话文本记录 |
| ai_agent_chat_audio | 对话音频记录 |
| ai_agent_template | 默认智能体模板 |
| ai_model_provider | 模型/插件配置 |
| ai_tts_voice | 音色配置 |
| sys_params | 系统参数 |
| sys_user | 用户（智控台） |
| sys_user_token | 用户 Token |

完整建表逻辑见：`manager-api/src/main/resources/db/changelog/`。

## 5. 验证表是否已创建

### 方式一：MySQL 客户端

```bash
docker exec -it xiaozhi-esp32-server-db mysql -uroot -p123456 xiaozhi_esp32_server -e "
SELECT TABLE_NAME FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'xiaozhi_esp32_server'
ORDER BY TABLE_NAME;
"
```

### 方式二：检查关键表存在

```bash
docker exec -it xiaozhi-esp32-server-db mysql -uroot -p123456 xiaozhi_esp32_server -e "
SELECT TABLE_NAME FROM information_schema.TABLES
WHERE TABLE_SCHEMA = 'xiaozhi_esp32_server'
AND TABLE_NAME IN (
  'ai_agent', 'ai_device', 'ai_agent_chat_history', 'ai_agent_chat_audio',
  'ai_agent_template', 'sys_params', 'sys_user'
);
"
```

若上述表均存在，则 xiaozhi-server 所需表已就绪。

### 方式三：确认 Liquibase 已执行

manager-api 启动时会自动执行 Liquibase，建表日志类似：

```
Liquibase: Successfully acquired change log lock
Liquibase: Successfully released change log lock
```

若 manager-api 曾成功启动过，表应已创建。

## 6. 补漏 SQL

**xiaozhi-server 本身无需任何建表 SQL。**

若发现 manager-api 表缺失（例如新部署、数据库被重置），应：

1. **优先方案**：重启 manager-api，由 Liquibase 自动执行全部 changelog
2. **手动方案**：按需执行 `manager-api/src/main/resources/db/changelog/*.sql` 中的脚本（建议按 changelog 顺序）

## 7. 与其他组件的区别

| 组件 | 是否直连 MySQL | 建表职责 |
|------|----------------|----------|
| xiaozhi-server | 否 | 无 |
| manager-api | 是 | Liquibase 创建 ai_*、sys_* 等 |
| xiaozhi_mcp_gateway | 是 | 需手动创建 sys_reminders（见 mcp_gateway/scripts/init_sys_reminders.sql） |
