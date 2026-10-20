"""Model-facing descriptions and strict business receipts for reminder actions."""
import copy
import json
import re
from core.utils.tool_result import parse_payload

DESCRIPTIONS = {
    'reminder_get_current': '读取设备当前提醒卡片。用户说“我喝过了”“取消这张卡”“稍后提醒”时先调用本工具。返回空则说明没有当前提醒；使用返回的 instance_id、revision 和按钮含义，禁止猜测 ID。',
    'reminder_action': '操作已读取的当前提醒；必须先 reminder_get_current。instance_id、revision 原样使用回执，动作以卡片类型及按钮含义为准。primary=完成本次；secondary=稍后提醒；tertiary 在便签为跳过本次、习惯为跳过今天、闹钟为永久关闭；cancel 仅便签支持永久删除，仅用户明确要求删除时使用。minutes/snooze_at 按用户时间设置。“关卡片”含义不明确先澄清。只有成功业务回执才能说完成，身份拒绝不得换工具绕过。',
    'behavior_log': '记录行为意图用于习惯分析，不能创建提醒、启动倒计时、完成事项或关闭卡片。不得代替执行用户请求的工具。记录成功只代表日志已保存，不代表用户操作完成。',
    'alarm_dismiss': '关闭正在响的提醒，返回实际处理结果。它不创建倒计时、不删除未来提醒、不证明喝水等事项已完成。当前卡片操作优先 reminder_get_current + reminder_action，禁止用它绕过身份或失败回执。',
    'note_add': '保存便签或定时提醒。remind_at=0 只保存便签；定时提醒必须使用准确的 Unix 秒时间，由服务端解析相对时间，禁止自行猜时间戳。接收人未指定时由服务端使用本轮已确认声纹，显式人名按用户目录解析。保存失败不能说设置成功。',
}


def describe_tool(tool):
    name = str((tool.get('function') or {}).get('name') or '').replace('.', '_')
    if name not in DESCRIPTIONS:
        return tool
    result = copy.deepcopy(tool)
    result['function']['description'] = DESCRIPTIONS[name]
    return result


ACTION_RECEIPTS = {
    'primary': ('提醒已完成', '本次闹钟已完成', '本次习惯已完成'),
    'secondary': ('将在指定时间再次提醒', '将在指定时间再次响铃'),
    'tertiary': ('已跳过本次提醒', '已跳过今天', '闹钟已永久关闭'),
    'cancel': ('提醒已永久删除',),
    'silence': ('已停止声音，事项仍待处理',),
}


def reminder_action_completed(arguments, result):
    """Accept only a receipt for this exact action; transport acceptance is insufficient."""
    action = arguments.get('action')
    body = parse_payload(result)
    if isinstance(body, dict):
        return (body.get('ok') is True and body.get('status') == 'completed'
                and body.get('instance_id') == arguments.get('instance_id')
                and body.get('action') == action and body.get('accepted') is not True)
    if not isinstance(result, str):
        return False
    if result.strip() in ACTION_RECEIPTS.get(action, ()):
        return True
    return (action == 'secondary' and type(arguments.get('minutes')) is int
            and result.strip() in {f"{arguments['minutes']}分钟后再次提醒",
                                   f"{arguments['minutes']}分钟后再次响铃"})
