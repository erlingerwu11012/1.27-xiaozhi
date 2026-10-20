"""Authoritative manifest, including unavailable and unaudited capabilities."""
from .contracts import contract
from .declarations import DECLARATIONS

RETIRED={'habit_create':'retired_unbound_gateway_entry','habit_list_manual':'retired_cross_account_list'}
from core.providers.tools.retired_tools import RETIRED_TOOL_NAMES
RETIRED.update({name:'retired_maintenance_endpoint' for name in RETIRED_TOOL_NAMES})
PLUGIN={'get_lunar','handle_exit_intent','memory_search','memory_add','memory_forget','memory_correct','get_weather','get_news_from_newsnow'}
SERVER_MCP={'get_world_time','random_decision','add_reminder','habit_create','habit_list_manual'}

def binding(definition):
    source=getattr(definition,'tool_type',getattr(definition,'source','unknown'))
    return getattr(source,'value',str(source))

def audited_source(name,definition):
    expected=DECLARATIONS.get(name,{}).get('source')
    return name not in RETIRED and contract(name).known and binding(definition)==expected
def manifest(manager):
    manager.refresh_tools()
    ambiguous=set(manager.get_ambiguous_tool_names())
    rows=[]
    discovered=dict(manager.get_all_tools())
    for executor in manager.executors.values():
        get=getattr(executor,'get_tools',None)
        if not callable(get):continue
        try:
            for name,definition in get().items():discovered.setdefault(name,definition)
        except Exception:continue
    for name,definition in sorted(discovered.items()):
        c=contract(name)
        source=binding(definition)
        rows.append({'name':name,'source':source,'raw_name':getattr(definition,'original_name',name),
          'schema':definition.description['function'].get('parameters',{}),
          'purpose':definition.description['function'].get('description',''),
          'prerequisites':list(c.prerequisites),'authority':'existing executor identity and account guards',
          'write':c.write,'timeout':c.timeout,'retry':c.retry,
          'completion_adapter':DECLARATIONS.get(name,{}).get('receipt_checker'),
          'availability':RETIRED.get(name) or ('ambiguous_name' if name in ambiguous else 'available' if audited_source(name,definition) else 'unaudited_contract_or_source')})
    for name,declaration in sorted(DECLARATIONS.items()):
        if name in discovered:continue
        rows.append({'name':name,'source':declaration['source'],'purpose':declaration['label'],
                     'schema':None,'write':declaration['write'],'prerequisites':declaration['prerequisites'],
                     'completion_adapter':declaration['receipt_checker'],
                     'availability':RETIRED.get(name) or ('device_not_supported' if declaration['source']=='device_mcp' else 'not_connected')})
    return sorted(rows,key=lambda row:row['name'])
