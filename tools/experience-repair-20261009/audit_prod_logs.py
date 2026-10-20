from pathlib import Path
import json,subprocess,datetime,collections,re,time
S=Path(__file__).parent; R=Path('/root/prjs/releases/experience-repair-20261009'); state=json.loads((R/'deployment-state.json').read_text()); apps=json.loads(subprocess.check_output(['pm2','jlist'])); out={}
for name,pid in state['new'].items():
 a=next(x for x in apps if x['pm_id']==pid); logs={}
 for kind in ['pm_out_log_path','pm_err_log_path']:
  p=Path(a['pm2_env'][kind]); data=p.read_text(errors='replace')[-8000000:] if p.exists() else ''; lines=data.splitlines(); selected=[]; active=False
  for line in lines:
   m=re.search(r'(?<!\d)(261009)[ T](\d\d:\d\d:\d\d)',line)
   if not m:m=re.search(r'(2026-10-09)[ T](\d\d:\d\d:\d\d)',line)
   if m:
    fmt='%y%m%d %H:%M:%S' if len(m[1])==6 else '%Y-%m-%d %H:%M:%S'
    epoch=datetime.datetime.strptime(m[1]+' '+m[2],fmt).replace(tzinfo=datetime.timezone(datetime.timedelta(hours=8))).timestamp(); active=epoch>=state['deployed_at']
   if active:selected.append(line)
  categories={'exception':r'Traceback|Exception|\bERROR\b|-ERROR-','unauthenticated_health':r'invalid_token|experience-unauthenticated-health','unauthorized':r'\b401\b|\b403\b','timeout':r'timeout|Timeout|超时','event_loop_blocking':r'event.loop.*block|slow.callback|Executing <.*took','false_success_guard':r'guard_reply|不能说已经完成|没有确认到操作完成','connection_close':r'close.code|断开连接|websocket.*closed|connection.*closed','harness_failure':r'harness.*(?:failed|error|exception)|tool.*(?:failed|error)'}
  logs[kind]={'path':str(p),'bytes':p.stat().st_size if p.exists() else 0,'lines_since_cutover':len(selected),'category_counts':{k:sum(bool(re.search(v,x,re.I)) for x in selected) for k,v in categories.items()},'expected_probe_errors':sum('WSS 认证失败 reason=missing token_present=False device_id_set=True' in x for x in selected),'unexpected_exception_lines':sum(bool(re.search(r'Traceback|Exception|\bERROR\b|-ERROR-',x)) and 'WSS 认证失败 reason=missing token_present=False device_id_set=True' not in x for x in selected),'exception_types':dict(collections.Counter(re.findall(r'\b([A-Za-z_][A-Za-z_0-9]*(?:Error|Exception))\b','\n'.join(selected))))}
 out[name]={'status':a['pm2_env']['status'],'restarts':a['pm2_env'].get('restart_time'),'logs':logs}
result={'at':time.time(),'since':state['deployed_at'],'aggregates':out,'limitations':'Read-only log aggregate; no live authenticated hardware traffic generated. Health probes intentionally use invalid credentials; no dialogue or credentials exported.'};(S/'production-log-audit.json').write_text(json.dumps(result,indent=2)); print(json.dumps(result))
