"""Ephemeral task continuation, scoped to the authenticated connection and owner."""
from dataclasses import dataclass,field
import time,uuid

@dataclass
class TaskContext:
    account:str
    device:str
    session:str
    owner:object
    original:str
    question:str
    goal:str=''
    created:float=field(default_factory=time.monotonic)
    task_id:str=field(default_factory=lambda:uuid.uuid4().hex)
    parameters:dict=field(default_factory=dict)
    sources:dict=field(default_factory=dict)
    supplements:dict=field(default_factory=dict)
    state:str='awaiting_parameters'
    write_tools:list=field(default_factory=list)

    def visible(self,conn,actor,now=None):
        now=time.monotonic() if now is None else now
        return (now-self.created<90 and self.state in {'awaiting_parameters','paused_identity'}
            and self.account==str(getattr(conn,'account_id','') or getattr(actor,'account_id',''))
            and self.device==getattr(conn,'device_id','') and self.session==getattr(conn,'session_id','')
            and actor is not None and actor.eligible and self.owner==actor.key)

    def context(self):
        return {'id':self.task_id,'original_request':self.original,'question':self.question,
                'goal':self.goal,'confirmed_parameters':self.parameters,'parameter_sources':self.sources,
                'authorized_write_tools':self.write_tools,
                'remaining_seconds':max(0,int(90-(time.monotonic()-self.created)))}

    def supplement(self,query,turn):
        # Immutable origin and expiry; the latest supplied value wins only for its field.
        self.supplements[str(turn)]=query
        self.sources['latest_supplement']={'turn':str(turn),'text':query}
        return self.original+'\n[该任务已收到的补充，最新明确改口优先]\n'+'\n'.join(self.supplements.values())
