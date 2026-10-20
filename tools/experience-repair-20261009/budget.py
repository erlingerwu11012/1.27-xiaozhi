"""Reserve before execution; failures consume budget too."""
import json, os, sqlite3, time
from pathlib import Path
LIMITS={'case':4300,'model':2200,'tts':12,'vision':6}
class Budget:
    def __init__(self,path=None):
        self.path=Path(path or os.environ.get('EXPERIENCE_TEST_BUDGET','budget.sqlite3'))
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.path) as c:c.execute('CREATE TABLE IF NOT EXISTS charges(id INTEGER PRIMARY KEY,kind TEXT,label TEXT,created REAL,metadata TEXT)')
    def reserve(self,kind,label):
        if kind not in LIMITS:raise ValueError('unknown_budget_kind')
        with sqlite3.connect(self.path,timeout=30) as c:
            c.execute('BEGIN IMMEDIATE')
            used=c.execute('SELECT count(*) FROM charges WHERE kind=?',(kind,)).fetchone()[0]
            if used>=LIMITS[kind]:raise RuntimeError('budget_exhausted:'+kind)
            return c.execute('INSERT INTO charges(kind,label,created) VALUES(?,?,?)',(kind,label,time.time())).lastrowid
    def finish(self,charge,metadata):
        with sqlite3.connect(self.path) as c:c.execute('UPDATE charges SET metadata=? WHERE id=?',(json.dumps(metadata,ensure_ascii=False),charge))
    def report(self):
        with sqlite3.connect(self.path) as c:used=dict(c.execute('SELECT kind,count(*) FROM charges GROUP BY kind'))
        return {k:{'used':used.get(k,0),'limit':v} for k,v in LIMITS.items()}
