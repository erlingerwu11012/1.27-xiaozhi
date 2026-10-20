"""Read-only, no chat text/audio/secrets printed; selected device only."""
from pathlib import Path
import json,subprocess,urllib.request,re

device='ac:a7:04:fd:20:2c'
mysql=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def sql(query):
    return subprocess.run(mysql,input=query,text=True,capture_output=True,check=True).stdout.strip()
target=json.loads((Path('/root/prjs/tmp/memory-test-20260930')/'target.json').read_text())
secret=sql("SELECT param_value FROM xiaozhi_esp32_server.sys_params WHERE param_code='server.secret';")
request=urllib.request.Request('http://127.0.0.1:8002/xiaozhi/device/by-mac/'+device,headers={'Authorization':'Bearer '+secret})
with urllib.request.urlopen(request,timeout=5) as response:
    result=json.loads(response.read())
data=result.get('data') or {}
print(json.dumps({'device_config_status':result.get('code'),'device_config_keys':sorted(data.keys()),
    'has_agentId':bool(data.get('agentId')),'has_agent_id':bool(data.get('agent_id')),
    'agent_matches_current_device':str(data.get('agentId') or data.get('agent_id') or '')==str(target['agent_id']),
    'has_userId':bool(data.get('userId')),'has_user_id':bool(data.get('user_id')),
    'user_matches_current_device':str(data.get('userId') or data.get('user_id') or '')==str(target['account_id'])},ensure_ascii=False))
body=json.dumps({'macAddress':device,'clientId':'diagnostic-read-only','selectedModule':{}},ensure_ascii=False).encode()
config_request=urllib.request.Request('http://127.0.0.1:8002/xiaozhi/config/agent-models',data=body,
    headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'},method='POST')
with urllib.request.urlopen(config_request,timeout=7) as response:
    config_response=json.loads(response.read())
cfg=config_response.get('data') or {}
print(json.dumps({'agent_config_status':config_response.get('code'),'has_account':bool(cfg.get('sys_user_id')),
    'account_matches':str(cfg.get('sys_user_id') or '')==str(target['account_id']),
    'has_agent':bool(cfg.get('agent_id')),'agent_matches':str(cfg.get('agent_id') or '')==str(target['agent_id']),
    'memory_selection':(cfg.get('selected_module') or {}).get('Memory')},ensure_ascii=False))

pm=json.loads(subprocess.run(['pm2','jlist'],capture_output=True,text=True,check=True).stdout)
server=next(p for p in pm if p['name']=='xiaozhi-server')
for kind in ('pm_out_log_path','pm_err_log_path'):
    logfile=Path(server['pm2_env'][kind]);raw=logfile.read_bytes()[-8_000_000:].decode('utf-8','replace') if logfile.exists() else ''
    window=[];inside=False
    for line in raw.splitlines():
        if '260930 00:58:' in line or '260930 00:59:' in line:inside=True
        if '260930 01:00:' in line:inside=False
        if inside:window.append(line)
    categories={label:sum(bool(re.search(pattern,line,re.I)) for line in window) for label,pattern in {
        'memory_search':r'memory_search','memory_provider':r'providers.memory|memory_gateway|person-memory/internal/search',
        'tool_call':r'tool_call|function.call|调用工具','archive_error':r'存档归属无效|TTS上报失败',
        'identity':r'identity_context|directory_version|default_generation|冻结.*身份',
        'asr':r'识别文本|ASR', 'llm':r'LLM|大模型',
    }.items()}
    print(json.dumps({'log_stream':kind,'window_line_count':len(window),'categories':categories},ensure_ascii=False))
    if kind=='pm_out_log_path':
        for line in window:
            if not any(term in line for term in ('memory_search','存档归属无效','identity_context')):continue
            at=re.search(r'260930 (\d\d:\d\d:\d\d)',line)
            tag=re.search(r'\[core\.([^\]]+)\]',line)
            print(json.dumps({'at':at.group(1) if at else None,'tag':tag.group(1) if tag else None,
                'memory_search':('memory_search' in line),'archive_rejected':('存档归属无效' in line),
                'identity_unknown':('identity_unknown' in line),'temporarily_unavailable':('temporarily_unavailable' in line),
                'tool_list':('当前支持的函数列表' in line),'tool_execute':('执行' in line or '调用' in line),
                'contains_seeded_fact':any(fact in line for fact in ('蓝松果','小山雀','茉莉花茶'))},ensure_ascii=False))
        print(json.dumps({'status_markers':{key:sum(key in l for l in window) for key in
            ('identity_unknown','temporarily_unavailable','not_found','search_in_progress','memory_gateway_status',
             'identity/sync','directory_version','identity_context','设备归属已变更','存档归属无效','蓝松果','小山雀',
             '检测到 1 个工具调用','function_name=memory_search','[device_config_fallback]','获取设备配置失败')}},ensure_ascii=False))

account=target['account_id'];agent=target['agent_id']
rows=sql("SELECT JSON_OBJECT('identity_status',identity_status,'chat_type',chat_type,'has_person',person_id IS NOT NULL,'has_turn',turn_id IS NOT NULL,'recall_allowed',recall_allowed) FROM xiaozhi_esp32_server.ai_agent_chat_history WHERE account_id="+str(account)+" AND agent_id='"+agent+"' AND created_at BETWEEN '2026-09-30 00:58:00' AND '2026-09-30 01:00:59' ORDER BY id;")
print(json.dumps({'archive_row_metadata':[json.loads(r) for r in rows.splitlines() if r]},ensure_ascii=False))
result=json.loads((Path('/root/prjs/tmp/memory-test-20260930')/'seed-result.json').read_text())
cloud=result['cloud_private'].encode().hex()
bills=sql("SELECT operation,COUNT(*),SUM(state='settled') FROM one_api.memory_charges WHERE BINARY cloud_user_id=BINARY CONVERT(X'"+cloud+"' USING utf8mb4) AND created_at>=UNIX_TIMESTAMP('2026-09-30 00:58:00') AND created_at<UNIX_TIMESTAMP('2026-09-30 01:01:00') GROUP BY operation;")
print(json.dumps({'window_memory_charges':bills},ensure_ascii=False))
