"""Read-only source/config verification after the prompt-only experiment."""
import ast, hashlib, json, subprocess
from pathlib import Path
from urllib.request import urlopen

out = Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
exec(compile((out/'inspect_default_route.py').read_text().split('cfg=json.loads')[0], '<read-only-config>', 'exec'))
data = json.loads((out/'prompt-only-comparison.json').read_text())
cfg = json.loads(sql("SELECT config_json FROM ai_model_config WHERE id='LLM_QwenPlusOfficial';"))
hashes = {p: hashlib.sha256((prod/'main/xiaozhi-server'/p).read_bytes()).hexdigest() for p in data['runtime_source_sha256']}
processes = json.loads(subprocess.run(['pm2','jlist'], capture_output=True, text=True, check=True).stdout)
result = {
    'production_commit': subprocess.run(['git','-C',str(prod),'rev-parse','HEAD'],capture_output=True,text=True,check=True).stdout.strip(),
    'tracked_changes_preserved': subprocess.run(['git','-C',str(prod),'status','--porcelain','--untracked-files=no'],capture_output=True,text=True,check=True).stdout.strip(),
    'model': cfg.get('model_name'), 'temperature': cfg.get('temperature'),
    'source_hashes_unchanged': hashes == data['runtime_source_sha256'],
    'services': [{'name': p['name'], 'status': p.get('pm2_env',{}).get('status')} for p in processes if p['name'] in {'xiaozhi-server','manager-api','mcp-gateway'}]
}
with urlopen('https://www.realecho.cn/',timeout=20) as response:
    result['public_http_status'] = response.status
guides = {}
for name, path in [('current',prod/'main/xiaozhi-server/core/utils/conversation_guidance.py'),('prompt_only',Path('/root/prjs/tmp/complete-chat-review-20261006/main/xiaozhi-server/core/utils/conversation_guidance.py'))]:
    for node in ast.parse(path.read_text(encoding='utf-8-sig')).body:
        if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='NATURAL_CONVERSATION_GUIDANCE' for t in node.targets):
            guides[name] = ast.literal_eval(node.value)
    assert hashlib.sha256(guides[name].encode()).hexdigest() == data['guidance_sha256'][name]
assert result['source_hashes_unchanged'] and result['model']=='qwen3.8-flash' and float(result['temperature'])==0.4
assert result['public_http_status']==200 and len(result['services'])==3 and all(p['status']=='online' for p in result['services'])
assert result['production_commit'].startswith('35236f03')
(out/'prompt-only-formal-verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
(out/'prompt-only-guidance-snapshot.json').write_text(json.dumps(guides,ensure_ascii=False,indent=2))
print(json.dumps(result,ensure_ascii=False))
