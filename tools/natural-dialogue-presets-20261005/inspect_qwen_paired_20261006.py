import json,time
from pathlib import Path
root=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
for attempt in range(100):
    try:
        data=json.loads((root/'qwen-paired-tool-results-20261006.json').read_text())
        break
    except (ValueError,OSError):time.sleep(.05)
else:raise RuntimeError('snapshot_not_ready')
(root/'qwen-paired-tool-snapshot-20261006.json').write_text(json.dumps(data,ensure_ascii=False,indent=2))
print(json.dumps({'complete':data['complete'],'pairs':len(data['pairs']), 'totals':{m:{'n':sum(r['model']==m for r in data['cases']),'passed':sum(r['native_pass'] for r in data['cases'] if r['model']==m),'errors':sum(bool(r['api_errors']) for r in data['cases'] if r['model']==m)} for m in data['models']}},ensure_ascii=False))
for row in [r for r in data['cases'] if not r['native_pass']][:12]:
    print(json.dumps({k:row[k] for k in ['model','id','user','expected','reasons','steps','api_errors']},ensure_ascii=False))
