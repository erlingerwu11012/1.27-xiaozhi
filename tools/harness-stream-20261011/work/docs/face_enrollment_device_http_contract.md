# 设备人脸采集 HTTP 契约（固件接入冻结）

**Guided Burst V2-only**：MCP `face_enrollment.protocol_version = 2` 且 `guided_burst_v1 = true`。
`session_url` 为 `/mcp/face-enrollment/session`（singular）；`session_timeout_seconds = 240`。
V1 `/sessions`、`/sessions/{id}/frames`、幂等 `DELETE /sessions/{id}` 已移除（无回退）。

固件**必须**以 `ok` / `error_code` / `retryable` 判断状态；V2 错误体**不得**含 `message`。

详见网关路由：`POST /session`、`POST /assess/{id}`、`POST /capture/{id}`、`DELETE /cancel/{id}`；
上传 token scope = `enrollment_upload_v2`，仅 `X-Enrollment-Token` header（禁止 query）。

## Guided Burst V2（默认，三姿态）

Capability 静态字段不变：`protocol_version=2`、`guided_burst_v1=true`、`required_frames=3`、`max_frames=3`、`session_timeout_seconds=240`。

未传 `capture_mode` 的 create 仍为 front→left→right，`accepted_count=3` 才 `DRAFT_READY`。

## front_only_v1（显式协商，本轮默认关闭）

服务端**不会**把 capability 里的 `required_frames` 改成 1。旧固件继续按 3 处理。

仅当账号+设备在允许名单且开关打开时，capability **额外**附加：

```json
"supported_capture_modes": ["guided_burst_v1", "front_only_v1"]
```

新固件仅在看到该字段含 `front_only_v1` 时，create JSON 请求：

```json
{ "capture_mode": "front_only_v1" }
```

客户端不得指定 `required_frames` / `max_frames`（网关忽略）。非法模式 → `invalid_capture_mode`；未允许设备 → `capture_mode_not_allowed`。

成功 create（新模式，对设备重建）示例：

```json
{
  "ok": true,
  "session_id": "...",
  "assess_url": "https://.../mcp/face-enrollment/assess/{id}",
  "capture_url": "https://.../mcp/face-enrollment/capture/{id}",
  "cancel_url": "https://.../mcp/face-enrollment/cancel/{id}",
  "upload_token": "...",
  "expires_at": 1234567890,
  "required_frames": 1,
  "max_frames": 1,
  "capture_mode": "front_only_v1"
}
```

完成响应（assess/capture 对设备仍只有四字段）：

```json
{
  "ok": true,
  "session_id": "...",
  "guidance_code": "DRAFT_READY",
  "accepted_count": 1,
  "draft_ready": true
}
```

规则：

- 每次 capture 仍固定 `candidate_0` / `candidate_1` / `candidate_2` 三张候选。
- 只允许 `pose=front`；`left`/`right` → `invalid_pose`，不改变会话进度。
- 一张合格即 `DRAFT_READY`，不再进入 `CAPTURE_LEFT` / `CAPTURE_RIGHT`。
- 会话 TTL 仍为 240 秒。
- 旧三姿态会话的 `accepted_count=1` **不得**被当成完成。

以下为历史 V1 契约摘录（已停用，仅供对照）：

## 鉴权（V1 已停用）

| 头 | 说明 |
|---|---|
| `Authorization: Bearer <AuthManager配对token>` | 创建设备会话 / 取消 |
| `Device-Id` | 必填，与 token 绑定 |
| `Client-Id` | 必填，与 token 绑定 |
| `X-Enrollment-Token` | 上传帧必填；绑定 `session_id+device_id+account_id+exp+scope=enrollment_upload` |

账号由服务端配置注入，客户端不可指定。

## 成功响应（V1 已停用）

所有成功响应包含 `"ok": true`。

### POST `/mcp/face-enrollment/sessions`（已移除）

```json
{
  "ok": true,
  "session_id": "opaque-id",
  "upload_url": "https://host/mcp/face-enrollment/sessions/{id}/frames",
  "cancel_url": "https://host/mcp/face-enrollment/sessions/{id}",
  "upload_token": "short-lived",
  "expires_at": 1234567890,
  "required_frames": 3,
  "max_frames": 5
}
```

### POST `/mcp/face-enrollment/sessions/{id}/frames`（已移除）

`Content-Type: multipart/form-data`，字段名 `image` / `file` / `photo`，JPEG。

```json
{
  "ok": true,
  "session_id": "...",
  "accepted_count": 1,
  "required_frames": 3,
  "max_frames": 5,
  "status": "collecting",
  "draft_ready": false
}
```

`status` ∈ `collecting` | `draft_ready`。达到 3 张时 `draft_ready=true`。

成功响应**不得**包含图片、embedding、账号、token、姓名。

### DELETE `/mcp/face-enrollment/sessions/{id}`

```json
{
  "ok": true,
  "session_id": "...",
  "status": "cancelled"
}
```

## 失败响应

```json
{
  "ok": false,
  "error_code": "stable_machine_code",
  "retryable": false,
  "message": "仅供用户展示的简短说明"
}
```

## error_code 与 HTTP

| error_code | HTTP | retryable（默认） |
|---|---|---|
| auth_invalid | 401 | false |
| upload_token_invalid | 403 | false |
| upload_token_expired | 403 | false |
| device_mismatch | 403 | false |
| account_mismatch | 403 | false |
| session_not_found | 404 | false |
| session_expired | 409 | false |
| session_cancelled | 409 | false |
| session_already_consumed | 409 | false |
| enrollment_already_active | 409 | false |
| enrollment_busy | 409 | true |
| payload_too_large | 413 | false |
| invalid_content_type | 422 | false |
| invalid_jpeg | 422 | true |
| image_dimensions_invalid | 422 | true |
| no_face | 422 | true |
| multiple_faces | 422 | true |
| face_quality_low | 422 | true* |
| duplicate_frame | 422 | true |
| upload_limit_reached | 422 | false |
| account_draft_quota_exceeded | 429 | true |
| rate_limited | 429 | true |
| enrollment_disabled | 503 | false |
| capability_invalid | 503 | false |
| internal_error | 500 | true |

\* 连续质量失败达阈值后 `face_quality_low` 的 `retryable=false`，固件须重新创建 session。

## 资源限制（摘要）

- JPEG 单帧 ≤ 307200 字节；multipart 整体 ≤ 307200+64KiB
- 网关：Content-Length 预检 + 流式累计上限
- face-api：二次 Content-Length / 流式读上限；校验 magic、宽高、像素数后才检测
- 同 Device-Id：10 分钟内最多 5 次创建
- 同 account：10 分钟内最多 20 次创建
- 同 session：质量失败累计 8 次则中止（retryable=false）
