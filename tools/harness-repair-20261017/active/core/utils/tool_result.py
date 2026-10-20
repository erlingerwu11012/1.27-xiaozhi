"""Device error contract. Keep transport status separate from business results."""
import json
import re

MESSAGES = {
    'vision_awaiting_hello':'视觉连接还在建立，这次没有拍照。',
    'vision_awaiting_initialize':'视觉配置尚未送达设备，这次没有拍照。',
    'vision_expired':'视觉授权已过期，这次没有拍照。',
    'vision_missing_identity_url':'识人服务地址尚未配置，这次没有识人。',
    'vision_incomplete_pending':'视觉配置不完整，这次没有拍照。',
    'vision_connection_closed':'视觉连接已经断开，这次没有拍照。',
    'vision_vision_session_mismatch':'视觉授权属于其他会话，这次没有拍照。',
    'capture_or_upload_failed':'拍照或上传失败，这次没有获得识别结果。',
    'vision_not_ready':'视觉服务尚未就绪，这次没有拍照，请稍后再试。',
    'vision_session_mismatch':'视觉授权与当前连接不一致，这次没有完成拍照。',
    'vision_upload_failed':'照片上传失败，这次没有获得识别结果。',
    'vision_http_401':'视觉授权已失效，请重新连接后再试。',
    'vision_http_403':'当前没有使用视觉服务的权限。',
    'vision_http_413':'照片超过服务端允许的大小。',
    'vision_http_500':'视觉服务处理失败，请稍后再试。',
    'vision_http_502':'视觉服务暂时无法连接，请稍后再试。',
    'vision_http_504':'视觉服务响应超时，请稍后再试。',
    'vision_timeout':'视觉服务响应超时，请稍后再试。',
    'identity_unconfirmed': '这次没听出是谁，请本人再说一句让我确认。',
    'identity_mismatch': '当前确认的身份不是这条提醒的接收人，请由本人处理，或在屏幕上操作。',
    'storage_full': '设备的持久化存储空间不足，这条提醒没有保存。',
    'storage_write_failed': '设备保存提醒失败，这条提醒没有保存。',
    'note_limit_reached': '备忘录已达到20条上限，请先删除不需要的事项。',
    'invalid_repeat_days': '重复提醒的日期参数不正确，这条提醒没有保存。',
    'persist_failed': '提醒状态保存失败，这次操作没有完成。',
    'storage_error': '设备保存事项失败，这次操作没有完成。',
    'inactive': '这条提醒已经结束，没有执行新的操作。',
    'invalid_snooze_time': '稍后提醒的时间不正确，请说明未来的时间或1到60分钟。',
    'stale_revision': '提醒状态已经更新，请重新读取当前提醒后再操作。',
    'recipient_not_found': '没有找到指定的接收人，请确认账号中登记的姓名。',
    'not_found': '这条提醒已不存在，请重新读取当前提醒。',
    'no_current': '当前没有可操作的提醒卡片。',
    'not_actionable': '当前卡片是信息提示，不能执行完成或取消操作。',
    'unsupported_action': '当前提醒不支持这个操作。',
    'session_mismatch': '这条提醒不属于当前会话，请重新读取当前提醒。',
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
        # Compatibility for deployed firmware's JSON-RPC error message. Only
        # accept known error prefixes; never interpret an arbitrary device string.
        if not code or code == 'unclassified_tool_error':
            prefix = re.match(r'^([a-zA-Z0-9_.-]{1,80}):\s', str(message))
            if prefix and (prefix[1] in MESSAGES or re.fullmatch(r'(?:vision|identity)_http_[1-5][0-9]{2}',prefix[1])):
                code = prefix[1]
        self.code = code if isinstance(code, str) and re.fullmatch(r'[a-zA-Z0-9_.-]{1,80}', code) else 'unclassified_tool_error'
        self.details = details or {}
        self.device_message = str(message)[:512]
        super().__init__(self.user_message)

    @property
    def user_message(self):
        if self.code.startswith('vision_http_'):
            status=self.code.removeprefix('vision_http_')
            return MESSAGES.get(self.code,'视觉请求被服务端拒绝，HTTP 状态码为'+status+'。')
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
    if isinstance(result, str) and result.strip() in {'人脸录入已开始','ENROLL_STARTED','[FACE_ENROLL_STARTED]'}:
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
