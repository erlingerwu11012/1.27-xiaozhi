from pathlib import Path
p=Path('tools/experience-repair-20261009/release.py');s=p.read_text(encoding='utf-8-sig').replace('==303','==304').replace("'cases':len(r)","'cases':len(r)")
s=s.replace("if drift:raise RuntimeError('production_source_drift:'+','.join(drift))","""if drift:raise RuntimeError('production_source_drift:'+','.join(drift))
 unrelated=[n for n,h in baseline.items() if n.endswith('.py') and n not in names and not n.startswith('test/') and (not (ROOT/n).is_file() or sha(ROOT/n)!=h)]
 if unrelated:raise RuntimeError('unrelated_source_drift:'+','.join(unrelated))""")
s=s.replace("for n in ['http-api-results.json','live-query-note-results.json']:","for n in ['http-api-results.json','live-query-note-results.json','query-lifecycle-replay-summary.json']:")
# Record billing origins/key hashes privately; report equality only.
s=s.replace("state={'phase':'prepared'", "billing_names=['HW_BILLING_SERVICE_KEY','HW_BILLING_GATEWAY_ORIGIN','HW_BILLING_AUDIO_GATEWAY_ORIGIN']\n billing_hashes={n:hashlib.sha256(envs['xiaozhi-server'].get(n,'').encode()).hexdigest() for n in billing_names}\n state={'billing_env_hashes':billing_hashes,'phase':'prepared'")
s=s.replace("out['processes_healthy']=all(a['pm2_env']['status']=='online' and a['pm2_env'].get('restart_time',0)==0 for a in proc)","out['processes_healthy']=all(a['pm2_env']['status']=='online' and a['pm2_env'].get('restart_time',0)==0 for a in proc)\n env=env_of(app(s['new']['xiaozhi-server']));out['billing_env_matches']=all(hashlib.sha256(env.get(n,'').encode()).hexdigest()==h for n,h in s['billing_env_hashes'].items())")
s=s.replace("'processes_healthy','ledger_private']","'processes_healthy','ledger_private','billing_env_matches']")
p.write_text(s,encoding='utf-8')
