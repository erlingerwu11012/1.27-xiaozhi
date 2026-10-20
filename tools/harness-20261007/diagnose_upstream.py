"""Read-only error classification; never print raw logs or credentials."""
import collections,json,re,subprocess
from pathlib import Path
patterns=['Arrearage','AccessDenied.AccountBlocked','AccessDenied','AccountBlocked','insufficient_quota','insufficient_user_quota','rate_limit_exceeded','余额不足','欠费','Access denied','hardware_account_insufficient_balance']
sources={}
command=['journalctl','-u','one-api-bailian','--since','2026-10-08 02:15:00','--no-pager','-o','cat']
sources['native_gateway']=subprocess.check_output(command,text=True,errors='replace')
probe=subprocess.run(['docker','logs','--since','25m','--tail','12000','one-api'],capture_output=True,text=True,errors='replace')
sources['one_api_container']=probe.stdout+probe.stderr
p=Path('/root/prjs/one-api/data/logs/oneapi-20261007.log')
if p.exists():
    with p.open('rb') as f:
        f.seek(max(0,p.stat().st_size-4000000));sources['one_api']=f.read().decode(errors='replace')
out={}
for name,raw in sources.items():
    count=collections.Counter();codes=collections.Counter();dates=[]
    for line in raw.splitlines():
        matches=[p for p in patterns if p in line]
        if not matches:continue
        count.update(matches)
        for code in re.findall(r'["\'](?:code|type)["\']\s*[:=]\s*["\']([A-Za-z0-9_.-]{1,64})',line):codes[code]+=1
        date=re.search(r'2026[-/]10[-/]0[78][ T][0-9:.]+|10/0[78]\s+[0-9:]+',line)
        if date and len(dates)<8:dates.append(date[0])
    out[name]={'classified_errors':count,'codes':codes,'first_matching_timestamps':dates,'raw_logs_disclosed':False}
(Path(__file__).parent/'upstream-error-summary.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
print(json.dumps(out,ensure_ascii=False))
