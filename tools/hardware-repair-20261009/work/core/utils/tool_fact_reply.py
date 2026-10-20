"""Render a small allowlist of verified receipts without a model rewrite.

Only completed tool results enter here; never parse assistant prose as receipts.
Unknown tools still use the normal primary-model continuation.
"""
import json
import re
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from plugins_func.register import Action


def world_time_reply(arguments, text):
    timezone = arguments.get('timezone')
    if not isinstance(timezone, str):
        return '时间查询结果不完整，暂时不能确认当地时间。'
    pattern = (r'(?:🌍\s*)?([^\s]+)\s+当前时间：\s*'
               r'(\d{4})年(\d{2})月(\d{2})日\s+(\d{2}):(\d{2}):(\d{2})\s*'
               r'\((Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\)\s*'
               r'时区：UTC([+-])(\d{1,2})(?::(\d{2}))?')
    match = re.fullmatch(pattern, text.strip()) if isinstance(text, str) else None
    if not match or match[1] != timezone:
        return '时间查询结果不完整，暂时不能确认当地时间。'
    try:
        moment = datetime(*(int(match[i]) for i in range(2, 8)))
        zone = ZoneInfo(timezone)
        minutes = int(match[10]) * 60 + int(match[11] or 0)
        if int(match[10]) > 14 or int(match[11] or 0) > 59:
            raise ValueError('invalid offset')
        offset = timedelta(minutes=minutes * (1 if match[9] == '+' else -1))
        if not any(moment.replace(tzinfo=zone, fold=fold).utcoffset() == offset for fold in (0, 1)):
            raise ValueError('timezone offset mismatch')
        weekdays = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
        if weekdays[moment.weekday()] != match[8]:
            raise ValueError('weekday mismatch')
    except (ValueError, ZoneInfoNotFoundError):
        return '时间查询结果有冲突，暂时不能确认当地时间。'
    from core.utils.operation_control import WORLD_TIMEZONES
    city = next((city for city, value in WORLD_TIMEZONES.items() if value == timezone), None)
    label = city or timezone
    return f'{label}当地时间是{moment.year}年{moment.month}月{moment.day}日，{moment.hour:02d}点{moment.minute:02d}分。'


def verified_tool_reply(result, call):
    """Return None for open-ended answers, a literal reply for known facts."""
    if getattr(result, 'action', None) != Action.REQLLM:
        return None
    name = call.get('name', '')
    if name.startswith('mcp_'):
        name = name[4:]
    allowed = {'get_world_time', 'self_get_device_status', 'self_audio_speaker_set_volume',
               'self_screen_set_brightness', 'add_reminder', 'note_add', 'camera_open', 'camera_close'}
    if name not in allowed:
        return None
    try:
        arguments = call.get('arguments') or '{}'
        arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
        if not isinstance(arguments, dict):
            raise ValueError('not an object')
    except (ValueError, TypeError):
        return '工具参数或回执不完整，暂时不能确认结果。'
    if name == 'get_world_time':
        return world_time_reply(arguments, getattr(result, 'result', None))
    from core.utils.operation_control import CONTRACTS, feedback, payload_of
    if name == 'self_get_device_status':
        body = payload_of(result)
        if not isinstance(body, dict) or body.get('ok') is False or body.get('success') is False or body.get('status') == 'error':
            return '没有读到可信的设备状态。'
        facts = []
        for key, nested, inner, label in [('volume', 'audio_speaker', 'output_volume', '音量'),
                                          ('brightness', 'screen', 'brightness', '屏幕亮度')]:
            value = body.get(key)
            sub = body.get(nested)
            if value is None and isinstance(sub, dict):
                value = sub.get(key, sub.get(inner))
            if type(value) is int and 0 <= value <= 100:
                facts.append(f'{label}是{value}')
        return '当前' + '，'.join(facts) + '。' if facts else '没有读到可信的音量或亮度数值。'
    kind = next(kind for kind, contract in CONTRACTS.items() if contract[0] == name)
    return feedback(SimpleNamespace(kind=kind, arguments=arguments), result)
