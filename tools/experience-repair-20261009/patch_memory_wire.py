from pathlib import Path
S=Path('tools/experience-repair-20261009')
p=S/'wire_conversation.py';s=p.read_text(encoding='utf-8-sig')
s=s.replace('import test_protocol','import experience_protocol as test_protocol')
s=s.replace("from unittest.mock import patch,AsyncMock", "from unittest.mock import patch,AsyncMock\n_directory_patch=None\n_directory_users=0")
s=s.replace(" async def setup(self,provider,cfg):", " async def setup(self,provider,cfg):\n  global _directory_patch,_directory_users\n  import requests\n  self.api_headers={'Authorization':'Bearer '+(stage/'api-test-secret').read_text()}\n  info=requests.get('http://127.0.0.1:18002/xiaozhi/user-identities/internal/state/99003',headers=self.api_headers,timeout=3).json()['data']")
s=s.replace("c.account_id='simulation-account';", "c.account_id='99003';c.person_turn=dataclasses.replace(c.person_turn,account_id='99003',person_id=info['default_user_id'],mode='default',status='default',generation=info['default_generation'],directory_version=info['directory_version'],agent_id='agent_http');c.config['manager-api']={'url':'http://127.0.0.1:18002/xiaozhi','secret':(stage/'api-test-secret').read_text(),'max_retries':0};")
a=s.index("    if name=='memory_search':");b=s.index("    if name=='add_reminder'",a)
s=s[:a]+"""    if name=='memory_search':
     from core.utils.recent_memory import search
     return ActionResponse(Action.REQLLM,result=await search(conn,args['query']))
    if name in {'memory_correct','memory_forget'}:
     from core.utils.recent_memory import override
     return ActionResponse(Action.REQLLM,result=await override(conn,'correct' if name=='memory_correct' else 'forget',args['match'],args.get('replacement')))
"""+s[b:]
s=s.replace("ProfileDirectory(account_id='simulation-account',profiles=[ProfileRecord('person-a','测试用户','active','simulation-account')])", "ProfileDirectory(account_id='99003',profiles=[ProfileRecord(c.person_turn.person_id,'测试用户','active','99003')])")
s=s.replace("  self.directory_patch=patch('core.utils.unified_recipient_resolver._fetch_directory',AsyncMock(return_value=directory));self.directory_patch.start()", "  if _directory_users==0:\n   _directory_patch=patch('core.utils.unified_recipient_resolver._fetch_directory',AsyncMock(return_value=directory));_directory_patch.start()\n  _directory_users+=1")
s=s.replace(" async def close(self):", " async def close(self):\n  global _directory_users,_directory_patch")
s=s.replace("  self.directory_patch.stop();await", "  _directory_users-=1\n  if _directory_users==0:_directory_patch.stop()\n  await")
p.write_text(s,encoding='utf-8')
proto=Path('tools/harness-20261007/test_protocol.py').read_text(encoding='utf-8-sig').replace("'recipient_id':'person-a'","'recipient_id':self.conn.person_turn.person_id")
(S/'experience_protocol.py').write_text(proto,encoding='utf-8')
p=S/'candidate/core/utils/recent_memory.py';s=p.read_text(encoding='utf-8')
s=s.replace("    from core.utils.person_material_outbox import material_outbox", "    if not isinstance(result,dict) or (result.get('local_applied') is not True and result.get('status') not in {'accepted','queued'}):\n        return {'status':'error','message':'这次没有确认记忆修改成功。'}\n    from core.utils.person_material_outbox import material_outbox",1)
s=s.replace("        if message.role=='system' or (match!='*' and match not in text):kept.append(message)", "        if message.role=='system' or getattr(message,'material_turn_id',None)==actor.turn_id:\n            kept.append(message)\n        elif match!='*':\n            if match in text:\n                message.content=text.replace(match,replacement if action=='correct' else '（该个人信息已按要求移除）')\n            kept.append(message)\n        elif not getattr(message,'memory_retrieval',False):\n            # Keep conversational scaffolding; removed facts must not be recalled.\n            if message.role in {'user','assistant'} and not getattr(message,'tool_calls',None):\n                message.content='（此前个人内容已按要求从本地对话召回中移除）'\n            kept.append(message)")
p.write_text(s,encoding='utf-8')
