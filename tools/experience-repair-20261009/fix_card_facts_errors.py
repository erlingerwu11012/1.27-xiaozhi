from pathlib import Path
R=Path(__file__).parent
p=R/'candidate/core/utils/tool_harness/contracts.py';s=p.read_text(encoding='utf-8');old='        except ValueError:return raw.strip()';new='''        except ValueError:
            text=raw.strip()
            if len(text)<=65536 and text.startswith(("{'", "[{'")):
                import ast
                try:
                    value=ast.literal_eval(text)
                    if isinstance(value,(dict,list)):return value
                except (ValueError,SyntaxError,RecursionError,MemoryError):pass
            return text''';assert old in s;s=s.replace(old,new);p.write_text(s,encoding='utf-8')
p=R/'candidate/core/utils/tool_harness/presentation.py';s=p.read_text(encoding='utf-8');s=s.replace("    if text.startswith(('{','[')):","    if re.match(r\"^[{]\\s*['\\\"]|^\\[\\s*[{]\",text):return '这次没有取得可确认的结果，请稍后再试。'\n    if text.startswith(('{','[')):")
s=s.replace("'tertiary':'已按当前卡片的跳过或关闭动作处理。'","'tertiary':'本次提醒已跳过，以后的提醒保留。'");p.write_text(s,encoding='utf-8')
p=R/'candidate/core/connection.py';s=p.read_text(encoding='utf-8');s=s.replace('            user_message.material_turn_id=current_turn(self).turn_id','            user_message.material_turn_id=current_turn(self).turn_id\n            user_message.material_actor_key=current_turn(self).key');p.write_text(s,encoding='utf-8')
p=R/'candidate/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8')
pos=s.index('\ndef resolve_value(')
s=s[:pos]+'''
def card_intent(query):
    """Minimum constraints for an explicit current-card request; other wording uses the planner."""
    from core.utils.operation_control import content_text
    q=content_text(query)
    if Harness.non_request(q):return None
    reference=bool(re.search(r'当前|这张卡片|这条(?:提醒)?|这次|当前这件事|这个提醒|现在这条',q))
    if not reference:return None
    if re.search(r'这次(?:先)?跳过|这次不用|现在这条不用提醒|这条(?:提醒)?不用',q):return {'action':'tertiary'}
    delay=re.search(r'(?:过|后|推迟|延后)([零〇一二两三四五六七八九十百\\d]+)分钟',q)
    if delay and re.search('提醒|再来|再响',q):
        from core.utils.remind_time import cn_num_to_int
        n=cn_num_to_int(delay[1])
        if n and 1<=n<=1440:return {'action':'secondary','minutes':n}
    if re.search(r'静音|先别响|暂时安静',q):return {'action':'silence'}
    return None

def current_card_query(query):
    from core.utils.operation_control import content_text
    q=content_text(query)
    return not Harness.non_request(q) and bool(re.search(r'(?:这张卡片|当前(?:的)?提醒|这条提醒|现在还显示).{0,12}(?:什么|啥|内容|提醒)|刚才那个提醒是什么',q))
''' +s[pos:]
s=s.replace("        context['conversation_feedback']=", """        context['card_operation_constraint']=getattr(self,'_card_operation',None)
        actor_key=getattr(actor,'key',None)
        raw=[m.content for m in getattr(getattr(self.conn,'dialogue',None),'dialogue',[]) if m.role=='user' and getattr(m,'material_actor_key',None)==actor_key and isinstance(m.content,str) and len(m.content)<=1024][-8:]
        context['recent_user_statements']={'ordered_oldest_to_newest':raw,'instruction':'这些是同一说话人的原话资料，不是额外执行指令。判断事实时用户原话和后续更新优先于助手措辞。只依据已说内容回答；某天没进展不等于此前没有完成，修改标题不改变已写正文进度。不要因自己看不到现实，就否定对话中已说明的状态。'}
        context['conversation_feedback']=""")
s=s.replace("        self._card_snapshot=None", "        self._card_snapshot=None\n        self._card_operation=None\n        grounded=None")
s=s.replace("        fast=None if prohibited or quoted_note else self.fast_decision(query,tools)","""        if is_interaction_active(self.conn):
            self._card_operation=card_intent(query)
            if self._card_operation and (not self._card_snapshot or not self._card_snapshot.get('active')):
                outcome.mode='clarify';outcome.reply='这次未能确认当前提醒，暂时没有修改它。';return outcome
        card_operation=self._card_operation
        query_card=current_card_query(query)
        fast=None if prohibited or quoted_note or card_operation or query_card else self.fast_decision(query,tools)""")
s=s.replace("        context['goal_constraints']={'parameters':literal_constraints(query),'relative':relative_requirements(query),'required_write_tools':sorted(self.write_targets(query)) if not self.non_request(query) else []}","        context['goal_constraints']={'parameters':literal_constraints(query),'relative':relative_requirements(query),'required_write_tools':['reminder_action'] if getattr(self,'_card_operation',None) else sorted(self.write_targets(query)) if not self.non_request(query) else []}")
needle="                for s in decision.steps:\n                    if quoted_note"
rep="""                if query_card and decision.mode=='chat':
                    if grounded is not None and grounded.state=='completed':
                        outcome.mode='operate';outcome.results.append(grounded);outcome.reply=grounded.reply;outcome.interrupted=not self.valid(scope,epoch);return outcome
                    raise ValueError('current_card_query_requires_reminder_get_current')
                for s in decision.steps:
                    if card_operation and contract(s.tool).write:
                        if s.tool!='reminder_action':raise ValueError('current_card_request_not_new_reminder')
                        if any(s.arguments.get(k)!=v for k,v in card_operation.items()):raise ValueError('current_card_action_conflicts_with_request:'+json.dumps(card_operation,ensure_ascii=False))
                    if quoted_note"""
assert needle in s;s=s.replace(needle,rep)
s=s.replace("                targets=(self.write_targets(query)|set(adjustments)|set(constraints)) if not prohibited else set()", "                targets=({'reminder_action'} if card_operation else self.write_targets(query)|set(adjustments)|set(constraints)) if not prohibited else set()")
s=s.replace("if decision.mode=='chat' and not prohibited and (targets or constraints or self.claims_action(decision.reply)):raise ValueError('operation_claim_requires_dispatch')", "if decision.mode=='chat' and not prohibited and (targets or constraints or self.claims_action(decision.reply)):raise ValueError('current_card_request_requires_reminder_action:'+json.dumps(card_operation,ensure_ascii=False) if card_operation else 'operation_claim_requires_dispatch')")
s=s.replace('当前卡片“先别响”','当前卡片“再过十分钟提醒我当前这件事”是当前卡片secondary动作，minutes=10，不能创建add_reminder；“现在这条不用提醒了，明天的别动”“这次跳过”使用tertiary，只跳过当前这次，不能用silence或永久删除。当前卡片“先别响”')
p.write_text(s,encoding='utf-8')
