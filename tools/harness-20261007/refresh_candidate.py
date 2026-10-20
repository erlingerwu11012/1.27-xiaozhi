from rollout import *
p=STAGE/'frozen-20261008-budget-delta';code,m=validate_frozen(p)
drift=[str(f.relative_to(p/'work')) for f in (p/'work').rglob('*.py') if str(f.relative_to(p/'work')) not in m and (not (ROOT/f.relative_to(p/'work')).is_file() or digest(f)!=digest(ROOT/f.relative_to(p/'work')))]
print(json.dumps({'unrelated_source_drift':drift,'code_hash':code}),flush=True)
if drift:raise RuntimeError('source_drift')
stop_isolated()
print(run([PYTHON,str(STAGE/'launch_candidate.py'),str(p/'work')]),flush=True)
print(json.dumps(wait_ready()),flush=True)
