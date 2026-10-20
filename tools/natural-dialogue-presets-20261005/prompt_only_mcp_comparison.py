"""Same formal execution/receipt protection, two prompt variants, no chat gate."""
import ast,os
from pathlib import Path
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
os.environ.pop('CANDIDATE_RUNTIME',None)
prefix=(OUT/'runtime_production_acceptance.py').read_text().split('async def runtime_mcp():')[0]
exec(compile(prefix,'<formal-mcp-bootstrap>','exec'));provider.client.close()
import core.utils.prompt_manager as pm
original=pm.NATURAL_CONVERSATION_GUIDANCE
tree=ast.parse(Path('/root/prjs/tmp/complete-chat-review-20261006/main/xiaozhi-server/core/utils/conversation_guidance.py').read_text(encoding='utf-8-sig'))
new=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
         and any(isinstance(t,ast.Name) and t.id=='NATURAL_CONVERSATION_GUIDANCE' for t in n.targets))
source=(OUT/'complete_chat_mcp_acceptance.py').read_text()
source=source.replace("os.environ['CANDIDATE_RUNTIME']='1'", "os.environ.pop('CANDIDATE_RUNTIME',None)")
source=source.replace(" h.config['conversation_validation']={'semantic_enabled':True,'model_names':['qwen3.8-max']}\n",'')
source=source.replace("dict(llm,model_name='qwen3.8-max',temperature=0.3,timeout=45,max_tokens=250)","dict(llm,timeout=45,max_tokens=450)")
source=source.replace("'core/connection.py','core/utils/conversation_turn.py','core/utils/conversation_guidance.py'", "'core/connection.py','core/utils/prompt_manager.py','core/utils/conversation_guidance.py'")
extra="""
  negative_samples=['打开摄像头预览','把音量调到三十','查询设备当前音量',
                    '不要打开摄像头，只解释预览和拍照的区别。',
                    '不用查时间，我只是说东京跟我们有时差。']
  for text in negative_samples:
   h.tts_events.clear();events.clear();calls.clear()
   ok=await asyncio.to_thread(lambda:h.chat(text,_identity=h.actor))
   spoken=''.join(str(e.content_detail) for e in h.tts_events if e.content_type==ContentType.TEXT)
   # The current real catalog has no hardware camera/volume tools. A missing
   # capability is not permission to substitute a different tool.
   success=bool(ok and spoken and not events and not re.search(r'已打开|已经打开|打开了|已调到|已经调到|已设置',spoken))
   row={'user':text,'spoken':spoken,'tool_events':list(events),'primary_requests':list(calls),
        'case_type':'absent_capability_or_non_operation','success':success}
   report['cases'].append(row);print(json.dumps(row,ensure_ascii=False),flush=True)
"""
source=source.replace('import os,json,asyncio,time','import os,json,asyncio,time,re')
source=source.replace("  report['success']=all(r['success'] for r in report['cases'])", extra+"\n  report['success']=all(r['success'] for r in report['cases'])")
source=source.replace(" report={'hardware_writes':0,'physical_test':False,'cases':[],'success':False}",
    " report={'hardware_writes':0,'physical_test':False,'cases':[],'success':False,'semantic_validation':False,'prompt_variant':VARIANT}")
original_runner=source
all_results=[]
for variant,guidance in [('current',original),('prompt_only',new)]:
    pm.NATURAL_CONVERSATION_GUIDANCE=guidance
    rebuilt=PromptManager({'system_base_prompt':base.get('system_base_prompt',''),'language':'中文'},logger=MagicMock()).build_enhanced_prompt_v2(PERSONA,'synthetic-prompt-only',device_name='小智',user_nickname='主人',official_enhanced=True)
    assert guidance.strip() in rebuilt
    # Bootstrap normally builds the old prompt; replace only that in-process
    # string before each actual handler is created. Source is not modified.
    run_source=original_runner.replace('exec(compile(s,\'<bootstrap>\',\'exec\'));provider.client.close()',
        "exec(compile(s,'<bootstrap>','exec'));provider.client.close();prompt="+repr(rebuilt))
    os.environ['CHAT_REPORT']='prompt-only-mcp-'+variant
    VARIANT=variant
    try:exec(compile(run_source,'<formal-prompt-only-mcp>', 'exec'))
    except SystemExit as error:
        if error.code not in (0,None):all_results.append(False)
    else:all_results.append(True)
pm.NATURAL_CONVERSATION_GUIDANCE=original
assert len(all_results)==2
print('both_variants_completed='+str(all(all_results)),flush=True)
