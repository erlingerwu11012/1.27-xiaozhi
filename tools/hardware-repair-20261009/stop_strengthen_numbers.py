from pathlib import Path
import json,os,signal,time
S=Path(__file__).parent
for p in Path('/proc').iterdir():
 if p.name.isdigit():
  try:cmd=(p/'cmdline').read_bytes()
  except OSError:continue
  if b'run_model.py' in cmd and b'resume-final' in cmd:os.kill(int(p.name),signal.SIGTERM)
time.sleep(.3)
for suffix in ['results.jsonl','freeze.json','console.log','summary.json']:
 p=S/('resume-final-'+suffix)
 if p.exists():p.rename(S/('resume-final-chinese-number-guard-'+suffix))
print('preserved incomplete run before strengthening Chinese number assertions')
