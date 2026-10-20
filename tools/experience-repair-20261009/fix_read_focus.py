from pathlib import Path
R=Path(__file__).parent;p=R/'candidate/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8').replace("if re.search(r'音量|声音|亮度|几档',positive):return 'self_get_device_status'","if re.search(r'音量|声音|亮度|几档',positive) or re.search(r'多少|多大|几档',positive) and re.search(r'音量|声音|亮度',q):return 'self_get_device_status'")
old="            current.intermediate=False;outcome.results.append(current);outcome.reply=current.reply;outcome.interrupted=not self.valid(scope,epoch);return outcome\n        fast=quoted_note_decision"
new="            if current.state=='completed':\n                from .presentation import device_status_reply\n                current.reply=device_status_reply(current.payload,query)\n            current.intermediate=False;outcome.results.append(current);outcome.reply=current.reply;outcome.interrupted=not self.valid(scope,epoch);return outcome\n        fast=quoted_note_decision"
assert old in s;s=s.replace(old,new);p.write_text(s,encoding='utf-8')
p=R/'candidate/core/utils/tool_harness/presentation.py';s=p.read_text(encoding='utf-8');s+='''

def device_status_reply(body,query=''):
    if not isinstance(body,dict):return '这次没有取得可确认的设备状态。'
    speaker=body.get('audio_speaker',{});speaker=speaker if isinstance(speaker,dict) else {}
    screen=body.get('screen',{});screen=screen if isinstance(screen,dict) else {}
    volume=body.get('volume',speaker.get('output_volume'))
    brightness=body.get('brightness',screen.get('brightness'))
    level=screen.get('brightness_level',body.get('brightness_level'))
    # Only describe the requested aspect when it is explicit.
    positive='，'.join(x for x in re.split('[，,；;。]',str(query)) if not re.match(r'^(?:这次|先|现在)?(?:不要|别|不用|不改|不动|不调)',x.strip()))
    focus=positive if re.search('音量|声音|亮度|几档',positive) else str(query)
    audio=bool(re.search('音量|声音',focus));display=bool(re.search('亮度|几档',focus))
    all_fields=not (audio or display)
    parts=[]
    if (audio or all_fields) and type(volume) is int:parts.append(f'当前音量是{volume}。')
    if display or all_fields:
        if type(level) is int:parts.append(f'当前亮度是{level}档。')
        elif type(brightness) is int:parts.append(f'当前亮度是{brightness}。')
    return ''.join(parts) or '这次返回的状态未包含所查询的数值。'
''';p.write_text(s,encoding='utf-8')
