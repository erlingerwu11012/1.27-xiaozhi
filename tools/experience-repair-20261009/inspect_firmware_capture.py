import json,re,collections
from pathlib import Path
S=Path('tools/experience-repair-20261009');R=Path(json.loads((S/'active-hardware-capture.json').read_text(encoding='utf-8-sig'))['output']);data=(R/'firmware-0001.raw').read_bytes();lines=data.decode('utf-8',errors='replace').splitlines();warnings=[];relevant=[]
for i,l in enumerate(lines,1):
 clean=re.sub(r'\x1b\[[0-9;]*m','',l).replace('\x00','')
 if re.search(r'^(?:[EW] \(|.*(?:error|failed|not_ready|mismatch|NVS|EspWS|WS_DIAG|ALARM|alarm|set_volume|brightness|take_photo|identify_person|reminder\.action|reminder\.get_current|MCP|Camera|Vision|REMIN|REMIND))',clean,re.I):relevant.append((i,clean))
 if re.match(r'^[EW] \(',clean):warnings.append((i,clean))
print('BYTES',len(data),'LINES',len(lines),'NULLS',data.count(b'\0'),'WARNINGS',len(warnings))
print('FIRMWARE WARNINGS')
for i,l in warnings:print(str(i)+':'+l)
print('KEY EVIDENCE')
for i,l in relevant:
 if re.search('alarm|Alarm|拍照|photo|Camera|Vision|亮度|音量|set_volume|brightness|reminder.action|MCP.*(?:result|error|request|call)|REMIN',l,re.I):print(str(i)+':'+l)
