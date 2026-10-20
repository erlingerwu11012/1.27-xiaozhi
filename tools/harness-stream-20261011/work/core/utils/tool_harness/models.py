from typing import Any,Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator,field_validator

class Step(BaseModel):
    model_config=ConfigDict(extra='forbid')
    id:str=Field(min_length=1,max_length=32)
    tool:str=Field(min_length=1,max_length=128)
    arguments:dict[str,Any]=Field(default_factory=dict)
    depends_on:list[str]=Field(default_factory=list,max_length=8)
    relative:int|None=Field(default=None,strict=True)
    extreme:Literal['minimum','maximum']|None=None

class TaskUpdate(BaseModel):
    model_config=ConfigDict(extra='forbid')
    target_tool:str=Field(max_length=128)
    parameters:dict[str,Any]=Field(default_factory=dict)
    missing_fields:list[str]=Field(default_factory=list,max_length=32)

class Decision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    mode:Literal['chat','clarify','operate','continue','retrieve']
    reply:str=Field(default='',max_length=4000)
    goal:str=Field(default='',max_length=600)
    steps:list[Step]=Field(default_factory=list,max_length=8)
    finished:bool=True
    task_action:Literal['none','resume','new','cancel']='none'
    authorized_writes:list[str]=Field(default_factory=list,max_length=8)
    retrieval_query:str=Field(default='',max_length=600)
    task_update:TaskUpdate|None=None
    @field_validator('retrieval_query',mode='before')
    @classmethod
    def empty_retrieval(cls,value):
        return '' if value is None else value
    @model_validator(mode='after')
    def consistent(self):
        if self.mode in {'chat','clarify','retrieve'} and self.steps:raise ValueError('non-operation cannot have steps')
        if self.mode=='retrieve' and (not self.retrieval_query.strip() or self.authorized_writes):raise ValueError('retrieval_requires_capability_without_write')
        if self.mode!='retrieve' and self.retrieval_query:raise ValueError('unexpected_retrieval_query')
        if self.mode=='clarify' and not self.reply.strip():raise ValueError('clarification_requires_question')
        if self.mode=='operate' and not self.steps:raise ValueError('operation needs steps')
        seen=set()
        for step in self.steps:
            if step.id in seen or any(x not in seen for x in step.depends_on):raise ValueError('duplicate or forward dependency')
            seen.add(step.id)
            if step.relative is not None and step.extreme is not None:raise ValueError('relative and extreme conflict')
        return self

    @classmethod
    def output_schema(cls):
        # Remote structured decoders may omit fields with Python defaults.
        # Require the envelope and step fields remotely, while retaining local
        # defaults for deterministic planners and existing regression fixtures.
        schema=cls.model_json_schema()
        schema['required']=list(schema['properties'])
        schema['$defs']['Step']['required']=list(schema['$defs']['Step']['properties'])
        return schema

class StepResult(BaseModel):
    state:Literal['completed','accepted','failed','unknown','blocked']
    tool:str
    call_id:str
    arguments:dict[str,Any]
    reply:str
    payload:Any=None
    error:str=''
    intermediate:bool=False

class OperationOutcome(BaseModel):
    mode:str
    reply:str
    results:list[StepResult]=Field(default_factory=list)
    model_calls:int=0
    repairs:int=0
    catalog_version:str=''
    error:str=''
    interrupted:bool=False
    validation_failures:list[dict[str,Any]]=Field(default_factory=list)

class OperationPlan(BaseModel):
    request_id:str
    scope:str
    catalog_version:str
    goal:str
    steps:list[Step]
