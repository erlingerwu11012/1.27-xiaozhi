"""Restore original values recorded before authorized reversible test."""
import json,socket,time
from pathlib import Path
OUT=Path('/root/prjs/tmp/natural-dialogue-20261003')
def probe(payload):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as s:
        s.settimeout(80);s.connect(str(OUT/'probe.sock'));s.sendall((json.dumps(payload)+'\n').encode());data=b''
        while not data.endswith(b'\n'):
            p=s.recv(65536)
            if not p:break
            data+=p
        return json.loads(data)
rows=[]
for name,args,q in [('self_audio_speaker_set_volume',{'volume':100},'把音量调到100'),('self_screen_set_brightness',{'brightness':100},'把亮度调到100'),('self_get_device_status',{},'查询设备状态')]:
    result=probe({'op':'call','name':name,'arguments':args,'query':q});rows.append({'name':name,'receipt':result})
(OUT/'device-restoration.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2));print(json.dumps(rows,ensure_ascii=False))
