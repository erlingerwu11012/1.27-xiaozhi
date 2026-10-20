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
    target_tool:str=''
    missing_fields:list=field(default_factory=list)

    def visible(self,conn,actor,now=None):
        now=time.monotonic() if now is None else now
        return (now<self.created+90 and self.state in {'awaiting_parameters','paused_identity'}
            and self.account==str(getattr(conn,'account_id','') or getattr(actor,'account_id',''))
            and self.device==getattr(conn,'device_id','') and self.session==getattr(conn,'session_id','')
            and actor is not None and actor.eligible and self.owner==actor.key)

    def context(self):
        return {'id':self.task_id,'original_request':self.original,'question':self.question,
                'goal':self.goal,'confirmed_parameters':self.parameters,'parameter_sources':self.sources,
                'authorized_write_tools':self.write_tools,
                'target_tool':self.target_tool,'missing_fields':self.missing_fields,
                'remaining_seconds':max(0,int(90-(time.monotonic()-self.created)))}

    def update(self,patch,tools,turn,text):
        from jsonschema import Draft202012Validator
        name=patch.target_tool
        if name not in tools:raise ValueError('task_target_unavailable')
        if self.target_tool and name!=self.target_tool:raise ValueError('task_target_changed_without_new_task')
        schema=tools[name].description['function']['parameters']
        properties=schema.get('properties',{})
        if set(patch.parameters)-set(properties) or set(patch.missing_fields)-set(properties):raise ValueError('task_field_unknown')
        for key,value in patch.parameters.items():Draft202012Validator(properties[key]).validate(value)
        self.target_tool=name
        self.parameters.update(patch.parameters)
        for key in patch.parameters:self.sources[key]={'turn':str(turn),'text':text}
        self.missing_fields=[key for key in patch.missing_fields if key not in self.parameters]

    def supplement(self,query,turn):
        # Immutable origin and expiry; the latest supplied value wins only for its field.
        self.supplements[str(turn)]=query
        self.sources['latest_supplement']={'turn':str(turn),'text':query}
        return self.original+'\n[该任务已收到的补充，最新明确改口优先]\n'+'\n'.join(self.supplements.values())
