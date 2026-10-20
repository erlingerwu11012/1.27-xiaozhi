import json,re,collections
from pathlib import Path
S=Path('tools/experience-repair-20261009');R=Path(json.loads((S/'active-hardware-capture.json').read_text(encoding='utf-8-sig'))['output']);F=(R/'firmware-0001.raw').read_bytes().decode('utf-8',errors='replace').splitlines();L=(R/'server-0.log').read_text(encoding='utf-8').splitlines()
print('FIRMWARE NON-DIAGNOSTIC WARNINGS')
for i,l in enumerate(F,1):
 if re.match(r'^[EW] \(',l) and 'TaskDiag:' not in l and '[SPINE]' not in l:print(i,l)
print('FIRMWARE COMMAND / CAMERA / ALARM')
for i,l in enumerate(F,1):
 if re.search(r'CameraTools:|Esp32Camera:|HttpClient:|AlarmManager:|Set volume|volume.*[0-9]|brightness.*[0-9]|Brightness.*[0-9]|event=action|action_result|identity.*result|\[MCP',l,re.I):print(i,l)
print('SERVER SELECTED WINDOWS')
for lo,hi in [(1260,1300),(1710,1745),(2480,2498),(2520,2539),(2988,3018),(3213,3235)]:
 print('WINDOW',lo,hi)
 for i in range(lo,hi+1):
  l=L[i-1]
  if any(k in l for k in ['audio_frame','AUDIO_UL','device_send','type=listen','asr.qwen','[MCP解包]']):continue
  print(i,l)
