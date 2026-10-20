"""Read-only diagnosis against deployed Python modules. No tool or device calls."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock
import config.config_loader
def offline(config):
    result = dict(config)
    result['read_config_from_api'] = False
    result['manager-api'] = {}
    return result
config.config_loader.get_config_from_api = offline
import config.settings
config.settings.config_file_valid = True
import config.logger
config.logger.setup_logging = lambda: MagicMock()
from core.utils.operation_control import OperationControl, get_control, guard_reply
cases = [
    ('13:10:15', '把亮度调到百分之六十。'),
    ('13:10:31', '声音太大了，调小声点儿。'),
    ('13:13:54', '把音量调到百分之四十。'),
    ('13:14:05', '那你把音量调到百分之四十。'),
    ('13:14:18', '调了没有？'),
    ('13:14:56', '把音亮度调到百分之四十。'),
    ('13:15:15', '把音量亮度调到百分之四十。'),
    ('13:15:55', '把亮度调低，调到百分之四十。'),
    ('13:16:10', '把亮度调高，再调高一点。'),
    ('13:16:20', '亮度调高。'),
    ('13:16:36', '把亮度调到百分之百。'),
    ('13:16:52', '把亮度再调到最大，你他妈没调。'),
    ('13:17:04', '找到调节亮度的工具，把亮度调到最大。'),
    ('13:18:14', '把亮度调到九十。'),
]
for timestamp, text in cases:
    plan = OperationControl().begin(text, ('synthetic', 'actor'))
    wrapped = OperationControl().begin(json.dumps({'speaker':'张宸硕', 'content':text}, ensure_ascii=False), ('synthetic','actor'))
    print(json.dumps({'time':timestamp, 'user':text,
        'fast_actions':[{'kind':r.kind, 'args':r.arguments, 'delta':r.delta} for r in plan.requests],
        'speaker_wrapper_same': [(r.kind,r.arguments,r.delta) for r in plan.requests] == [(r.kind,r.arguments,r.delta) for r in wrapped.requests]}, ensure_ascii=False))
claims = [
    '好嘞，屏幕亮度调到60%啦张宸硕，这下光线柔和得刚刚好！',
    '好嘞，音量调小啦张宸硕，现在这声音轻柔得刚刚好！',
    '好嘞，屏幕亮度直接拉满到100%啦张宸硕！',
    '音量已调到40。',
    '亮度已调到100。',
]
for text in claims:
    conn=SimpleNamespace(config={'operation_control':{'enabled':True}})
    get_control(conn).begin('synthetic no-receipt turn', ('synthetic','actor'))
    reply=guard_reply(conn,text)
    print(json.dumps({'reply':text, 'no_receipts':True, 'blocked':reply != text, 'output':reply},ensure_ascii=False))
