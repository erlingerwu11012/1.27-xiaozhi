from pathlib import Path
S=Path(__file__).resolve().parent;W=S/'work';B=S.parent/'hardware-repair-20261009/work'
for name in ['core/connection.py','core/utils/device_reminder.py']:
 p=W/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((B/name).read_bytes())
p=W/'core/connection.py';s=p.read_text(encoding='utf-8');needle="            if not str(query or '').strip():return False";assert needle in s
s=s.replace(needle,"""            from core.utils.operation_control import content_text
            accepted_text=content_text(query).strip()
            # Exact non-semantic ASR outputs do not supersede a real request.
            if not accepted_text or re.fullmatch(r'[\\s，,。.!！?？…～~]*|(?:咳[咳嗽]*|\\[噪音\\]|\\[无语音\\])[，,。.!！?？… ]*',accepted_text):return False""")
p.write_text(s,encoding='utf-8')
p=W/'core/utils/device_reminder.py';s=p.read_text(encoding='utf-8');needle="    accepted=getattr(conn,'_person_inputs',{}).get(getattr(actor,'turn_id',''))";assert needle in s
s=s.replace(needle,"""    task_input=getattr(conn,'_harness_task_input',None)
    if isinstance(task_input,dict) and task_input.get('turn_id')==getattr(actor,'turn_id',None):
        return str(task_input.get('text') or '')
"""+needle)
p.write_text(s,encoding='utf-8')
p=W/'core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8');s=s.replace('公共提醒recipient=all，个人接收人必须由当前身份和真实目录验证。','公共提醒在text中保留公共语义；设备接收人字段recipient_person_id=all，个人接收人必须由当前身份和真实目录验证。')
p.write_text(s,encoding='utf-8')
print('lifecycle and continuation adapters prepared')
