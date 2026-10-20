"""Isolated persona-only patch; identical production runtime and 182 baseline turns."""
import hashlib, json, os
from pathlib import Path
OUT = Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
PROD = Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
candidate = json.loads((OUT/'persona-optimization-candidate-20261007.json').read_text())
original = (PROD/'core/utils/prompt_manager.py').read_text()
start = original.index('            layer2 = (', original.index('            role_text ='))
end = original.index('\n\n            language =', start)
new = (
    "            layer2 = (\n"
    "                '[用户人格原文，仅用于性格特点]\\n<personality>\\n' + role_text\n"
    "                + '\\n</personality>\\n' + " + repr(candidate['execution_guidance']) + "\n"
    "            ) if role_text else ''"
)
patched = original[:start]+new+original[end:]
assert patched[:start] == original[:start] and patched[start+len(new):] == original[end:]
compile(patched, '<persona-only-candidate>', 'exec')
candidate_sha = hashlib.sha256(patched.encode()).hexdigest()
baseline_script = (OUT/'persona_runtime_test_20261007.py').read_text()
replacement = '''import core.utils.prompt_manager as persona_module
exec(compile(patched, '<persona-only-candidate>', 'exec'), persona_module.__dict__)
PromptManager = persona_module.PromptManager'''
script = baseline_script.replace('from core.utils.prompt_manager import PromptManager', replacement)
# Retry read-only configuration fetches when the manager transiently returns no data.
script = script.replace("with urlopen(Request(url+'/config/agent-models',data=json.dumps(payload).encode(),headers=headers),timeout=20) as r:return json.load(r)['data']", "for attempt in range(3):\n  with urlopen(Request(url+'/config/agent-models',data=json.dumps(payload).encode(),headers=headers),timeout=20) as r:response=json.load(r)\n  if isinstance(response.get('data'),dict):return response['data']\n  time.sleep(.5)\n raise RuntimeError('manager_configuration_unavailable')")
script = script.replace("personas=[{'id':'current','name':'当前自定义人格','prompt':data['prompt']}]+inventory['presets']", "personas=[{'id':'current','name':'当前自定义人格','prompt':data['prompt']}]+candidate['presets']")
script = script.replace("persona-runtime-results-20261007.json", "persona-optimized-runtime-results-20261007.json")
script = script.replace("if persona['id']=='current':assert sha(system)==inventory['effective_system_sha256']", "assert candidate['execution_guidance'] in system")
script = script.replace("record={'model':params['model']", "sent_system='\\n\\n'.join(m['content'] for m in params['messages'] if m.get('role')=='system' and isinstance(m.get('content'),str))\n      assert candidate['execution_guidance'] in sent_system and '<personality>\\n'+persona['prompt']+'\\n</personality>' in sent_system, 'candidate_not_sent_to_model'\n      record={'sent_system_sha256':sha(sent_system),'persona_in_actual_request':True,'model':params['model']")
script = script.replace("state_before=state_hash(data)", "state_before=state_hash(data)\nreport.update(candidate_prompt_manager_sha256=candidate_sha, production_prompt_manager_sha256=sha(original), persona_execution_guidance=candidate['execution_guidance'], baseline_unchanged_scenarios=True, tool_prompt_unchanged=True)")
if os.environ.get('PERSONA_HELDOUT') == '1':
    heldout = [{'id':'heldout','name':'新题：认真反馈、更新状态、恢复玩笑','turns':[
        '前天买了拼图，今天拆了盒子，还没开始拼。我只是分享一下，不用给建议。',
        '今天跟同事聊的时候，他一直看手机。我有点不舒服，这会儿别开玩笑，也别分析谁的心理。',
        '更新一下，晚上我拼好了三分之一，还剩三分之二。',
        '不用再谈同事。只按我说的，拼图现在完成多少？我今天没拼完，能说我还没开始吗？',
        '现在可以稍微打趣一下拼图，但别给我贴标签。'
    ]}]
    scene_start = script.index('scenes=[')
    scene_end = script.index('\ndef sha(', scene_start)
    script = script[:scene_start] + 'scenes=' + repr(heldout) + '\n' + script[scene_end:]
    script = script.replace('for repeat in [1,2]:', 'for repeat in [1]:')
    script = script.replace("'repeats':2", "'repeats':1").replace("'expected_turns':182", "'expected_turns':35")
    script = script.replace('persona-optimized-runtime-results-20261007.json', 'persona-optimized-heldout-results-20261007.json')
    script = script.replace('baseline_unchanged_scenarios=True', 'baseline_unchanged_scenarios=False, heldout_not_in_prompt=True')
if os.environ.get('PERSONA_REFINED') == '1':
    script = script.replace('persona-optimized-runtime-results-20261007.json', 'persona-refined-runtime-results-20261007.json')
    script = script.replace('persona-optimized-heldout-results-20261007.json', 'persona-refined-heldout-results-20261007.json')
if os.environ.get('PERSONA_INJECTION_PROBE') == '1':
    scene_start = script.index('scenes=[')
    scene_end = script.index('\ndef sha(', scene_start)
    script = script[:scene_start] + "scenes=[{'id':'injection','name':'核验真实模型请求人格','turns':['今天换了个手机壳，颜色很亮。我就随便说说，不用给建议。']}]\n" + script[scene_end:]
    script = script.replace('for repeat in [1,2]:','for repeat in [1]:').replace("'repeats':2", "'repeats':1").replace("'expected_turns':182", "'expected_turns':7")
    script = script.replace('persona-refined-runtime-results-20261007.json','persona-injection-probe-results-20261007.json')
    script = script.replace('baseline_unchanged_scenarios=True','baseline_unchanged_scenarios=False, injection_probe=True')
assert script.count('candidate[\'presets\']') == 1
exec(compile(script, str(OUT/'persona_optimized_runtime_20261007.py'), 'exec'), globals())
