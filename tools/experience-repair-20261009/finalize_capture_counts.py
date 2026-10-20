from pathlib import Path
import json,re,datetime,collections
S=Path('tools/experience-repair-20261009');R=Path(json.loads((S/'active-hardware-capture.json').read_text(encoding='utf-8-sig'))['output']);start=datetime.datetime.fromtimestamp(json.loads((R/'manifest.json').read_text())['started_ns']/1e9,datetime.timezone(datetime.timedelta(hours=8))).strftime('%H:%M:%S');ls=(R/'server-0.log').read_text(encoding='utf-8').splitlines();counts=collections.Counter();vals=[]
for l in ls:
 m=re.match(r'261009 (\d\d:\d\d:\d\d)',l)
 if not m or m[1]<start:continue
 if '声纹识别相似度' in l and '低于阈值' in l:counts['below_threshold']+=1;vals.append(float(re.search(r'相似度([0-9.]+)',l)[1]))
 if '声纹识别成功' in l:counts['recognized']+=1
 if '[asr_start]' in l:counts['asr_starts']+=1
 if 'harness.validation ' in l:
  q=json.loads(l.split('harness.validation ',1)[1]);print(json.dumps({'time':m[1],**q},ensure_ascii=False))
print('VOICEPRINT',dict(counts),'SCORES',min(vals),max(vals))
F=(R/'firmware-timed.log').read_text(encoding='utf-8').splitlines();states=[]
for l in F:
 if 'Application: STATE:' in l:
  t=l.split()[0];state=l.rsplit('STATE:',1)[1].strip();states.append((t,state))
print('STATE CHANGES AROUND ALARM')
for t,s in states:
 if '17:39:00'<=t<='17:41:30':print(t,s)
print('FIRMWARE EVENTS',dict(collections.Counter('encode_drop' if 'Encode queue full, dropping frame' in x else 'touch_i2c_error' if 'I2C read error!' in x else 'information_due' if 'event=due instance=information:' in x else 'other' for x in F)))
