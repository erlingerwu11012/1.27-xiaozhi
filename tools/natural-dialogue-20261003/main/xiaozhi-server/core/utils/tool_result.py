"""Device error contract. Keep transport status separate from business results."""
import json
import re

MESSAGES = {
    'resource_exhausted': '设备内存不足，暂时无法启动任务。',
    'task_create_failed': '设备任务启动失败。',
    'camera_busy': '摄像头正在使用，请稍后再试。',
    'already_active': '人脸采集正在进行，请等待完成或先取消。',
    'capability_invalid': '人脸录入授权或接口配置无效，请重新连接后重试。',
    'invalid_image': '没有收到有效图片，请重新拍摄。',
    'invalid_multipart': '图片上传格式不正确。',
    'preview_active': '摄像头预览正在使用，请先退出预览。',
    'camera_not_ready': '摄像头尚未就绪。',
    'capture_failed': '这次拍摄失败，请重试。',
    'permission_denied': '当前没有执行这项操作的权限。',
    'authentication_failed': '设备授权已失效，请重新连接。',
    'payload_too_large': '图片太大，服务端无法接收。',
    'request_timeout': '等待设备回执超时，结果尚不确定，不会自动重复执行。',
    'upstream_timeout': '识人服务响应超时。',
    'service_unavailable': '识人服务暂时不可用。',
    'upstream_auth_rejected': '识人服务的内部授权失败。',
    'upstream_unreachable': '暂时无法连接识人服务。',
    'upstream_invalid_response': '识人服务返回的数据异常。',
    'upstream_error': '识人服务处理失败。',
    'session_cancelled': '本次操作已取消。',
    'connection_closed': '连接已结束，本次操作结果未确认。',
    'mcp_not_ready': '设备工具正在同步，请稍后再试。',
    'tool_unavailable': '当前会话未开放这项设备工具。',
    'unclassified_tool_error': '设备执行失败，暂未提供明确原因。',
    'invalid_tool_result': '设备回执格式异常，操作结果未确认。',
}


class DeviceToolError(RuntimeError):
    def __init__(self, code, message='', details=None):
        self.code = code if isinstance(code, str) and re.fullmatch(r'[a-zA-Z0-9_.-]{1,80}', code) else 'unclassified_tool_error'
        self.details = details or {}
        self.device_message = str(message)[:512]
        super().__init__(self.user_message)

    @property
    def user_message(self):
        if self.code.startswith('identity_http_'):
            status = self.code.removeprefix('identity_http_')
            return {'401': MESSAGES['authentication_failed'], '403': MESSAGES['permission_denied'],
                    '413': MESSAGES['payload_too_large']}.get(status, '识人请求被服务端拒绝，HTTP 状态码为' + status + '。') if status != '200' else MESSAGES['upstream_error']
        return MESSAGES.get(self.code, MESSAGES['unclassified_tool_error'])

    def as_dict(self):
        result = {'status': 'error', 'errorCode': self.code, 'message': self.user_message}
        for key in ('http_status', 'upstream_http_status', 'request_id', 'operation_id'):
            if key in self.details:
                result[key] = self.details[key]
        return result


def parse_payload(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return None
    return value if isinstance(value, dict) else None


def unwrap_tool_result(raw):
    """Preserve the historical string return API while interpreting explicit errors."""
    if not isinstance(raw, dict):
        raise DeviceToolError('invalid_tool_result')
    content = raw.get('content', [])
    text = next((p['text'] for p in content if isinstance(p, dict) and isinstance(p.get('text'), str)), '') if isinstance(content, list) else ''
    structured = raw.get('structuredContent')
    body = structured if isinstance(structured, dict) else parse_payload(text)
    body = body if isinstance(body, dict) else {}
    if raw.get('isError') is True or body.get('status') == 'error' or body.get('success') is False or body.get('ok') is False:
        code = raw.get('errorCode') or body.get('errorCode') or body.get('error_reason') or body.get('reason') or 'unclassified_tool_error'
        raise DeviceToolError(code, body.get('message') or text, body)
    if structured is not None:
        return json.dumps(structured, ensure_ascii=False)
    return text if text else json.dumps(raw, ensure_ascii=False)


def require_enrollment_accepted(result):
    body = parse_payload(result)
    if isinstance(body, dict):
        if body.get('accepted') is True or body.get('state') in {'accepted', 'starting', 'waiting_idle', 'creating', 'capturing'}:
            return body
        raise DeviceToolError(body.get('errorCode') or body.get('reason') or 'invalid_tool_result', details=body)
    # Legacy firmware: successful MCP envelope is already checked; do not infer completion.
    if isinstance(result, str) and result.strip():
        return {'state': 'accepted', 'legacy_ack': True}
    raise DeviceToolError('invalid_tool_result')


def require_note_created(result):
    """Known firmware commits the note before returning this legacy receipt."""
    body = parse_payload(result)
    if isinstance(body, dict):
        if (body.get('status') == 'created' and type(body.get('id')) is int
                and body['id'] >= 0 and body.get('ok') is not False
                and body.get('accepted') is not True):
            return body
    elif isinstance(result, str) and result.startswith('已记录：'):
        return {'status': 'created', 'legacy_receipt': True}
    raise DeviceToolError('invalid_tool_result', '没有收到提醒已创建的回执')
