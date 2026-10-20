"""Post-release actual production prompt, LLM and read-only MCP verification."""
import hashlib,json
from pathlib import Path
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
STAGE=Path('/root/prjs/tmp/persona-production-release-20261007')
PROD=Path('/root/prjs/xiaozhi-esp32-server')
candidate=json.loads((OUT/'persona-optimization-candidate-20261007.json').read_text())
plan=json.loads((STAGE/'plan.json').read_text())
for name,values in plan['files'].items():assert hashlib.sha256((PROD/name).read_bytes()).hexdigest()==values['after']
script=(OUT/'persona_runtime_test_20261007.py').read_text()
script=script.replace("with urlopen(Request(url+'/config/agent-models',data=json.dumps(payload).encode(),headers=headers),timeout=20) as r:return json.load(r)['data']", "for attempt in range(3):\n  with urlopen(Request(url+'/config/agent-models',data=json.dumps(payload).encode(),headers=headers),timeout=20) as r:response=json.load(r)\n  if isinstance(response.get('data'),dict):return response['data']\n  time.sleep(.5)\n raise RuntimeError('manager_configuration_unavailable')")
script=script.replace("personas=[{'id':'current','name':'当前自定义人格','prompt':data['prompt']}]+inventory['presets']", "personas=[{'id':'current','name':'当前自定义人格','prompt':data['prompt']}]+candidate['presets']")
script=script.replace("if persona['id']=='current':assert sha(system)==inventory['effective_system_sha256']", "assert candidate['execution_guidance'] in system")
script=script.replace("record={'model':params['model']", "sent_system='\\n\\n'.join(m['content'] for m in params['messages'] if m.get('role')=='system' and isinstance(m.get('content'),str))\n      assert candidate['execution_guidance'] in sent_system and '<personality>\\n'+persona['prompt']+'\\n</personality>' in sent_system, 'persona_missing_from_production_request'\n      record={'sent_system_sha256':sha(sent_system),'persona_in_actual_request':True,'model':params['model']")
start=script.index('scenes=[');end=script.index('\ndef sha(',start)
scenes=[{'id':'production-chat','name':'新人格正式链路','turns':['今天换了个手机壳，颜色很亮。我就随便说说，不用给建议。']},{'id':'tools','name':'真实工具查询及否定请求','turns':['伦敦那边现在几点了？帮我查一下，直接说结果，别顺便逗我。','别查时间。我只是想知道时差是什么意思，正常解释一下。']}]
script=script[:start]+'scenes='+repr(scenes)+'\n'+script[end:]
script=script.replace('for repeat in [1,2]:','for repeat in [1]:').replace("'repeats':2","'repeats':1").replace("'expected_turns':182","'expected_turns':21")
script=script.replace('persona-runtime-results-20261007.json','persona-production-probe-results-20261007.json')
script=script.replace("state_before=state_hash(data)","state_before=state_hash(data)\nreport.update(actual_production_source=True, persona_source_sha256=plan['files']['main/xiaozhi-server/core/utils/prompt_manager.py']['after'])")
exec(compile(script,'<production-persona-probe>','exec'),globals())
