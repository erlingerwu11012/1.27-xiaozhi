"""Synthetic turns through the actual device chat pipeline; no write actions."""
import json, time, re, socket
from pathlib import Path

OUT=Path('/root/prjs/tmp/natural-dialogue-20261003')
def probe(payload):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(90)
        client.connect(str(OUT/'probe.sock'))
        client.sendall((json.dumps(payload,ensure_ascii=False)+'\n').encode())
        chunks=[]
        while True:
            part=client.recv(65536)
            if not part:break
            chunks.append(part)
            if b'\n' in part:break
    return json.loads(b''.join(chunks))
deadline=time.monotonic()+240
while True:
    catalog=probe({'op':'catalog'})
    if catalog.get('online') and catalog.get('ready'):break
    if time.monotonic()>deadline:raise RuntimeError('device_wait_expired')
    time.sleep(1)
report={'synthetic_text_injection':True,'physical_microphone_samples':0,
        'source_sha256':catalog['implementation_sha256'],'persona_before':catalog['persona_sha256'],'cases':[]}
for text in ['你好，随便聊聊。','别哄我，说说你真实的看法。','23乘以17等于多少？','查看设备当前状态']:
    result=probe({'op':'chat','text':text})
    answers=result.get('answers') or []
    combined=''.join(str(a) for a in answers)
    row={'text':text,'receipt':result,'success':bool(answers) and not result.get('error_type')
         and not re.search('服务暂时无法响应|没有确认到|处理失败|请求失败',combined)}
    if '23' in text:row['success']=row['success'] and '391' in combined
    if text.startswith('别哄我'):row['success']=row['success'] and '哪件事' in combined
    row['style_flag']=bool(re.search('乖乖|小主人|嘻嘻|嘿嘿|小尾巴|小脑袋瓜',combined))
    row['success']=row['success'] and not row['style_flag']
    report['cases'].append(row)
    (OUT/'pipeline-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(row,ensure_ascii=False),flush=True)
    time.sleep(4)
after=probe({'op':'catalog'})
report['persona_unchanged']=after.get('persona_sha256')==report['persona_before']
report['success']=all(c['success'] for c in report['cases']) and report['persona_unchanged']
(OUT/'pipeline-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
assert report['success'],'pipeline_acceptance_failed'
print('pipeline accepted; no hardware write actions',flush=True)
