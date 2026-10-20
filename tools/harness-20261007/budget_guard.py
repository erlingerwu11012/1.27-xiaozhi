"""Test-only global row/request spending guard. Never imported by production."""
import os,sqlite3,time
from pathlib import Path
PATH=Path(os.environ.get('HARNESS_TEST_BUDGET_PATH','/root/prjs/tmp/harness-20261007/budget-resume-20261008.sqlite3'))
class BudgetExceeded(RuntimeError):pass

def initialize(path=None,prior_rows=904,request_limit=1000,row_limit=2000):
    p=Path(path or PATH);p.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(p,timeout=30) as db:
        db.execute('CREATE TABLE IF NOT EXISTS counters(kind TEXT PRIMARY KEY,used INTEGER NOT NULL,cap INTEGER NOT NULL)')
        db.execute('INSERT OR IGNORE INTO counters VALUES(?,?,?)',('requests',0,request_limit))
        db.execute('INSERT OR IGNORE INTO counters VALUES(?,?,?)',('records',prior_rows,row_limit))
    os.chmod(p,0o600)

def reserve(kind,path=None):
    p=Path(path or PATH)
    if not p.exists():initialize(p)
    with sqlite3.connect(p,timeout=30) as db:
        db.execute('BEGIN IMMEDIATE')
        used,cap=db.execute('SELECT used,cap FROM counters WHERE kind=?',(kind,)).fetchone()
        if used>=cap:raise BudgetExceeded('test_budget_exhausted:'+kind)
        db.execute('UPDATE counters SET used=used+1 WHERE kind=?',(kind,))
    return used+1

def snapshot(path=None):
    p=Path(path or PATH)
    if not p.exists():initialize(p)
    with sqlite3.connect(p,timeout=30) as db:return {k:{'used':n,'limit':c} for k,n,c in db.execute('SELECT kind,used,cap FROM counters')}

def reserve_record():return reserve('records')

def attach(provider):
    initialize()
    def before(request):
        if request.url.path.endswith('/chat/completions'):reserve('requests')
    provider.client._client.event_hooks.setdefault('request',[]).append(before)
