from pathlib import Path
S=Path('tools/hardware-repair-20261009');W=S/'work';J=S/'java'
p=W/'core/utils/tool_harness/memory_policy.py';s=p.read_text().replace('音量|亮度|屏幕|卡片|闹钟|拍照|相机|壁纸|渲染','音量|亮度|屏幕|卡片|闹钟|拍照|相机|壁纸|渲染|习惯|便签|提醒');s=s.replace("    if re.search(r'忘掉", "    if re.search(r'为什么|怎么|什么|啥|你忘记|忘记.{0,4}(?:吗|么)|如果|假设|这句话',q):return 'read'\n    if re.search(r'忘掉");p.write_text(s)
p=J/'PersonMemoryService.java';s=p.read_text().replace('String value=Objects.toString(map.get("content"),Objects.toString(map.get("custom_content"),"")).strip();','String value=RecentArchiveService.normalizeFact(Objects.toString(map.get("content"),Objects.toString(map.get("custom_content"),"")));\n            if(!RecentArchiveService.factualUser(value))continue;')
s=s.replace('"source","cloud_user_fact"','"source","cloud_user_fact","version",MemoryGatewayClient.sha(value),"owner",actor.getPersonId()').replace('"override:"+MemoryGatewayClient.sha(value)','"override:"+override.get("id")').replace('"source","local_override"','"source","local_override","version",MemoryGatewayClient.sha(value),"owner",actor.getPersonId()');p.write_text(s)
p=J/'RecentArchiveService.java';s=p.read_text().replace('Set.of("archive","material","override")','Set.of("archive","material","override","cloud")');old='''            String sql=switch(parts[0]) {''';s=s.replace(old,'''            if("cloud".equals(parts[0])) {
                if(match==null || match.isBlank())throw new RenException("请先查询要修改的记忆");
                @SuppressWarnings("unchecked") var facts=(List<Map<String,Object>>)memory.search(actor,match).get("items");
                var selected=facts.stream().filter(item->Objects.equals(item.get("record_id"),recordId)).toList();
                if(selected.size()!=1 || !Objects.equals(selected.get(0).get("version"),expectedVersion))throw new RenException("记忆版本已变化，请重新查询");
                resolved=Objects.toString(selected.get(0).get("text"),"");
                var result=new LinkedHashMap<String,Object>(memory.override(actor,action,resolved,replacement));
                result.put("resolved_match",resolved);return result;
            }
            String sql=switch(parts[0]) {''')
# Suppression addresses the selected source even if the old JSON used escaped unicode.
old='''        result.put("resolved_match",resolved);return result;
    }

    static boolean factualUser'''
new='''        if(recordId!=null && recordId.startsWith("archive:"))jdbc.update("UPDATE ai_agent_chat_history SET recall_allowed=FALSE WHERE id=? AND account_id=? AND person_id=? AND default_generation=? AND agent_id=?",recordId.substring(8),actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),actor.getAgentId());
        if(recordId!=null && recordId.startsWith("material:"))jdbc.update("UPDATE ai_person_material SET recall_allowed=FALSE WHERE id=? AND account_id=? AND user_id=? AND generation=? AND agent_id=?",recordId.substring(9),actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),actor.getAgentId());
        result.put("resolved_match",resolved);return result;
    }

    static boolean factualUser'''
assert old in s;s=s.replace(old,new);p.write_text(s)
# Deduplicate only identical sentences in the same generated answer.
p=W/'core/utils/tool_harness/presentation.py';s=p.read_text();s=s.replace("    return re.sub(r'。{2,}','。',text).strip()",'''    sentences=re.findall(r'[^。！？!?\\n]+[。！？!?]*',text)
    seen=set();parts=[]
    for sentence in sentences:
        key=sentence.strip(' 。！？!?\\n')
        if key and key not in seen:parts.append(sentence.strip());seen.add(key)
    return re.sub(r'。{2,}','。',''.join(parts)).strip()''');p.write_text(s)
# Preserve session-local response preferences across recognition failures, not identity authority.
p=W/'core/utils/tool_harness/runtime.py';s=p.read_text().replace("return {'no_optional_questions':no_questions}","return {'no_optional_questions':no_questions,'no_jokes':any(re.search(r'别逗|别开玩笑|别捉弄|直接回答|你刚才说过|重复|说过了',str(t)) for t in statements)}")
s=s.replace("self._reply_preferences=reply_preferences(statements+[query])", "self._reply_preferences=reply_preferences(list(getattr(self.conn,'_response_feedback',[]))+statements+[query])\n        if re.search(r'别逗|别开玩笑|别捉弄|直接回答|别反问|不要反问|说过了|重复',plain):\n            feedback=list(getattr(self.conn,'_response_feedback',[]));feedback.append(plain);self.conn._response_feedback=feedback[-8:]")
s=s.replace("                    if decision.mode=='chat' and not prohibited and (targets", "                    prior_text=next((m.get('content') for m in reversed(messages[:-1]) if m.get('role')=='assistant' and m.get('content')),None)\n                    if decision.mode=='chat' and decision.reply.strip()==str(prior_text).strip() and not re.search(r'再说|重说|重复一遍',plain):raise ValueError('duplicate_previous_answer_answer_current_question')\n                    if decision.mode=='chat' and not prohibited and (targets")
p.write_text(s)
# Reject unverified numeric claims and repeated replies. Facts remain authoritative.
p=W/'core/utils/tool_harness/reply_composer.py';s=p.read_text();s=s.replace("    return False\n\nasync",'''    for r in results:
        if r.tool in {'self_audio_speaker_set_volume','self_screen_set_brightness'} and r.state=='completed':
            key='volume' if 'volume' in r.tool else 'brightness';noun='音量|声音' if key=='volume' else '亮度|屏幕'
            expected=r.payload.get(key) if isinstance(r.payload,dict) else None
            for value in re.findall(r'(?:'+noun+r').{0,10}?(\\d+)(?:%|％|档|[。！,， ])',text+' '):
                if expected is not None and int(value)!=expected:return True
    return False

async''')
s=s.replace("    if not results:return outcome", "    if not results:return outcome\n    from .contracts import contract")
s=s.replace("GUIDANCE+'\\n本轮可信时钟：'", "GUIDANCE+'\\n当前回复偏好：'+json.dumps(getattr(harness,'_reply_preferences',{}),ensure_ascii=False)+'\\n本轮可信时钟：'")
s=s.replace("        if unsafe(text,results):", "        previous=next((m['content'] for m in reversed(recent) if m['role']=='assistant'),None)\n        if text==previous and not re.search(r'再说|重说|重复一遍',query):raise ValueError('duplicate_previous_reply')\n        if unsafe(text,results):");p.write_text(s)
print('memory version and feedback fixes applied')
