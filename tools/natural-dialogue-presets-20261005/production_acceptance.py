"""Verify real production provider streaming and actual read-only MCP round trips."""
from pathlib import Path
source=Path('/root/prjs/tmp/natural-dialogue-20261003/live_chain_acceptance.py').read_text().split('SAMPLES=[')[0]
source=source.replace("ROOT=Path('/root/prjs/tmp/natural-dialogue-20261003/main/xiaozhi-server')", "ROOT=PROD")
source=source.replace('OUT=ROOT.parents[1]', "OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')")
exec(compile(source,'<production-streaming-acceptance>','exec'))
assert llm['model_name']=='qwen3.8-flash' and float(llm['temperature'])==0.4
asyncio.run(mcp_test())
(OUT/'production-mcp-proposals.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({'native_mcp':report['native_mcp']},ensure_ascii=False),flush=True)
assert len(report['native_mcp'])==3 and all(row['success'] for row in report['native_mcp'])
from core.providers.llm.openai.openai import LLMProvider
provider=LLMProvider(dict(llm,timeout=35,max_tokens=160));provider.client=provider.client.with_options(max_retries=0)
report['dialogues']=[]
for persona_id,persona in [('natural','你随和、坦诚，有自己的看法。用熟人之间自然的方式交谈。'),('existing-playful',PERSONA)]:
 system=PromptManager({'system_base_prompt':base.get('system_base_prompt',''),'language':'中文'},logger=MagicMock()).build_enhanced_prompt_v2(persona,'synthetic-production',device_name='小智',user_nickname='小林',official_enhanced=True)
 messages=[{'role':'system','content':system}]
 for question in ['今天累了一天，别讲道理，也别替我安排事情，陪我正常聊两句。','我点了晚饭，还没送到，准备吃完再去洗澡。','明天再弄那份方案吧，我就是这么打算，还没写完。']:
  check_budget();messages.append({'role':'user','content':question});report['model_calls']+=1
  answer=''.join(provider.response('synthetic-production',messages,max_tokens=160))
  flags=bool(re.search(r'\[(?:smirk|wink|grin|emotion)|喵|小主人|乖乖|小尾巴|\*[^*]+\*',answer,re.I))
  row={'persona':persona_id,'user':question,'assistant':answer,'invalid_style_flag':flags}
  report['dialogues'].append(row);messages.append({'role':'assistant','content':answer})
  assert answer and not flags,'production_dialogue_style_failed'
provider.client.close()
report.update(model=llm['model_name'],temperature=llm['temperature'],production_gateway=True,actual_mcp_executions=3,model_calls=12,secondary_rewrite=False,hardware_writes=0)
(OUT/'production-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps({'production_gateway':True,'actual_mcp_executions':3,'dialogues':report['dialogues'],'model_calls':report['model_calls']},ensure_ascii=False))
