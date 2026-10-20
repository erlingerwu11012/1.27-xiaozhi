from pathlib import Path
import tarfile,json,hashlib
S=Path('tools/hardware-repair-20261009');W=S/'work'
p=S/'budget.py';p.write_text(p.read_text().replace("'case':4300,'model':2200","'case':2000,'model':600"))
p=S/'java/ConfigServiceImpl.java';p.write_text(p.read_text().replace('默认0.4','默认0.3').replace('similarity_threshold", 0.4','similarity_threshold", 0.3'))
p=W/'core/utils/tool_harness/contracts.py';s=p.read_text();s=s.replace("        elif name in {'alarm_list','note_list','habit_list'}:\n            valid=", "        elif name=='alarm_list' and isinstance(body,dict):\n            valid=body.get('ok') is True and isinstance(body.get('items'),list) and all(isinstance(a,dict) and type(a.get('id')) is int and type(a.get('hour')) is int and 0<=a['hour']<=23 and type(a.get('minute')) is int and 0<=a['minute']<=59 and isinstance(a.get('label'),str) for a in body['items'])\n        elif name=='get_weather':valid=isinstance(body,str) and '您查询的位置是：' in body and '当前天气:' in body\n        elif name=='get_news_from_newsnow':valid=isinstance(body,str) and bool(re.search(r'新闻标题[:：]|标题[:：]',body))\n        elif name in {'alarm_list','note_list','habit_list'}:\n            valid=")
s=s.replace("                reply=legacy_list_reply(body)", "                reply=('当前没有闹钟。' if not body['items'] else '；'.join(f\"{a['hour']:02d}点{a['minute']:02d}分，{a['label']}\" for a in body['items'])+'。') if isinstance(body,dict) and name=='alarm_list' else legacy_list_reply(body)")
p.write_text(s)
p=S/'wire_conversation.py';s=p.read_text().replace("args['match'],args.get('replacement')", "args.get('match',''),args.get('replacement'),record_id=args.get('record_id',''),expected_version=args.get('expected_version','')");p.write_text(s)
p=S/'stateful_device.py';s=p.read_text().replace("'output_volume':self.state['volume']", "'volume':self.state['volume']")
s=s.replace("        elif name=='alarm_list':body=", "        elif name=='alarm_list_legacy':body=")
s=s.replace("        elif name=='alarm_delete':", "        elif name=='alarm_list':body={'ok':True,'items':[{'id':i+1,'enabled':True,'last_triggered_at':0,**a} for i,a in enumerate(self.state['alarms'])]}\n        elif name=='self_camera_take_photo':body={'success':True,'response':'画面里是一只蓝色杯子，放在桌面上。'}\n        elif name=='reminder_close_current':\n            card=self.state['card']\n            if not card.get('active') or args['instance_id']!=card['instance_id'] or args['revision']!=card['revision']:body={'ok':False,'errorCode':'stale_revision','message':'卡片已更新'}\n            else:\n                card['active']=False;card['last_action']='close';body={'ok':True,'closed':True,'business_unchanged':True,'instance_id':args['instance_id'],'revision':args['revision'],'current_revision':args['revision']+1};card['revision']+=1\n        elif name=='alarm_delete':")
s=s.replace("        self.state.setdefault('alarm_ringing',True)", "        from core.providers.tools.base import ToolDefinition,ToolType\n        d={'type':'function','function':{'name':'reminder_close_current','description':'只关闭当前卡片，不完成、不删除事项；先读取reminder_get_current获得ID和revision。','parameters':{'type':'object','properties':{'instance_id':{'type':'string'},'revision':{'type':'integer','minimum':1,'maximum':2147483647}},'required':['instance_id','revision'],'additionalProperties':False}}}\n        self.tools['reminder_close_current']=ToolDefinition(name='reminder_close_current',description=d,tool_type=ToolType.DEVICE_MCP)\n        self.state.setdefault('alarm_ringing',True)")
p.write_text(s)
p=S/'experience_protocol.py';s=p.read_text().replace("        async def device(request):", "        self.raw['reminder.close_current']='reminder_close_current'\n        async def device(request):");p.write_text(s)
files=['core/utils/tool_harness/runtime.py','core/utils/tool_harness/contracts.py','core/utils/tool_harness/presentation.py','core/utils/tool_harness/memory_policy.py','core/utils/tool_harness/reply_composer.py','core/utils/recent_memory.py','core/utils/voiceprint_provider.py','core/utils/vision_readiness.py','plugins_func/functions/person_memory.py']
with tarfile.open(S/'candidate-changes.tgz','w:gz') as t:
 for f in files:t.add(W/f,arcname='work/'+f)
 for p in (S/'java').glob('*.java'):
  if p.name=='ConfigServiceImpl.java':target='src/main/java/xiaozhi/modules/config/service/impl/'+p.name
  elif p.name.endswith('Test.java'):target='src/test/java/xiaozhi/modules/personmemory/'+p.name
  else:target='src/main/java/xiaozhi/modules/personmemory/'+p.name
  t.add(p,arcname='manager-api/'+target)
 for f in ['bootstrap.py','budget.py','wire_conversation.py','stateful_device.py','experience_protocol.py','start_api.py','run_java_tests.py']:t.add(S/f,arcname=f)
(S/'changed-files.json').write_text(json.dumps({f:hashlib.sha256((W/f).read_bytes()).hexdigest() for f in files},indent=2))
print('packaged',len(files),'server files')
