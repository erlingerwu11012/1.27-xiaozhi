from pathlib import Path

root = Path(__file__).parent / 'test'
for name in ['test_recipient_resolver.py', 'test_device_reminder.py']:
    path = root / name
    text = path.read_text(encoding='utf-8').replace(
        'core.utils.device_reminder.resolve_recipient_for_conn',
        'core.utils.device_reminder.resolve_unified_recipient_for_conn')
    if name == 'test_recipient_resolver.py':
        text = text.replace('and "歧义" in (resp.result or "")', 'and "歧义" in (resp.response or "")')
    else:
        text = text.replace('route:self_uses_default_owner_usr', 'route:self_uses_confirmed_speaker_usr')
        start = text.index('def test_prompt_injection():')
        end = text.index('\ndef test_tool_description_rewrite():', start)
        text = text[:start] + '''def test_prompt_injection():
    print("\\n== Frozen per-turn time context ==")
    from types import SimpleNamespace
    from core.utils.turn_context import build_turn_context
    from core.utils.dialogue import Message
    frozen = {"current_datetime": "2026-08-02 21:00:00",
              "today_date": "2026-08-02", "today_weekday": "星期日",
              "timezone": "Asia/Shanghai", "unix_timestamp": 1785675600}
    with patch("core.utils.current_time.get_prompt_time_context", return_value=frozen):
        ctx = build_turn_context(SimpleNamespace(), None, None)
    d = Dialogue()
    messages = []
    d.getMessages(Message(role="user", content="两分钟后提醒我喝水", prompt_context=ctx), messages)
    content = messages[0]["content"]
    check("prompt:frozen_time", "2026-08-02 21:00:00" in content)
    check("prompt:timezone_shanghai", "Asia/Shanghai" in content)
    check("prompt:user_content_preserved", content.endswith("两分钟后提醒我喝水"))
    check("prompt:no_unix_guessing", "1785675600" not in content)
    check("prompt:context_not_in_system", messages[0]["role"] == "user")
    check("prompt:no_literal_placeholders", "{{" not in content)

''' + text[end:]
    path.write_text(text, encoding='utf-8')
