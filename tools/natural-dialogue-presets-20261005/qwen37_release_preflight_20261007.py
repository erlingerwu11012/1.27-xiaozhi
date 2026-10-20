"""Verify the deployment candidate matches the frozen tested prompt exactly."""
import json,sys,unittest
from pathlib import Path
from unittest.mock import MagicMock
import qwen_paired_tool_test_20261006 as tested
ROOT=Path('/root/prjs/tmp/qwen37-official-release-20261007')
import core.utils.conversation_guidance as guidance
import core.utils.prompt_manager as prompt_module
import core.utils.operation_control as control
import core.providers.tools.unified_tool_manager as manager
import core.providers.llm.openai.openai as llm_module
for module,name in [(guidance,'core/utils/conversation_guidance.py'),(prompt_module,'core/utils/prompt_manager.py'),(control,'core/utils/operation_control.py'),(manager,'core/providers/tools/unified_tool_manager.py'),(llm_module,'core/providers/llm/openai/openai.py')]:
 path=ROOT/'xiaozhi-server'/name;exec(compile(path.read_text(),str(path),'exec'),module.__dict__)
pack=json.loads(tested.PACK.read_text())
checks=[]
for persona_index in [0,1]:
 row=pack['cases'][persona_index]
 persona=tested.old.PERSONA if row['id']%2 else '你随和、坦诚，有自己的看法。用熟人之间自然的方式交谈。'
 actual=prompt_module.PromptManager({'system_base_prompt':tested.old.base.get('system_base_prompt',''),'language':'中文'},logger=MagicMock()).build_enhanced_prompt_v2(persona,'production-verification',device_name='小智',user_nickname='主人',official_enhanced=True)
 expected=row['initial_messages'][0]['content'].split('\n\n[本轮可信验收时钟]')[0]
 assert actual==expected,'deployed_prompt_differs_from_frozen_test'
 assert '[本轮可信验收时钟]' not in actual
 checks.append({'persona':row['persona'],'prompt_exact_match':True,'sha256':tested.sha(actual)})
p=llm_module.LLMProvider(dict(tested.old.llm,model_name='qwen3.7-plus',api_key='isolated-verification-token',base_url='http://127.0.0.1:3000/v1',max_tokens=600,timeout=45))
capture=MagicMock(return_value=[]);p.client.chat.completions.create=capture
list(p.response('qa',[{'role':'user','content':'你好'}]))
list(p.response_with_functions('qa',[{'role':'user','content':'查时间'}],functions=[]))
for call in capture.call_args_list:
 params=call.kwargs
 assert params['model']=='qwen3.7-plus'
 assert params['extra_body']=={'enable_thinking':False,'preserve_thinking':False}
 assert params['temperature']==.4 and params['max_tokens']==600
p.client.close()
sys.path.insert(0,str(tested.OUT/'qwen-paired-guard/test'))
names=['test_operation_control','test_operation_pipeline','test_verified_tool_facts','test_natural_tool_failure_regression','test_explicit_setting_targets','test_prompt_pipeline_v2']
result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(names))
receipt={'prompt_checks':checks,'plain_and_native_api_thinking_disabled':True,'gateway_origin':'http://127.0.0.1:3000/v1','regression_tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'passed':result.wasSuccessful()}
(ROOT/'python-preflight.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
print(json.dumps(receipt,ensure_ascii=False),flush=True)
raise SystemExit(0 if result.wasSuccessful() else 1)
