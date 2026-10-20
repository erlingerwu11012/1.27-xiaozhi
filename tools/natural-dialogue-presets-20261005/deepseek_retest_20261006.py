"""Isolated DeepSeek rerun of the paired production-handler evidence tests.

Uses the existing server credential in memory. Never edits production sources,
customer personas, routing, or default model configuration.
"""
import ast
import os
from pathlib import Path

OUT = Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
MODE = os.environ.get('DEEPSEEK_RETEST_MODE', 'chat')
CONFIG = """
llm = dict(llm, model_name='deepseek-flash',
           api_key=sql('SELECT `key` FROM one_api.channels WHERE id=1;').strip(),
           base_url='https://api.deepseek.com', temperature=0.4)
"""

if MODE == 'chat':
    source = (OUT / 'prompt_only_comparison.py').read_text()
    source = source.replace("RESULT=OUT/'prompt-only-comparison.json'",
                            "RESULT=OUT/'deepseek-retest-chat-20261006.json'")
    source = source.replace("new_guidance=constant(", CONFIG + "\nnew_guidance=constant(")
    source = source.replace("variants={'current':original_guidance,'prompt_only':new_guidance}",
                            "variants={'prompt_only':new_guidance}")
    source = source.replace("'planned_turns':400", "'planned_turns':200,'thinking':False,'endpoint':'https://api.deepseek.com'")
    source = source.replace("data['calls']<400", "data['calls']<200")
    source = source.replace("data['calls']==400", "data['calls']==200")
    source = source.replace("response=_create(**params)",
                            "params['extra_body']={'thinking':{'type':'disabled'}}\n            response=_create(**params)")
    source = source.replace("entry['turns'].append(row);save();", "row['context_status']=getattr(h.dialogue.context_window,'last_status',None)\n           row['summary_version']=getattr(h.dialogue.context_window,'version',None)\n           entry['turns'].append(row);save();")
    compile(source, '<deepseek-chat-rerun>', 'exec')
    exec(compile(source, '<deepseek-chat-rerun>', 'exec'))
elif MODE == 'mcp':
    source = (OUT / 'complete_chat_mcp_acceptance.py').read_text()
    source = source.replace("os.environ['CANDIDATE_RUNTIME']='1'", "os.environ.pop('CANDIDATE_RUNTIME',None)")
    source = source.replace("exec(compile(s,'<bootstrap>','exec'));provider.client.close()",
                            "exec(compile(s,'<bootstrap>','exec'));provider.client.close()\n" + CONFIG + """
import ast
import core.utils.prompt_manager as pm
tree=ast.parse(Path('/root/prjs/tmp/complete-chat-review-20261006/main/xiaozhi-server/core/utils/conversation_guidance.py').read_text(encoding='utf-8-sig'))
pm.NATURAL_CONVERSATION_GUIDANCE=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='NATURAL_CONVERSATION_GUIDANCE' for t in n.targets))
prompt=PromptManager({'system_base_prompt':base.get('system_base_prompt',''),'language':'中文'},logger=MagicMock()).build_enhanced_prompt_v2(PERSONA,'synthetic-deepseek-retest',device_name='小智',user_nickname='主人',official_enhanced=True)
""")
    source = source.replace(" h.config['conversation_validation']={'semantic_enabled':True,'model_names':['qwen3.8-max']}\n", '')
    source = source.replace("dict(llm,model_name='qwen3.8-max',temperature=0.3,timeout=45,max_tokens=250)",
                            "dict(llm,timeout=45,max_tokens=450)")
    source = source.replace("'core/connection.py','core/utils/conversation_turn.py','core/utils/conversation_guidance.py'",
                            "'core/connection.py','core/utils/prompt_manager.py','core/utils/conversation_guidance.py'")
    source = source.replace("calls.append({'model':params['model'],'stream':params.get('stream')});return original(**params)",
                            "params['extra_body']={'thinking':{'type':'disabled'}}\n  calls.append({'model':params['model'],'stream':params.get('stream')});return original(**params)")
    extra_tree = ast.parse((OUT / 'prompt_only_mcp_comparison.py').read_text())
    extra = next(ast.literal_eval(n.value) for n in extra_tree.body if isinstance(n,ast.Assign)
                 and any(isinstance(t,ast.Name) and t.id=='extra' for t in n.targets))
    source = source.replace('import os,json,asyncio,time', 'import os,json,asyncio,time,re')
    source = source.replace("  report['success']=all(r['success'] for r in report['cases'])",
                            extra + "\n  report['success']=all(r['success'] for r in report['cases'])")
    os.environ['CHAT_REPORT'] = 'deepseek-retest-mcp-20261006'
    exec(compile(source, '<deepseek-mcp-rerun>', 'exec'))
elif MODE == 'native':
    import asyncio
    import json
    import time
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    bootstrap = (OUT / 'runtime_production_acceptance.py').read_text().split('async def runtime_mcp():')[0]
    exec(compile(bootstrap, '<native-bootstrap>', 'exec'))
    provider.client.close()
    exec(CONFIG)
    import core.utils.prompt_manager as pm

    tree = ast.parse(Path('/root/prjs/tmp/complete-chat-review-20261006/main/xiaozhi-server/core/utils/conversation_guidance.py').read_text(encoding='utf-8-sig'))
    pm.NATURAL_CONVERSATION_GUIDANCE = next(ast.literal_eval(n.value) for n in tree.body
        if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'NATURAL_CONVERSATION_GUIDANCE' for t in n.targets))
    prompt = PromptManager({'system_base_prompt':base.get('system_base_prompt',''),'language':'中文'},logger=MagicMock()).build_enhanced_prompt_v2(PERSONA,'synthetic-deepseek-native',device_name='小智',user_nickname='主人',official_enhanced=True)

    async def native_run():
        settings = json.loads((PROD / 'data/.mcp_server_settings.json').read_text())['mcpServers']
        client = ServerMCPClient(next(c for c in settings.values() if not c.get('disabled', False)))
        provider = LLMProvider(dict(llm, timeout=45, max_tokens=450))
        original = provider.client.chat.completions.create
        usage = []
        def capture(**params):
            params['extra_body'] = {'thinking':{'type':'disabled'}}
            params['stream_options'] = {'include_usage':True}
            for chunk in original(**params):
                if chunk.usage:
                    usage.append(chunk.usage.model_dump())
                yield chunk
        provider.client.chat.completions.create = capture
        result = {'model':'deepseek-flash','thinking':False,'hardware_writes':0,'cases':[]}
        def stream(messages, tools):
            start = time.perf_counter()
            calls = {}
            text = []
            for content, chunks in provider.response_with_functions('synthetic-deepseek-native', messages, functions=tools):
                if content:
                    text.append(content)
                for call in chunks or []:
                    item = calls.setdefault(call.index, {'id':'','name':'','arguments':''})
                    if call.id: item['id'] = call.id
                    if call.function.name: item['name'] += call.function.name
                    if call.function.arguments: item['arguments'] += call.function.arguments
            return {'text':''.join(text),'calls':list(calls.values()),'elapsed_ms':round((time.perf_counter()-start)*1000)}
        try:
            await asyncio.wait_for(client.initialize(), 20)
            tools = client.get_available_tools()
            result['tool_catalog_count'] = len(tools)
            samples = [('伦敦那边现在几点了？','Europe/London'),('东京的时间你能帮我看看吗？','Asia/Tokyo'),
                       ('纽约那边现在几点了？','America/New_York'),
                       ('查询设备当前音量',None),('不用查时间，我只是说东京跟我们有时差。',None)]
            for question, timezone in samples:
                usage.clear()
                messages = [{'role':'system','content':prompt},{'role':'user','content':question}]
                first = await asyncio.to_thread(stream, messages, tools)
                item = {'user':question,'first':first,'expected_timezone':timezone,'executed':[]}
                if timezone and len(first['calls']) == 1 and first['calls'][0]['name'] == 'get_world_time':
                    call = first['calls'][0]
                    args = json.loads(call['arguments'])
                    if args.get('timezone') == timezone:
                        receipt = (await asyncio.wait_for(client.call_tool(call['name'], args), 15)).model_dump(mode='json')
                        item['executed'].append({'name':call['name'],'arguments':args,'receipt':receipt})
                        messages.append({'role':'assistant','content':first['text'] or None,'tool_calls':[{'id':call['id'],'type':'function','function':{'name':call['name'],'arguments':call['arguments']}}]})
                        messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(receipt,ensure_ascii=False)})
                        item['final'] = await asyncio.to_thread(stream, messages, tools)
                item['usage'] = list(usage)
                result['cases'].append(item)
                (OUT / 'deepseek-retest-native-20261006.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
                print(json.dumps(item,ensure_ascii=False),flush=True)
        finally:
            await client.cleanup()
            provider.client.close()
    asyncio.run(native_run())
else:
    raise ValueError('unknown test mode')
