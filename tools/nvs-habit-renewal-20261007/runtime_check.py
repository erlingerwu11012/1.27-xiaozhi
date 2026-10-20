import asyncio,hashlib,importlib.util,json,subprocess,sys
from pathlib import Path
import httpx
stage=Path(__file__).parent
processes=json.loads(subprocess.check_output(['pm2','jlist']))
wanted={'manager-api','manager-web','xiaozhi-server','mcp-gateway'}
states={p['name']:p['pm2_env']['status'] for p in processes if p['name'] in wanted}
assert set(states)==wanted and all(x=='online' for x in states.values())
deployment=json.loads((stage/'production-backup/deployment.json').read_text())
runtime_audio_changes=[]
for name,digest in deployment['protected'].items():
 p=Path(name);current=hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
 if name.endswith('.wav'):
    if current!=digest:runtime_audio_changes.append(name)
    continue
 assert current==digest,'protected file changed'
for row in json.loads((stage/'manifest.json').read_text()):
 root=Path('/root/prjs/xiaozhi_mcp_gateway') if row['path'].startswith('gateway/') else Path('/root/prjs/xiaozhi-esp32-server')
 path=root/row['path'].removeprefix('gateway/') if row['path'].startswith('gateway/') else root/row['path']
 assert hashlib.sha256(path.read_bytes()).hexdigest()==row['candidate_sha256']
ports=subprocess.check_output(['ss','-lnt'],text=True)
for port in (8000,8001,8002,8006):assert ':'+str(port) in ports
async def auth():
 async with httpx.AsyncClient(timeout=10) as client:
    b=await client.get('http://127.0.0.1:8002/xiaozhi/habits/internal/1')
    c=await client.post('http://127.0.0.1:8006/api/v1/habit/sync',json={'habit_id':1})
    assert b.status_code==401 and c.status_code==401
    return {'manager_no_bearer':b.status_code,'python_no_bearer':c.status_code}
result={'services':states,'ports_checked':[8000,8001,8002,8006],'protected_configuration_unchanged':True,'source_hashes_match':True,'runtime_audio_changes':runtime_audio_changes,'auth':asyncio.run(auth())}
(stage/'runtime-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
