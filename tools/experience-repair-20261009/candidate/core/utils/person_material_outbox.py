"""A durable local delivery queue, not a local long-term memory store."""
import asyncio
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path


class MaterialOutbox:
    def __init__(self,path=None):
        self.path=path or os.getenv("PERSON_MATERIAL_OUTBOX","data/person-material-outbox.sqlite3")
        self.lock=threading.RLock()
        self._pumping=set()

    @contextmanager
    def connect(self):
        Path(self.path).parent.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(self.path,timeout=5)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("CREATE TABLE IF NOT EXISTS material(event TEXT PRIMARY KEY,account TEXT,person TEXT,generation INTEGER,actor TEXT,kind TEXT,content TEXT)")
        try:
            with db:
                yield db
        finally:
            db.close()

    def enqueue(self,actor,kind,content,event):
        if not actor.eligible:return False
        if len(content)>65536:raise ValueError("material_too_large")
        with self.lock,self.connect() as db:
            db.execute("INSERT OR IGNORE INTO material VALUES(?,?,?,?,?,?,?)",(event,actor.account_id,actor.person_id,actor.generation,json.dumps(actor.payload(),ensure_ascii=False),kind,content))
        return True

    def suppress(self,actor,match):
        with self.lock,self.connect() as db:
            if match=="*":db.execute("DELETE FROM material WHERE account=? AND person=? AND generation=?",(actor.account_id,actor.person_id,actor.generation))
            else:db.execute("DELETE FROM material WHERE account=? AND person=? AND generation=? AND instr(content,?)>0",(actor.account_id,actor.person_id,actor.generation,match))

    def retire(self,account,person,generation):
        with self.lock,self.connect() as db:
            db.execute("DELETE FROM material WHERE account=? AND person=? AND generation=?",(str(account),person,generation))

    async def pump(self,conn):
        from config.manage_api_client import ManageApiClient
        account=str((conn.config or {}).get("sys_user_id") or "")
        if not account or account in self._pumping:return
        self._pumping.add(account)
        try:
            client=ManageApiClient(conn.config)
            with self.lock,self.connect() as db:
                rows=db.execute("SELECT event,actor,kind,content FROM material WHERE account=? ORDER BY rowid LIMIT 50",(account,)).fetchall()
            for event,actor,kind,content in rows:
                try:
                    response=await client._async_client.post("person-memory/internal/material",json={"actor":json.loads(actor),"eventId":event,"kind":kind,"content":content},timeout=2)
                    response.raise_for_status()
                    result=response.json()
                    permanent=any(word in str(result.get("msg") or "") for word in ("人物目录已变更","默认身份已失效","声纹绑定已失效","设备归属已变更","当前智能体未开启长期记忆","记忆实体已失效"))
                    if result.get("code")==0 or permanent:
                        with self.lock,self.connect() as db:db.execute("DELETE FROM material WHERE event=?",(event,))
                    else:break
                except Exception:break
        finally:self._pumping.discard(account)


material_outbox=MaterialOutbox()
