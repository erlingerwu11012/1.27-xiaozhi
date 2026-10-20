from pathlib import Path
import re,json,hashlib
B=Path('tools/hardware-repair-20261009');W=B/'work'
def edit(name,old,new):
 p=W/name;s=p.read_text(encoding='utf-8');assert old in s,(name,old[:70]);p.write_text(s.replace(old,new,1),encoding='utf-8')
def write(name,s):
 p=W/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(s,encoding='utf-8')
write('core/utils/tool_harness/memory_policy.py',r'''"""Current-turn memory authority and normalized facts. No model-supplied identity."""
import hashlib,json,re

def normalize_fact(value):
    if not isinstance(value,str):return ''
    text=value.strip()
    for _ in range(3):
        if not text.startswith('{'):break
        try:row=json.loads(text)
        except (ValueError,TypeError):return ''
        if not isinstance(row,dict) or not isinstance(row.get('content'),str):return ''
        if row.get('role') not in (None,'user'):return ''
        text=row['content'].strip()
    if not text or re.search(r'[{}]|\[来源[:：]|verified_results|tool_calls|catalog_version',text):return ''
    if re.search(r'[？?]|(?:我|你).{0,15}(?:喜欢|爱喝|喝过|爱吃).{0,8}(?:什么|啥)|(?:你还|还)?记得.{0,8}(?:吗|么)|怎么|为什么|能不能|是不是',text):return ''
    return text

def memory_intent(query):
    from core.utils.operation_control import content_text
    q=content_text(query).strip()
    if re.search(r'你(?:在|又|刚才)?(?:更正|修改|纠正).{0,8}(?:什么|啥)|(?:更正|修改|纠正).{0,4}什么|我(?:就|只是)?.{0,3}问|上下文|看不着|看不到|别(?:修改|更正|纠正|删除)|不要(?:修改|更正|纠正|删除)',q):return 'read'
    if re.search(r'忘掉|忘记|遗忘|别记着|不要记着|删.{0,5}记忆',q):return 'forget'
    if re.search(r'改一下|改成|改为|更正|纠正|更新.{0,5}(?:记忆|偏好)|修改.{0,5}(?:记忆|偏好)',q):return 'correct'
    return 'read'

def item_version(text):return hashlib.sha256(text.encode()).hexdigest()
''')
edit('core/utils/tool_harness/presentation.py',"text=item.get('text')", "from .memory_policy import normalize_fact\n        text=normalize_fact(item.get('text'))")
edit('core/utils/tool_harness/presentation.py',"text in seen:continue", "text.strip() in seen:continue")
edit('core/utils/tool_harness/presentation.py',"if re.match(r\"^[{]\\s*['\\\"]|^\\[\\s*[{]\",text):", "if re.search(r\"[\\\"'](?:speaker|content|record_id|tool_calls)[\\\"']\\s*:|^[{]\\s*['\\\"]|^\\[\\s*[{]\",text):")
for name in ['core/utils/tool_harness/presentation.py','core/utils/tool_harness/contracts.py']:
 p=W/name;s=p.read_text().replace("speaker.get('output_volume')", "speaker.get('volume',speaker.get('output_volume'))");p.write_text(s)
edit('core/utils/tool_harness/contracts.py',"code=body.get('errorCode') if isinstance(body,dict) else None", "code=body.get('errorCode') if isinstance(body,dict) else None\n    if isinstance(body,dict) and body.get('status')=='identity_unknown':\n        return out('failed','这次没听出是谁，请本人再说一句，确认身份后再查询。','identity_unconfirmed')")
edit('core/utils/tool_harness/contracts.py',"elif name=='self_camera_take_photo':valid=isinstance(body,str) and len(body)>=2 and not body.startswith(('错误','失败','error'))", "elif name=='self_camera_take_photo':\n            valid=(isinstance(body,str) and len(body)>=2 and not body.startswith(('错误','失败','error'))) or (isinstance(body,dict) and body.get('success') is True and isinstance(body.get('response'),str) and bool(body['response'].strip()))\n            if valid and isinstance(body,dict):body=body['response']")
edit('core/utils/tool_harness/runtime.py',"if re.search(r'忘掉|忘记|遗忘|删|更正|纠正|改成|改为|记住|保存|记录|[“”「」]',q):return None", "from .memory_policy import memory_intent\n    if memory_intent(q)!='read' or re.search(r'记住|保存|记录|[“”「」]',q):return None")
edit('core/utils/tool_harness/runtime.py',"if re.search(r'(?:查|搜|检索).{0,25}(?:我|记忆|以前|之前)|你还记得|记忆库',q):return q", "if re.search(r'(?:查|搜|检索|回忆).{0,25}(?:我|记忆|以前|之前)|你还记得|记忆库|(?:我|你).{0,15}(?:喜欢|爱喝|爱吃).{0,8}(?:什么|啥)|上下文|看不着|看不到',q):return q")
edit('core/utils/tool_harness/runtime.py',"outcome=await self._run(query,messages,deadline,scope,epoch)\n            self.last_outcome=outcome", "outcome=await self._run(query,messages,deadline,scope,epoch)\n            if not outcome.interrupted and self.valid(scope,epoch):\n                from .reply_composer import compose\n                outcome=await compose(self,query,messages,outcome,deadline)\n            self.last_outcome=outcome")
edit('core/utils/tool_harness/runtime.py',"self.validate_step(s,tools)\n                    if prohibited", "self.validate_step(s,tools)\n                    if s.tool in {'memory_correct','memory_forget'}:\n                        from .memory_policy import memory_intent\n                        intent=memory_intent(query)\n                        if intent!=('correct' if s.tool=='memory_correct' else 'forget'):raise ValueError('memory_write_not_requested_this_turn')\n                    if prohibited")
old="""match=arguments.get('match','')
                            if match!='*' and (not isinstance(match,str) or not match or len(match)>1024 or not any(match==item['text'] for item in verified_items)):
                                raise ValueError('memory_requires_single_verified_fact')"""
new="""match=arguments.get('match','')
                            record=arguments.get('record_id')
                            selected=[item for item in verified_items if (item.get('record_id')==record if record else item['text']==match)]
                            if match!='*' and len(selected)!=1:raise ValueError('memory_target_not_unique')
                            if selected:
                                item=selected[0];arguments['match']=item['text']
                                if record:
                                    from .memory_policy import item_version
                                    actual=item.get('version') or item_version(item['text'])
                                    if arguments.get('expected_version') not in (None,'',actual):raise ValueError('memory_record_changed')
                                    arguments['expected_version']=actual"""
edit('core/utils/tool_harness/runtime.py',old,new)
edit('core/utils/tool_harness/runtime.py',"pre_args={'query':arguments['match']} if pre=='memory_search' else {}", "pre_args={'query':arguments.get('match') or query} if pre=='memory_search' else {}")
edit('core/utils/tool_harness/runtime.py',"if not outcome.reply:outcome.reply='这次没有执行成功，需要确认操作目标或参数。'", "if not outcome.reply:\n            reasons={'memory_target_not_unique':'检索到了不同的旧记录，还没有修改。请说明要改的是哪一项。','memory_record_changed':'那条记忆刚发生了变化，这次没有覆盖它。','memory_write_not_requested_this_turn':'你这次是在查询，我没有修改记忆。','memory_requires_single_verified_fact':'没有定位到对应的单条旧记忆，这次没有修改。','write_goal_requires_write_steps':'这次只完成了前面的查询，设置操作没有执行。'}\n            outcome.reply=reasons.get(outcome.error.split(':',1)[0], '这次请求没有执行完，尚未确认任何新的修改。')")
# Memory writes are required targets even when the model only plans a read.
edit('core/utils/tool_harness/runtime.py',"targets=set();card_reference=False;card_instruction=False", "targets=set();card_reference=False;card_instruction=False\n        from .memory_policy import memory_intent\n        intent=memory_intent(query)\n        if intent in {'correct','forget'}:targets.add('memory_'+intent)")
# Highest/maximum in a query is not a write request.
edit('core/utils/tool_harness/runtime.py',"if not display_config and re.search(noun,clause) and re.search", "if not display_config and not re.search(r'是不是|是否|已经|现在是|这是|吗|么|多少|几档',clause) and re.search(noun,clause) and re.search")
# No camera interpretation of voice recognition or a complaint.
edit('core/utils/tool_harness/runtime.py',"if memory_query and 'memory_search' in tools:", "if re.search(r'听.{0,5}(?:出|出来).{0,8}(?:谁|我)|你连我是谁|声音.{0,6}(?:认|谁)',plain) and not re.search(r'拍|摄像|看脸|人脸',plain):\n            actor=current_turn(self.conn)\n            outcome.mode='chat';outcome.reply=('听出来了，你是'+actor.display_name+'。') if actor and actor.eligible and actor.display_name else '这次没听出是谁，请再说一句让我确认。'\n            return outcome\n        if memory_query and 'memory_search' in tools:")
# Habit time ambiguity is handled before any write; model can supply an explicit clarification.
edit('core/utils/tool_harness/runtime.py',"quoted_note=quoted_note_request(query)\n        adjustments=", "quoted_note=quoted_note_request(query)\n        if not prohibited and re.search(r'每天|习惯',plain) and re.search(r'加|设|提醒|创建|新增',plain) and re.search(r'[零〇一二两三四五六七八九十\\d]+[点时]',plain) and not re.search(r'早|晨|上午|中午|下午|晚上|夜|凌晨|傍晚|(?:1[3-9]|2[0-3])[:：点时]',plain):\n            outcome.mode='clarify';outcome.reply='你说的六点，是早上还是晚上？' if re.search(r'六点|6点',plain) else '这个时间是上午还是下午？'\n            self.pending=(scope,time.monotonic(),{'user':query,'question':outcome.reply,'goal':'确认习惯时间'});return outcome\n        adjustments=")
# Guidance: record-based mutation, direct answers, and neutral handling of errors.
p=W/'core/utils/tool_harness/runtime.py';s=p.read_text();s=s.replace("用其完整单条text作为match（最多1024字）", "传record_id和expected_version，match仅用于兼容旧接口")
s=s.replace("删除或更正某条记忆前先memory_search查询旧信息，match必须是实际查询结果中可核对的原文片段，不能补入“我”等不在原记录中的字。", "删除或更正记忆只接受本轮明确要求。先memory_search，使用结果record_id与version定位；不要猜ID，不要把历史修改要求带到当前查询。")
s=s.replace("人物和权限只使用可信服务端上下文；", "普通问题必须先回答问题本身。用户质疑、纠错或表示不满时停止玩笑，不用玩笑代替答案，不复述上轮套话。提问我爱喝什么、之前上下文呢只能查询，不能更正。工具结果后的自然回答由同一主模型单独依据可信结果生成。\n人物和权限只使用可信服务端上下文；")
p.write_text(s)
# Plugin schema, backward-compatible optional record address.
p=W/'plugins_func/functions/person_memory.py';s=p.read_text();s=s.replace('async def memory_forget(conn,match):','async def memory_forget(conn,match="",record_id="",expected_version=""):').replace('async def memory_correct(conn,match,replacement):','async def memory_correct(conn,match="",replacement="",record_id="",expected_version=""):')
s=s.replace('await override(conn,"forget",match)', 'await override(conn,"forget",match,record_id=record_id,expected_version=expected_version)').replace('await override(conn,"correct",match,replacement)', 'await override(conn,"correct",match,replacement,record_id=record_id,expected_version=expected_version)')
s=s.replace('{"match":{"type":"string"}},["match"]', '{"match":{"type":"string"},"record_id":{"type":"string"},"expected_version":{"type":"string"}},[]')
s=s.replace('{"match":{"type":"string"},"replacement":{"type":"string"}},["match","replacement"]', '{"match":{"type":"string"},"replacement":{"type":"string"},"record_id":{"type":"string"},"expected_version":{"type":"string"}},["replacement"]')
p.write_text(s)
edit('core/utils/recent_memory.py','async def override(conn, action, match, replacement=None):','async def override(conn, action, match="", replacement=None, record_id="", expected_version=""):')
edit('core/utils/recent_memory.py',"if action not in {'correct','forget'} or not isinstance(match,str) or not match or len(match)>1024:", "if action not in {'correct','forget'} or not isinstance(match,str) or (not match and not record_id) or len(match)>1024:")
edit('core/utils/recent_memory.py',"json={'actor':actor.payload(),'action':action,'match':match,'replacement':replacement},timeout=3)", "json={'actor':actor.payload(),'action':action,'match':match,'replacement':replacement,'recordId':record_id,'expectedVersion':expected_version},timeout=3)\n    match=result.get('resolved_match',match) if isinstance(result,dict) else match")
# Provider default; authoritative management config is changed at deployment only.
p=W/'core/utils/voiceprint_provider.py';s=p.read_text().replace('默认0.4','默认0.3').replace('config.get("similarity_threshold", 0.4)','config.get("similarity_threshold", 0.3)');p.write_text(s)
print('server patch applied')
