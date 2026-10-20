from pathlib import Path
r=Path('tools/hardware-repair-20261009')
p=r/'work/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8');needle='current.reply=device_status_reply(current.payload,query)';s=s.replace(needle,needle+'''
                if re.search(r'最高档|最亮|最高亮度',plain) and isinstance(current.payload,dict):
                    from .domains import bounds
                    definition=tools.get('self_screen_set_brightness');screen=current.payload.get('screen',{})
                    level=screen.get('brightness_level',current.payload.get('brightness_level'))
                    if definition and type(level) is int:
                        hi=bounds('self_screen_set_brightness',definition)[1]
                        if hi:current.reply=f'当前亮度是{level}档，最高为{hi}档。'+('已经是最高档。' if level==hi else '还不是最高档。')
''');p.write_text(s,encoding='utf-8')
p=r/'work/core/utils/tool_harness/reply_composer.py';s=p.read_text(encoding='utf-8');needle='    for r in results:\n        if r.tool in';insert='''    completion=r'设好(?:啦|了)|调好(?:啦|了)|搞定|已完成|已经完成|成功(?:设置|删除|更正)|重启(?:完成|成功|好了)|录入(?:完成|成功|好了)'
    if any(r.state!='completed' for r in writes) and re.search(r'都(?:已|已经)?(?:完成|搞定|设好|调好)',text):return True
    for r in writes:
        if r.state=='completed':continue
        noun={'self_audio_speaker_set_volume':'音量|声音','self_screen_set_brightness':'亮度|屏幕','alarm_set':'闹钟','note_add':'便签|提醒','add_reminder':'提醒','habit_learn':'习惯','self_reboot':'重启','camera_face_enroll_start':'录入|人脸'}.get(r.tool)
        if noun:
            for clause in re.split('[，,。；;]',text):
                if re.search(noun,clause) and re.search(completion,clause) and not re.search(r'没有|未能|尚未|没能|不能|无法|还没|未完成',clause):return True
'''
s=s.replace(needle,insert+needle,1);p.write_text(s,encoding='utf-8')
