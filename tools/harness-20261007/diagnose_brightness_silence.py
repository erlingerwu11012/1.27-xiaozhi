import pathlib,subprocess,json,re
apps=json.loads(subprocess.check_output(['pm2','jlist'],text=True));a=next(x for x in apps if x['pm_id']==7)
for key in ['pm_out_log_path','pm_err_log_path']:
 p=pathlib.Path(a['pm2_env'][key]);lines=p.read_text(errors='replace').splitlines()
 print('LOG',key)
 for i,l in enumerate(lines):
  if re.search(r'261009 01:(?:09|10|11):',l) and any(t in l for t in ['harness.','ERROR','WARNING','超时','WebSocket close','大模型收到','发送第一段语音','listen_start','abort','音频识别','LLM','brightness']):
   l=re.sub(r'"(?:account_id|person_id|agent_id)":\s*"[^"]*"','"private":"[redacted]"',l)
   print(l[:2000])
root=pathlib.Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server')
for rel,terms in [('core/providers/tools/device_mcp/mcp_handler.py',['brightness','isError','error','result']),('core/utils/tool_harness/registry.py',['brightness','minimum','maximum']),('core/handle/receiveAudioHandle.py',['utterance_id','epoch','abort','person_turn'])]:
 p=root/rel;lines=p.read_text().splitlines();print('SOURCE',rel)
 for i,l in enumerate(lines):
  if any(t in l for t in terms):print(str(i+1)+':'+l)
