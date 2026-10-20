"""Actual production handler in an isolated process, read-only live MCP only."""
import ast,json,os
from pathlib import Path
import qwen_paired_tool_test_20261006 as paired

model=os.environ['PAIRED_MODEL']
assert model in paired.MODELS
out=paired.OUT
system=json.loads(paired.PACK.read_text())['cases'][0]['initial_messages'][0]['content']
# Live tools return the real clock; the fixed test clock is only for the paired
# synthetic-receipt benchmark. Both live runs use exactly this same system.
system=system.split('\n\n[本轮可信验收时钟]')[0]
source=(out/'complete_chat_mcp_acceptance.py').read_text()
def replace_once(before,after):
    global source
    assert source.count(before)==1, before
    source=source.replace(before,after)

replace_once("os.environ['CANDIDATE_RUNTIME']='1'", "os.environ.pop('CANDIDATE_RUNTIME',None)")
replace_once("exec(compile(s,'<bootstrap>','exec'));provider.client.close()", "exec(compile(s,'<bootstrap>','exec'));provider.client.close();prompt=TEST_PROMPT;paired.install_guard()")
replace_once(" h.config['conversation_validation']={'semantic_enabled':True,'model_names':['qwen3.8-max']}\n",'')
replace_once("h.llm=LLMProvider(dict(llm,model_name='qwen3.8-max',temperature=0.3,timeout=45,max_tokens=250))", "h.llm,native_capture=paired.provider(TEST_MODEL)")
replace_once("original=h.llm.client.chat.completions.create", "original=h.llm._create_with_retry")
replace_once("h.llm.client.chat.completions.create=capture", "h.llm._create_with_retry=capture")
replace_once("'core/connection.py','core/utils/conversation_turn.py','core/utils/conversation_guidance.py'", "'core/connection.py','core/utils/prompt_manager.py','core/utils/conversation_guidance.py'")
replace_once("report={'hardware_writes':0,'physical_test':False,'cases':[],'success':False}", "report={'model':TEST_MODEL,'temperature':0.4,'enable_thinking':False,'semantic_validation':False,'hardware_writes':0,'customer_writes':0,'physical_test':False,'system_sha256':paired.sha(TEST_PROMPT),'cases':[],'success':False}")
extra_tree=ast.parse((out/'prompt_only_mcp_comparison.py').read_text())
extra=next(ast.literal_eval(n.value) for n in extra_tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='extra' for t in n.targets))
replace_once('import os,json,asyncio,time','import os,json,asyncio,time,re')
replace_once("  report['success']=all(r['success'] for r in report['cases'])", extra+"\n  report['success']=all(r['success'] for r in report['cases']);report['reasoning_chars']=native_capture['reasoning_chars'];report['response_models']=sorted(native_capture['response_models']);report['api_errors']=native_capture['api_errors'];report['tool_catalog_sha256']=paired.sha(definitions)")
os.environ['CHAT_REPORT']='qwen-paired-live-'+model+'-20261006'
scope=dict(vars(paired.old),paired=paired,TEST_MODEL=model,TEST_PROMPT=system)
exec(compile(source,'<isolated-paired-live-handler>','exec'),scope)
