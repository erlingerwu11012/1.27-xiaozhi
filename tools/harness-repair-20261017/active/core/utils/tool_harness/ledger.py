import hashlib,json,os,sqlite3,threading,time
from pathlib import Path

class Ledger:
    """Durable dispatch markers; no dialogue, raw arguments or credentials."""
    def __init__(self,path):
        self.lock=threading.RLock();self.path=path
        if path!=':memory:':
            p=Path(path);p.parent.mkdir(parents=True,exist_ok=True);os.chmod(p.parent,0o700)
        self.db=sqlite3.connect(path,check_same_thread=False,timeout=5)
        if path!=':memory:':os.chmod(path,0o600)
        self.db.execute('PRAGMA journal_mode=WAL')
        if path!=':memory:':
            for suffix in ('','-wal','-shm'):
                if os.path.exists(path+suffix):os.chmod(path+suffix,0o600)
        self.db.execute('CREATE TABLE IF NOT EXISTS dispatch (scope TEXT, turn TEXT, fingerprint TEXT, call_id TEXT, tool TEXT, state TEXT, updated REAL, PRIMARY KEY(scope,turn,fingerprint))')
        if 'catalog_version' not in {r[1] for r in self.db.execute('PRAGMA table_info(dispatch)')}:
            self.db.execute("ALTER TABLE dispatch ADD COLUMN catalog_version TEXT DEFAULT ''")
        self.db.execute("UPDATE dispatch SET state='unknown' WHERE state='sent'");self.db.commit()
    @staticmethod
    def fingerprint(tool,args):
        return hashlib.sha256(json.dumps([tool,args],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    def reserve(self,scope,turn,tool,args,call_id,catalog_version=''):
        fp=self.fingerprint(tool,args)
        with self.lock:
            cursor=self.db.execute('INSERT OR IGNORE INTO dispatch(scope,turn,fingerprint,call_id,tool,state,updated,catalog_version) VALUES(?,?,?,?,?,?,?,?)',(scope,turn,fp,call_id,tool,'sent',time.time(),catalog_version));self.db.commit()
            return cursor.rowcount==1
    def finish(self,scope,turn,tool,args,state):
        with self.lock:
            self.db.execute('UPDATE dispatch SET state=?,updated=? WHERE scope=? AND turn=? AND fingerprint=?',(state,time.time(),scope,turn,self.fingerprint(tool,args)));self.db.commit()
    def lookup(self,scope,turn,tool,args):
        with self.lock:
            row=self.db.execute('SELECT call_id,state,catalog_version FROM dispatch WHERE scope=? AND turn=? AND fingerprint=?',(scope,turn,self.fingerprint(tool,args))).fetchone()
            return row
    def close(self):self.db.close()

_instances={}
_lock=threading.Lock()
def get_ledger(path):
    with _lock:
        if path not in _instances:_instances[path]=Ledger(path)
        return _instances[path]
