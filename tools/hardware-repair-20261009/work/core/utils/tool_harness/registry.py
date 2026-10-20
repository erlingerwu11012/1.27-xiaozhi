"""Authoritative manifest, including unavailable and unaudited capabilities."""
from .contracts import contract

RETIRED={'habit_create':'retired_unbound_gateway_entry','habit_list_manual':'retired_cross_account_list'}
PLUGIN={'get_lunar','handle_exit_intent','memory_search','memory_forget','memory_correct','get_weather','get_news_from_newsnow'}
SERVER_MCP={'get_world_time','random_decision','add_reminder','habit_create','habit_list_manual'}

def binding(definition):
    source=getattr(definition,'tool_type',getattr(definition,'source','unknown'))
    return getattr(source,'value',str(source))

def audited_source(name,definition):
    expected='server_plugin' if name in PLUGIN else 'server_mcp' if name in SERVER_MCP else 'device_mcp'
    return contract(name).known and binding(definition)==expected
def manifest(manager):
    manager.refresh_tools()
    ambiguous=set(manager.get_ambiguous_tool_names())
    rows=[]
    for name,definition in sorted(manager.get_all_tools().items()):
        c=contract(name)
        source=binding(definition)
        rows.append({'name':name,'source':source,'raw_name':getattr(definition,'original_name',name),
          'schema':definition.description['function'].get('parameters',{}),
          'purpose':definition.description['function'].get('description',''),
          'prerequisites':list(c.prerequisites),'authority':'existing executor identity and account guards',
          'write':c.write,'timeout':c.timeout,'retry':c.retry,
          'completion_adapter':name if c.known else None,
          'availability':RETIRED.get(name) or ('ambiguous_name' if name in ambiguous else 'available' if audited_source(name,definition) else 'unaudited_contract_or_source')})
    return rows
