import copy,json,types,uuid
from unittest.mock import MagicMock
from bootstrap import system_prompt
from test_support import PACK,SimulationManager
from core.connection import ConnectionHandler
from core.providers.tools.unified_tool_handler import UnifiedToolHandler
from core.utils.person_identity import PersonTurn,activate,deactivate
from core.utils.tool_harness.contracts import receipt
from core.utils.tool_harness.models import OperationOutcome

class ProviderSpy:
    def __init__(self,provider):self.provider=provider;self.events=[]
    def __getattr__(self,k):return getattr(self.provider,k)
    def decision(self,messages):
        import time
        start=time.monotonic();event={'kind':'decision'};self.events.append(event)
        try:
            value=self.provider.decision(messages);event['decision']=value
            return value
        except Exception as exc:
            event['error_type']=type(exc).__name__;event['error_kind']='validation' if isinstance(exc,ValueError) else 'api';raise
        finally:
            event['elapsed_ms']=round((time.monotonic()-start)*1000,2);event['usage']=self.provider.last_usage
    def response_with_functions(self,*args,**kw):
        import time
        start=time.monotonic();event={'kind':'native','content':'','tool_fragments':[]};self.events.append(event)
        for text,calls in self.provider.response_with_functions(*args,**kw):
            event['content']+=text or ''
            if text and '【服务暂时无法响应' in text:
                event['error_type']='ProviderFallback';event['error_kind']='api'
            if calls:event['tool_fragments'].extend([c.model_dump() for c in calls])
            yield text,calls
        event['elapsed_ms']=round((time.monotonic()-start)*1000,2);event['usage']=self.provider.last_usage

def make_baseline(provider,cfg,loop,harness=False):
    config=copy.deepcopy(cfg)
    config.update({'exit_commands':cfg.get('exit_commands',['再见']),'harness':{'enabled':harness},'operation_control':{'enabled':True},'read_config_from_api':False})
    spy=ProviderSpy(provider)
    c=ConnectionHandler(config,None,None,spy,None,None)
    c.loop=loop;c.device_id='SIMULATION-NO-HARDWARE';c.intent_type='function_call';c.client_ip=None
    c.person_turn=PersonTurn('simulation-account','person-a',1,1,'personal','matched','sim-turn',c.device_id,'sim-agent',1)
    c.listen_epoch=1;c._pipeline_v2_frozen=True;c._official_tts_enabled=lambda:True
    c.harness_test_clock=PACK['clock']
    c.speech=[];c.enqueue_tts=lambda dto:c.speech.append(str(dto.content_detail)) if getattr(getattr(dto,'content_type',None),'name','')=='TEXT' else True
    c.mcp_client=types.SimpleNamespace(ready=True,closed=False,capabilities={'experimental':{'personBehavior':2,'personalIdentity':2,'identityCleanup':2}})
    c.func_handler=UnifiedToolHandler(c)
    simulation=SimulationManager();simulation.conn=c
    manager=c.func_handler.tool_manager
    manager.refresh_tools=lambda:None;manager._invalidate_cache=lambda:None
    manager.get_all_tools=simulation.get_all_tools;manager.get_ambiguous_tool_names=simulation.get_ambiguous_tool_names
    manager._execute_tool=simulation._execute_tool
    c.func_handler.select_candidate_functions=lambda *a,**k:None
    c.dialogue.update_system_message(system_prompt(cfg))
    if harness:
        from core.utils.tool_harness.runtime import Harness
        from core.utils.tool_harness.ledger import Ledger
        c._full_tool_harness=Harness(c,ledger=Ledger(':memory:'))
    return c,simulation,spy

def run_baseline(c,m,spy,query):
    call_start=len(m.calls);speech_start=len(c.speech);event_start=len(spy.events)
    token=activate(c,c.person_turn)
    try:c.chat(query)
    finally:deactivate(token)
    if c.config['harness']['enabled']:
        return c._full_tool_harness.last_outcome
    results=[]
    for index,call in enumerate(m.calls[call_start:],call_start):
        # Re-render only recorded simulator responses; no executor is repeated.
        body=call.get('receipt')
        if body is not None:
            from plugins_func.register import Action,ActionResponse
            r=ActionResponse(Action.REQLLM,result=body)
            if call['tool']=='add_reminder':r.operation_state='completed'
            results.append(receipt(call['tool'],call['arguments'],r,'baseline-'+str(index)))
    # Current-turn receipts and speech only; keep the actual history intact.
    return OperationOutcome(mode='operate' if m.calls[call_start:] else 'chat',reply=''.join(c.speech[speech_start:]),results=results,model_calls=len(spy.events)-event_start)
