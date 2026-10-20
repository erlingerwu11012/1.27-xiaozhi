import collections,json,re,subprocess
from pathlib import Path
report={}
commands={'billing_service':['journalctl','-u','one-api-bailian.service','--since','25 minutes ago','--no-pager','-n','1500'],'one_api':['docker','logs','--since','25m','--tail','2000','one-api']}
for name,cmd in commands.items():
 r=subprocess.run(cmd,capture_output=True,text=True,timeout=15);lines=(r.stdout+r.stderr).splitlines()
 patterns=['context deadline exceeded','i/o timeout','timed out','429','insufficient','欠费','payment','502','503','504','rate limit','connection reset']
 report[name]={'exit_code':r.returncode,'lines_scanned':len(lines),'pattern_counts':{p:sum(p in x.lower() for x in lines) for p in patterns}}
report['load_average']=Path('/proc/loadavg').read_text().split()[:3]
(Path(__file__).parent/'transport-diagnostic.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
