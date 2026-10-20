"""Fresh hard limits for this approved plan, reserved before every attempt."""
import json,os,sqlite3,time
from pathlib import Path
# Independent budget approved 2026-10-13; previous ledger is never reused.
LIMITS={'case':800,'model':700,'tts':12,'vision':0}
class Budget:
 def __init__(self,path=None):
  self.path=Path(path or os.environ.get('EXPERIENCE_TEST_BUDGET',Path(__file__).parent/'budget.sqlite3'))
  self.path.parent.mkdir(parents=True,exist_ok=True)
  with sqlite3.connect(self.path) as c:c.execute('CREATE TABLE IF NOT EXISTS charges(id INTEGER PRIMARY KEY,kind TEXT,label TEXT,phase TEXT,created REAL,metadata TEXT)')
 def reserve(self,kind,label):
  if kind not in LIMITS:raise ValueError('unknown_budget_kind')
  phase=os.environ.get('MODEL_TEST_PHASE') if kind=='model' and os.environ.get('MODEL_TEST_PHASE') else os.environ.get('TEST_PHASE','development')
  with sqlite3.connect(self.path,timeout=30) as c:
   c.execute('BEGIN IMMEDIATE')
   used=c.execute('SELECT count(*) FROM charges WHERE kind=?',(kind,)).fetchone()[0]
   if used>=LIMITS[kind]:raise RuntimeError('budget_exhausted:'+kind)
   if kind=='model' and phase!='final' and c.execute("SELECT count(*) FROM charges WHERE kind='model' AND phase<>'final'").fetchone()[0]>=180:raise RuntimeError('development_model_budget_exhausted')
   if kind=='tts':
    cap={'baseline':4,'candidate':6,'repair':2}.get(phase)
    if cap is None:raise RuntimeError('tts_phase_required')
    if c.execute("SELECT count(*) FROM charges WHERE kind='tts' AND phase=?",(phase,)).fetchone()[0]>=cap:raise RuntimeError('tts_phase_budget_exhausted')
   return c.execute('INSERT INTO charges(kind,label,phase,created) VALUES(?,?,?,?)',(kind,label,phase,time.time())).lastrowid
 def finish(self,charge,metadata):
  with sqlite3.connect(self.path) as c:c.execute('UPDATE charges SET metadata=? WHERE id=?',(json.dumps(metadata,ensure_ascii=False),charge))
 def report(self):
  with sqlite3.connect(self.path) as c:used=dict(c.execute('SELECT kind,count(*) FROM charges GROUP BY kind'))
  return {k:{'used':used.get(k,0),'limit':v} for k,v in LIMITS.items()}
