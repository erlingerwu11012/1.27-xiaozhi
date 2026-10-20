# 人脸录入 Guided Burst V2：服务端适配交接

本文件只定义与固件 `FaceEnrollmentManager` / `FaceEnrollmentClient` 的
交接契约。**本次固件提交没有修改服务端。**

## 一、能力下发与兼容开关

只有以下两个条件同时满足，固件才会走 V2；否则保持现有单张上传 V1：

```json
{
  "face_enrollment": {
    "protocol_version": 2,
    "guided_burst_v1": true,
    "session_url": "https://<public-host>/mcp/face-enrollment/session",
    "session_timeout_seconds": 240,
    "required_frames": 3,
    "max_frames": 3,
    "max_frame_bytes": 307200
  }
}
```

- `protocol_version=2` 但遗漏或设为 `guided_burst_v1=false`：固件拒绝该能力，不会猜测启用 V2。
- V2 `session_timeout_seconds` 必须在 `240..600`；创建后 `expires_at` 至少还要有 240 秒。
- V2 `required_frames` 必须是 `3`：最终只保留正脸、左脸、右脸各一张最佳图。
- 所有 URL 都必须是 `https://`，不可为 localhost/内网，且 host 必须等于设备主 `wss://` URL 的 host。

## 二、创建 V2 session

设备向 `session_url` 发 `POST {}`，使用既有 `Authorization`、`Device-Id`、`Client-Id`。成功响应必须为：

```json
{
  "ok": true,
  "session_id": "opaque-short-id",
  "assess_url": "https://<public-host>/mcp/face-enrollment/assess/...",
  "capture_url": "https://<public-host>/mcp/face-enrollment/capture/...",
  "cancel_url": "https://<public-host>/mcp/face-enrollment/cancel/...",
  "upload_token": "short-lived-opaque-token",
  "expires_at": 1780000000,
  "required_frames": 3,
  "max_frames": 3
}
```

`session_id`、URL 和 token 只存在设备内存；请勿要求设备持久化它们。V2 失败、取消、超时、姿态失败后，设备会异步 `DELETE cancel_url`，并携带同一个 `X-Enrollment-Token`。

## 三、对齐与姿态批量接口

每次 V2 请求均附带：

```text
Authorization: Bearer <existing-pairing-token>
Device-Id: <device-mac>
Client-Id: <device-uuid>
X-Enrollment-Token: <session-upload-token>
```

### 1. 对齐评估

`POST assess_url`，`multipart/form-data; boundary=guidedassess`：

```text
image=@single-latest.jpeg
```

对齐结果不能保存为正式录入照。它只返回一个允许的 `guidance_code`。

### 2. 姿态批量采集

`POST capture_url`，`multipart/form-data; boundary=guidedcapture`：

```text
pose=front|left|right
round=1|2|3
candidate_0=@jpeg
candidate_1=@jpeg
candidate_2=@jpeg
```

一轮固定三张候选，约 300ms 间隔。服务端应只选择该姿态最佳的一张；无脸、模糊、重复、多人、未选中候选均不得保留，也不计入 `accepted_count`。

### 3. 通用 V2 成功响应

```json
{
  "ok": true,
  "session_id": "same-session-id",
  "guidance_code": "CAPTURE_LEFT",
  "accepted_count": 1,
  "draft_ready": false
}
```

可选失败字段：`error_code`、`retryable`。不要返回提示自然语言、TTS URL、图片 URL 或让大模型改写提示。

允许的 `guidance_code`：

```text
START NO_FACE MOVE_SCREEN_LEFT MOVE_SCREEN_RIGHT MOVE_UP MOVE_DOWN
MOVE_CLOSER MOVE_BACK FACE_FORWARD TOO_DARK MULTIPLE_FACES HOLD_STILL
ALIGN_READY CAPTURE_FRONT CAPTURE_LEFT CAPTURE_RIGHT
RECAPTURE_FRONT RECAPTURE_LEFT RECAPTURE_RIGHT UPLOADING
DRAFT_READY POSE_FAILED TIMEOUT CANCELLED SERVICE_ERROR
```

设备拒绝未知 code；`UNKNOWN_RESULT` 是设备本地 fail-closed 状态，服务端不得下发。

约束：

- `accepted_count` 只能 `0..3`，不得倒退；
- `draft_ready=true` 时，`guidance_code` 必须为 `DRAFT_READY` 且 `accepted_count=3`；
- 固件每个姿态最多执行三轮（首次 + 两次补采）。若右脸不合格，请返回 `RECAPTURE_RIGHT`，不得要求重拍已合格的正脸/左脸；
- `POSE_FAILED`、`TIMEOUT`、`CANCELLED`、`SERVICE_ERROR` 为终态；
- `ALIGN_READY` 会使固件进入 `CAPTURE_FRONT`。

## 四、取消控制意图

服务端须将“取消录入人脸”、“取消录入”、“停止录入人脸”确定性映射到既有 MCP 工具：

```text
camera.face.enroll.cancel
```

这不是闲聊，也不应交给大模型决定。设备双击顶部现有触摸区域也会本地取消；单击、长按、滑动保持原行为。

## 五、Cursor 服务端实施提示词

> 仅修改服务端仓库。先只读审计现有 V1 `face_enrollment` session/upload/cancel 路由、鉴权、短期 token、照片清理与 MCP 能力下发；不要修改固件、Nginx、DNS、TLS 或数据库 schema。确认后实现 `protocol_version=2 && guided_burst_v1=true` 的 opt-in Guided Burst V2。V1 路由及所有未带显式开关的设备必须完全保持 V1。
>
> V2 session 创建响应必须提供 `session_id, assess_url, capture_url, cancel_url, upload_token, expires_at, required_frames=3, max_frames=3`；所有 URL 必须为同一 HTTPS 公网 host，token 至少有效 240 秒。实现 `POST assess_url`（单张 multipart 字段 `image`）和 `POST capture_url`（字段 `pose`, `round=1..3`, `candidate_0..candidate_2`）。每个请求验证现有 pairing auth 与 `X-Enrollment-Token`，不得记录 token/JPEG/人脸特征或完整 URL query。
>
> 两个 V2 接口只返回 `ok, session_id, guidance_code, accepted_count, draft_ready`，失败可加 `error_code,retryable`，绝不返回自然语言/TTS/LLM 文本。未知 code 不得下发；`draft_ready` 仅在 `guidance_code=DRAFT_READY, accepted_count=3` 时允许。服务端对 front/left/right 每个姿态只保留最终最佳候选；无脸、模糊、多人、重复、未选中候选立即删除且不计数。`RECAPTURE_<POSE>` 只能要求补采该不合格姿态。第三轮仍失败应回 `POSE_FAILED`。实现语音取消词到 `camera.face.enroll.cancel` 的确定性路由。为 V1/V2 分别补单测、鉴权/host/expiry/cleanup 测试；执行项目现有测试并报告 diff，未经授权不要部署或重启。
