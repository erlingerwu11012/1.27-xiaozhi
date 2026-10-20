"""Build the exact tested persona candidate without modifying live source."""
import hashlib,json,os,shutil,subprocess
from pathlib import Path
from datetime import datetime,timezone
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
PROD=Path('/root/prjs/xiaozhi-esp32-server')
STAGE=Path('/root/prjs/tmp/persona-production-release-20261007')
os.umask(0o077)
STAGE.mkdir(exist_ok=True)
if (STAGE/'plan.json').exists():
 assert not json.loads((STAGE/'plan.json').read_text())['prepared'],'release_already_prepared'
candidate=json.loads((OUT/'persona-optimization-candidate-20261007.json').read_text())
tested=json.loads((OUT/'persona-refined-runtime-results-20261007.json').read_text())
assert tested['finished'] and tested['customer_configuration_unchanged']
assert tested['persona_execution_guidance']==candidate['execution_guidance'] and tested['personas'][1:]==candidate['presets']
assert len(candidate['presets'])==6
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def command(args,**kwargs):
 p=subprocess.run(args,capture_output=True,text=True,**kwargs)
 if p.returncode:raise RuntimeError('command_failed_'+args[0])
 return p.stdout.strip()
prompt_name='main/xiaozhi-server/core/utils/prompt_manager.py'
preset_name='main/manager-web/src/constants/personaPresets.js'
original=(PROD/prompt_name).read_text()
assert hashlib.sha256(original.encode()).hexdigest()==tested['production_prompt_manager_sha256']
start=original.index('            layer2 = (',original.index('            role_text ='))
end=original.index('\n\n            language =',start)
new=("            layer2 = (\n"
     "                '[用户人格原文，仅用于性格特点]\\n<personality>\\n' + role_text\n"
     "                + '\\n</personality>\\n' + "+repr(candidate['execution_guidance'])+"\n"
     "            ) if role_text else ''")
patched=original[:start]+new+original[end:]
assert hashlib.sha256(patched.encode()).hexdigest()==tested['candidate_prompt_manager_sha256']
compile(patched,'<production-persona-candidate>','exec')
target=STAGE/prompt_name;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(patched)
web=PROD/'main/manager-web';staged_web=STAGE/'main/manager-web'
if not staged_web.exists():
 shutil.copytree(web,staged_web,ignore=shutil.ignore_patterns('node_modules','dist','logs','.git'))
 (staged_web/'node_modules').symlink_to(web/'node_modules',target_is_directory=True)
presets="// Editable personality drafts; execution rules and tool permissions live on the server.\nexport const PERSONA_PRESETS = Object.freeze([\n"
for p in candidate['presets']:
 presets+="  { id: "+repr(p['id'])+", name: "+repr(p['name'])+", description: "+repr(p['description'])+",\n    prompt: "+repr(p['prompt'])+" },\n"
presets+="]);\n\nexport const DEFAULT_PERSONA_PROMPT = PERSONA_PRESETS[0].prompt;\nexport function matchingPersonaPreset(text) {\n  return PERSONA_PRESETS.find(preset => preset.prompt === String(text || '').trim()) || null;\n}\n"
(STAGE/preset_name).write_text(presets)
files={name:{'before':digest(PROD/name),'after':digest(STAGE/name)} for name in [prompt_name,preset_name]}
protected=['main/xiaozhi-server/core/connection.py','main/xiaozhi-server/core/utils/operation_control.py','main/xiaozhi-server/core/utils/conversation_guidance.py','main/xiaozhi-server/core/providers/tools/unified_tool_manager.py','main/xiaozhi-server/core/providers/llm/openai/openai.py']
plan={'prepared':False,'created_utc':datetime.now(timezone.utc).isoformat(),'baseline':command(['git','-C',str(PROD),'rev-parse','HEAD']),'files':files,'protected':{n:digest(PROD/n) for n in protected},'user_persona_migration':False,'model_changed':False,'billing_changed':False}
(STAGE/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2))
exec((OUT/'inspect_qwen37_release_20261007.py').read_text().split('cfg=json.loads')[0])
model_hash=hashlib.sha256(sql("SELECT CONCAT(model_name,'|',config_json) FROM ai_model_config WHERE id='LLM_QwenPlusOfficial';").encode()).hexdigest()
personas_hash=hashlib.sha256(sql("SELECT SHA2(CONCAT_WS('|',id,COALESCE(system_prompt,'')),256) FROM ai_agent ORDER BY id;").encode()).hexdigest()
plan.update(model_config_sha256=model_hash,user_personas_sha256=personas_hash)
(STAGE/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2))
# Reuse the real Vue component checks against the new exact preset drafts.
deps=STAGE/'ui-test-dependencies'
if not (deps/'node_modules/jsdom/package.json').exists():
 with (STAGE/'ui-dependencies.log').open('w') as log:
  p=subprocess.run(['npm','install','--prefix',str(deps),'--no-save','--ignore-scripts','jsdom@22.1.0','@vue/test-utils@1.3.6','vue@2.6.14','vue-template-compiler@2.6.14'],stdout=log,stderr=subprocess.STDOUT,timeout=150)
  assert p.returncode==0,'ui_test_dependencies_unavailable'
ui=(OUT/'ui_component_tests.cjs').read_text().replace("const ROOT = OUT + '/worktree/main/manager-web';","const ROOT = '/root/prjs/tmp/persona-production-release-20261007/main/manager-web';")
ui=ui.replace("OUT + '/ui-tests/package.json'","'/root/prjs/tmp/persona-production-release-20261007/ui-test-dependencies/package.json'")
ui=ui.replace("OUT+'/ui-component-tests.json'","'/root/prjs/tmp/persona-production-release-20261007/ui-component-tests.json'")
(STAGE/'ui_component_tests.cjs').write_text(ui)
with (STAGE/'ui-tests.log').open('w') as log:
 p=subprocess.run(['node',str(STAGE/'ui_component_tests.cjs')],stdout=log,stderr=subprocess.STDOUT,timeout=90)
 assert p.returncode==0,'ui_checks_failed'
assert json.loads((STAGE/'ui-component-tests.json').read_text())['passed']==14
test_code="""import os,sys,unittest
from pathlib import Path
from unittest.mock import MagicMock
prod=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
os.chdir(prod);sys.path[:0]=[str(prod),str(prod/'test')]
import config.logger
config.logger.setup_logging=lambda:MagicMock()
import core.utils.prompt_manager as module
source=Path('/root/prjs/tmp/persona-production-release-20261007/main/xiaozhi-server/core/utils/prompt_manager.py').read_text()
exec(compile(source,'<persona-production-candidate>','exec'),module.__dict__)
suite=unittest.defaultTestLoader.loadTestsFromNames(['test_prompt_pipeline_v2','test_conversation_contract','test_primary_answer_direct_tts','test_natural_tool_failure_regression'])
result=unittest.TextTestRunner(verbosity=1).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
"""
(STAGE/'backend_checks.py').write_text(test_code)
with (STAGE/'backend-checks.log').open('w') as log:
 p=subprocess.run(['/root/miniconda3/envs/xiaozhi-esp32-server/bin/python',str(STAGE/'backend_checks.py')],stdout=log,stderr=subprocess.STDOUT,timeout=90)
 assert p.returncode==0,'backend_checks_failed'
with (STAGE/'frontend-build.log').open('w') as log:
 p=subprocess.run(['npm','run','build'],cwd=staged_web,stdout=log,stderr=subprocess.STDOUT,timeout=300,env=dict(os.environ,NODE_ENV='production'))
 assert p.returncode==0,'frontend_build_failed'
bundles='\n'.join(p.read_text(errors='replace') for p in (staged_web/'dist/js').glob('*.js'))
for p in candidate['presets']:assert p['prompt'] in bundles,'preset_missing_from_build'
assert 'https://api.realecho.cn/xiaozhi' in bundles,'production_api_origin_missing'
assert (staged_web/'dist/index.html').is_file()
plan.update(prepared=True,ui_passed=14,backend_checks=True,frontend_build=True,exact_tested_prompt=True)
(STAGE/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2))
print(json.dumps({'prepared':True,'ui_passed':14,'backend_checks':True,'frontend_build':True,'exact_tested_prompt':True,'source_changes':len(files),'production_changed':False}),flush=True)
