from pathlib import Path
import json,collections
S=Path('tools/hardware-repair-20261009');old=json.loads(Path('tools/experience-repair-20261009/final-cases.json').read_text(encoding='utf-8-sig'))
a=[dict(x,holdout=False,independent_holdout=False) for x in old[:180]]
for x in a:
 x['query']=x['query'].replace('我这边想请你帮个忙，','').replace('麻烦处理一下这件事：','帮我')
 x['id']='reg-'+str(x['id'])
def add(q,tool=None,args=None,session='',**kw):
 a.append({'id':'new-'+str(len(a)-179),'query':q,'tool':tool,'arguments':args or {},'group':'tool' if tool else 'chat','session':session,'holdout':True,'independent_holdout':True,**kw})
# 24 turns: fresh independent user-like memory wording, corrections and follow-ups.
for i,(edit,ask,forget) in enumerate([
 ('不是啊，我现在不喝咖啡了，你改一下，我现在喝绿茶','我就问问爱喝啥，你更正什么记忆啊','台灯那件事别记着了，忘掉吧'),
 ('咖啡那条记错了，给我改成喜欢喝绿茶','我现在爱喝什么？别再改我的记忆了','关于台灯的那条记忆给我删了'),
 ('我之前说错了，现在喜欢绿茶，你把咖啡那条更正一下','之前上下文呢，我到底喜欢喝啥','忘掉银杏灯那个信息'),
 ('不是喝咖啡了，我现在喝绿茶。把记忆改一下','你就查查我喜欢喝什么，别修改','银杏灯那事不用记着了，忘掉'),
 ('把我爱喝咖啡的记忆更新成爱喝绿茶','别逗了，直接说我现在爱喝什么','我那台灯叫什么的事情，删除这条记忆'),
 ('咖啡这个偏好变了，改为喜欢喝绿茶','我就问现在喜欢什么饮料，不是叫你修改','台灯的记忆忘记掉吧')]):
  sess='new-memory-'+str(i)
  add('我爱喝什么，查一下', 'memory_search',session=sess,setup='memory_search',required=['咖啡'])
  add(edit,'memory_correct',session=sess,expected_memory='绿茶')
  add(ask,'memory_search',session=sess,required=['绿茶'])
  add(forget,'memory_forget',session=sess,expected_absent='银杏灯',memory_kind='forget')
# 12 turns: independent close capability, list source preservation, no false completion.
for i,q in enumerate(['这个卡片关了吧','把屏幕上这张卡片收起来','关掉当前卡片就行，事项别删','这张信息卡片给我关闭一下']):
 sess='new-card-'+str(i)
 add('刚才那个提醒是什么来着','reminder_get_current',session=sess)
 add(q,'reminder_close_current',session=sess)
 add('现在屏幕上还有提醒卡片吗','reminder_get_current',session=sess,required=['没有|关闭|不在|已关'])
# 12 turns: actual brightness levels/volume fields and queries, not implicit writes.
for i,(set_q,query_q,more_q,tool,args) in enumerate([
 ('亮度弄到百分之九十','这是最高档了吗','屏幕再亮一档','self_screen_set_brightness',{'brightness':90}),
 ('音量弄到二十','我现在音量多大，查一下','再大声一点','self_audio_speaker_set_volume',{'volume':20}),
 ('屏幕给我调到最低档','现在亮度几档','调亮一点吧','self_screen_set_brightness',{'brightness':1}),
 ('声音调到最大','音量是多少，别改','声音往小了调十个点','self_audio_speaker_set_volume',{'volume':100})]):
 sess='new-settings-'+str(i)
 add(set_q,tool,args,session=sess)
 add(query_q,'self_get_device_status',session=sess)
 add(more_q,tool,{'relative':1 if 'brightness' in tool else (-10 if i==3 else 10)},session=sess)
# 12 turns: feedback, latest-state accuracy, retry and ambiguous time.
add('刚买了个书架，还没发货。我就是随便聊聊，别替我安排。',session='new-chat-a')
add('别每句话都反问我，你直接说说看法。',session='new-chat-a')
add('店家刚通知已经发货了，我还没有收到。',session='new-chat-a')
add('书架现在啥状态？别逗我，直接说。',session='new-chat-a',required=['发货|寄出|路上','没.*收|还.*到|未.*收'],forbidden=['尚未发货|还没发货|已经收到'])
add('报告上周写好一半了，昨天只是改了标题，剩下正文没碰。',session='new-chat-b')
add('昨天正文没进展，能说我正文从来没写过吗？',session='new-chat-b',required=['不能|不对|不是|不可以'])
add('你刚才说过了，别重复，也别用玩笑回避问题。',session='new-chat-b')
add('所以报告目前写了多少？',session='new-chat-b',required=['一半|半'])
add('再拍一次看看','self_camera_take_photo',{'question':'画面里有什么'},setup='photo_retry',session='new-photo',multi_step=0)
add('再拍一次看看','self_camera_take_photo',{'question':'画面里有什么'},setup='photo_retry',session='new-photo',multi_step=1,required=['杯'])
add('每天六点给老婆打电话',session='new-time',expected_clarify=True,required=['早上|上午|晚上|下午'])
add('你能听出我是谁吗？',session='new-voice',required=['没听出|没.*确认|不知道'],forbidden_tools=['self_camera_identify_person','self_camera_take_photo'])
assert len(a)==240 and sum(x.get('independent_holdout',False) for x in a)==60
(S/'final-cases.json').write_text(json.dumps(a,ensure_ascii=False,indent=2),encoding='utf-8')
print('frozen',len(a),collections.Counter(x.get('tool') for x in a))
# Reuse existing state/readback assertions, replace wording-specific checks with phase semantics.
s=Path('tools/experience-repair-20261009/run_final.py').read_text(encoding='utf-8-sig')
s=s.replace("writes=[x['tool'] for x in r['calls'] if contract(x['tool']).write]", "writes=[x['tool'] for x in results if contract(x['tool']).write and x['state'] in {'completed','accepted'}]")
s=s.replace("'memory_forget':'memory_search'", "'memory_forget':'memory_search','reminder_close_current':'reminder_get_current'")
s=s.replace("if n=='self_reboot' and (not state['reboot_requested'] or '尚未' not in speech)","if n=='self_reboot' and (not state['reboot_requested'] or re.search(r'重启(?:成功|完成|好了)',speech))")
s=s.replace("if n=='camera_face_enroll_start' and ('尚未' not in speech or state['enrollment']['state']!='capturing')", "if n=='camera_face_enroll_start' and (re.search(r'录入(?:完成|成功|好了)',speech) or state['enrollment']['state']!='capturing')")
s=s.replace("if n=='memory_correct' and ('绿茶' not in rbtext if row.get('group')=='tool' else '不喝咖啡' not in rbtext)", "if n=='memory_correct' and (row.get('expected_memory','绿茶') not in rbtext)")
s=s.replace("  if row.get('session')=='chat0'", "  for forbidden in row.get('forbidden_tools',[]):\n   if any(x['tool']==forbidden for x in results):errors.append('unrequested_tool:'+forbidden)\n  if row.get('expected_clarify') and out['mode']!='clarify':errors.append('ambiguous_time_not_clarified')\n  if row.get('session')=='chat0'")
s=s.replace(" if n=='self_reboot'", " if n=='reminder_close_current' and (state['card']['active'] or state['card'].get('last_action')!='close' or state['notes']!=before['notes']):errors.append('close_changed_business_or_not_closed')\n if n=='self_reboot'")
s=s.replace(" if n=='memory_forget' and (('银杏灯' if row.get('memory_kind')=='forget' else '我喜欢咖啡') in rbtext)", " if n=='memory_forget' and (row.get('expected_absent','银杏灯' if row.get('memory_kind')=='forget' else '我喜欢咖啡') in rbtext)")
s=s.replace("stage/'final-results.jsonl'", "stage/('development-results.jsonl' if '--development' in __import__('sys').argv else 'final-results.jsonl')")
s=s.replace("async def main():\n assert", "async def main():\n global CASES\n if '--development' in __import__('sys').argv:\n  ids={'reg-1','reg-9','reg-11','reg-27','reg-29','reg-31'}\n  CASES=[x for x in CASES if x['id'] in ids or x.get('session') in {'new-memory-0','new-card-0','new-settings-0','new-settings-1','new-chat-a','new-photo','new-time','new-voice'}]\n assert")
s=s.replace("(stage/'final-summary.json')", "(stage/('development-summary.json' if '--development' in __import__('sys').argv else 'final-summary.json'))")
# extra checks for coherent facts, same-turn duplication and personality replies.
s=s.replace(" if speech.startswith", " if re.search(r'确认操作目标或参数|确定操作目标或参数',speech):errors.append('generic_parameter_error')\n parts=[x.strip() for x in re.split('[。！？!?]',speech) if len(x.strip())>8]\n if len(parts)!=len(set(parts)):errors.append('duplicate_sentence')\n if speech.startswith")
(S/'run_model.py').write_text(s,encoding='utf-8')
