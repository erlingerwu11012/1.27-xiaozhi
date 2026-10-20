from pathlib import Path
R=Path(__file__).parent;p=R/'candidate/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8');needle='                for s in decision.steps:\n                    if card_operation';rep="                if query_card and decision.mode in {'operate','continue'} and decision.finished and not any(s.tool=='reminder_get_current' for s in decision.steps):raise ValueError('current_card_query_requires_reminder_get_current')\n                for s in decision.steps:\n                    if card_operation";assert needle in s;s=s.replace(needle,rep);p.write_text(s,encoding='utf-8')
p=R/'candidate/core/utils/tool_harness/contracts.py';s=p.read_text(encoding='utf-8');old='        return out(\'failed\',f\'{label}没有完成：{body.get("error") or body.get("message") or "工具返回失败"}。\',code if code in MESSAGES else \'device_failure\')';new='''        message=MESSAGES.get(code) if code else None
        if not message:
            value=body.get('message') or body.get('error')
            message=value if isinstance(value,str) and not re.search(r'[{}]|errorCode|instance_id|tool_calls',value) else '工具返回失败'
        return out('failed',f'{label}没有完成：{message}。',code if code in MESSAGES else 'device_failure')''';assert old in s;s=s.replace(old,new);p.write_text(s,encoding='utf-8')
