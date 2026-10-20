from pathlib import Path

root=Path(__file__).parent/'work'
def edit(path,old,new):
 p=root/path;s=p.read_text(encoding='utf-8');assert old in s,(path,old[:100]);p.write_text(s.replace(old,new,1),encoding='utf-8')

runtime='core/utils/tool_harness/runtime.py'
edit(runtime,'mode为chat/clarify/operate/continue；普通聊天reply，操作steps。','mode为chat/clarify/operate/continue/retrieve；普通聊天reply，操作steps。')
edit(runtime,'省略默认字段，操作reply留空。','控制字段mode、goal、steps、finished、task_action、authorized_writes、retrieval_query、task_update必须先输出，reply必须最后输出。空值使用空串、[]或null；操作reply留空。')
edit(runtime,'工具使用索引的准确名称，相关schema按需提供，不以评分决定执行。','只提供本轮少量相关工具Schema，不是完整能力列表。需要实际查询或操作却没有对应工具时，先返回mode=retrieve、retrieval_query描述所需能力、steps=[]，不猜工具名。每个请求最多补检一次，检索不执行、不增加权限。收到补检结果后，仅使用可用Schema；未接入、设备不支持、权限不足、暂不可用应准确说明，不能假装完成。工具使用本轮Schema的准确名称，不以评分决定执行。')
edit(runtime,'task_action默认none；','澄清真正缺少的参数或对象，问题只问最少必要信息；task_update={target_tool:本轮工具名,parameters:已明确参数,missing_fields:缺少的Schema字段}。服务器校验后保存，无法确定工具时task_update=null并直接问对象。普通闲聊无需追问。task_action默认none；')
edit(runtime,"        from core.providers.tools.tool_catalog import ToolCatalogBuilder\n        from core.providers.tools.tool_selector import ToolSelector\n        catalog=ToolCatalogBuilder().build([d.description for d in tools.values()],tools)\n        selection=ToolSelector(policy=selection_policy()).select(query,catalog,turn_id='harness',mode='enabled')", "        from .retrieval import recall")
p=root/runtime;s=p.read_text(encoding='utf-8');start=s.index('        # Recall controls only initial schema size.');end=s.index('        detail=[tools[n].description',start)
s=s[:start]+'''        required=sorted(self.write_targets(query)) if not self.non_request(query) else []
        from core.utils.reminder_interaction import is_interaction_active
        if is_interaction_active(self.conn):required+=['reminder_get_current','reminder_action','reminder_close_current']
        previous=getattr(self,'last_outcome',None) if getattr(self,'last_outcome_scope',None)==self.scope() else None
        selected=recall(query,tools,selection_policy(),self.available_task(),previous,required,sorted(expanded))
        self.shown=set(selected)
        self.observe('recall',candidate_count=len(selected),supplemental_count=getattr(self,'_retrieval_count',0))
'''+s[end:]
s=s.replace("'index':index,'schemas':detail","'schemas':detail,'retrieval':getattr(self,'_retrieval_status',None)")
s=s.replace("request=list(messages)+[{'role':'system','content':GUIDANCE+'\\n[本轮可信目录与执行状态]\\n'+json.dumps(context,ensure_ascii=False)}]","from .prompt_cache import cached_prefix\n        request=cached_prefix(messages,GUIDANCE)+[{'role':'system','content':'[本轮可信目录与执行状态]\\n'+json.dumps(context,ensure_ascii=False)}]")
p.write_text(s,encoding='utf-8')
edit(runtime,"        self.decide=decide or conn.llm.decision","        self.decide=decide or conn.llm.decision\n        self.stream_decide=None if decide else getattr(conn.llm,'decision_stream',None)")
edit(runtime,"        raw=await asyncio.wait_for(asyncio.to_thread(self.decide,messages),remaining)","""        def emit(text):
            output=getattr(self.conn,'_harness_speech_output',None)
            if not output:return
            def check(candidate):
                from .presentation import safe_speech
                query=getattr(self,'_user_request','')
                if safe_speech(candidate)!=candidate or self.claims_action(candidate):return False
                if self.write_targets(query) or getattr(self,'_explicit_query_tools',set()):return False
                if memory_read_request(query) or live_read_request(query):return False
                if chat_fact_conflict(candidate,getattr(self,'_stream_messages',[]),query):return False
                return True
            output.feed(text,check)
        self._stream_messages=messages
        call=(lambda:self.stream_decide(messages,emit)) if self.stream_decide else (lambda:self.decide(messages))
        raw=await asyncio.wait_for(asyncio.to_thread(call),remaining)""")
edit(runtime,"        original_query=query;self._resuming_task=False","        original_query=query;self._resuming_task=False\n        self._retrieval_count=0;self._retrieval_status=None")
edit(runtime,"                task=self.available_task()\n                if task and decision.task_action", """                if decision.mode=='retrieve':
                    if self._retrieval_count:raise ValueError('retrieval_budget_exhausted')
                    from .retrieval import retrieve,availability
                    self._retrieval_count+=1
                    expanded.update(retrieve(decision.retrieval_query,tools,selection_policy()))
                    self._retrieval_status=availability(decision.retrieval_query,self.manager,tools,expanded)
                    error='supplemental_retrieval_complete; use supplied schemas or explain availability'
                    self.observe('retrieve',count=self._retrieval_count,candidate_count=len(expanded))
                    continue
                task=self.available_task()
                if task and decision.task_action""")
edit(runtime,"                    query=task.supplement(original_query,turn);self._resuming_task=True", "                    if decision.task_update:task.update(decision.task_update,tools,turn,original_query)\n                    query=task.supplement(original_query,turn);self._resuming_task=True")
edit(runtime,"                    expanded.update(unshown);error='schema_expanded: use the newly supplied schemas';continue", "                    raise ValueError('tool_schema_not_provided: request mode=retrieve before using another capability')")
edit(runtime,"self.save_task(scope,query,decision.reply,decision.goal)","self.save_task(scope,query,decision.reply,decision.goal,decision.task_update)")
# Both clarification branches must store the structured update.
p=root/runtime;s=p.read_text(encoding='utf-8').replace('self.save_task(scope,query,decision.reply,decision.goal)','self.save_task(scope,query,decision.reply,decision.goal,decision.task_update)');p.write_text(s,encoding='utf-8')
edit(runtime,"    def save_task(self,scope,query,question,goal=''):","    def save_task(self,scope,query,question,goal='',patch=None):")
edit(runtime,"        self.pending=(scope,self.task.created,", "        if patch:\n            self.task.update(patch,self.catalog(),actor.turn_id,query)\n            if contract(patch.target_tool).write:self.task.write_tools=[patch.target_tool]\n        self.pending=(scope,self.task.created,")
# Object-free relative commands must go through contextual understanding.
edit(runtime,"        if relative:\n            name='self_audio_speaker_set_volume' if relative[1] in {'大声','小声'} else 'self_screen_set_brightness'\n            if name in tools:return Decision(mode='operate',goal=query,steps=[{'id':'relative','tool':name,'arguments':{},'relative':10 if relative[1] in {'大声','亮'} else -10}])", "        if relative:return None")

edit('core/utils/prompt_manager.py','            self._get_weather_info(conn, local_address)','            # Weather is queried only by an explicit on-demand tool request.')
p=root/'core/utils/prompt_manager.py';s=p.read_text(encoding='utf-8');a=s.index('                if local_address:\n                    weather_info, weather_ts');b=s.index('\n',s.index('                        )',a))+1;s=s[:a]+s[b:];a=s.index('            if weather_info:\n');b=s.index('            enhanced_prompt',a);s=s[:a]+s[b:];s=s.replace('f"device_prompt:{device_id}"','f"device_prompt:harness-stream-v1:{device_id}"');p.write_text(s,encoding='utf-8')

provider='core/providers/llm/openai/openai.py'
p=root/provider;s=p.read_text(encoding='utf-8');a=s.index('    def response_with_functions(',s.index('    def decision('));s=s[:a]+'''    def decision_stream(self,messages,on_reply=None):
        """Consume real network chunks; control metadata gates incremental speech."""
        from core.utils.tool_harness.stream_decision import ReplyStream
        from core.utils.tool_harness.models import Decision
        required={'mode','goal','steps','finished','task_action','authorized_writes','retrieval_query','task_update'}
        def admit(meta):
            if not required<=set(meta):return False
            try:draft=Decision.model_validate(dict(meta,reply='待确认'))
            except Exception:return False
            return draft.mode in {'chat','clarify'} and not draft.steps and not draft.authorized_writes
        parser=ReplyStream(on_reply,admit)
        params={'model':self.model_name,'messages':messages,'stream':True,
                'stream_options':{'include_usage':True},'temperature':self.temperature,
                'max_tokens':1800,'response_format':{'type':'json_object'},
                'extra_body':{'enable_thinking':False,'preserve_thinking':False}}
        if self.hardware_context:params['extra_headers']=request_headers(self.hardware_context['account_id'],self.hardware_context['operation'])
        self.last_usage=None
        started=time.monotonic();first=None;finish=None;chunks=0
        stream=self.client.with_options(max_retries=0,timeout=45).chat.completions.create(**params)
        try:
            for chunk in stream:
                chunks+=1
                if chunk.usage:self.last_usage=chunk.usage.model_dump()
                if not chunk.choices:continue
                choice=chunk.choices[0]
                if getattr(choice.delta,'tool_calls',None):raise ValueError('unexpected_native_calls_in_decision')
                if choice.delta.content:
                    if first is None:first=time.monotonic()-started
                    parser.feed(choice.delta.content)
                if choice.finish_reason:finish=choice.finish_reason
            if finish!='stop':raise ValueError('incomplete_decision')
            return parser.finish()
        finally:
            stream.close()
            self.last_decision_timing={'network_chunks':chunks,'first_delta_seconds':first,'total_seconds':time.monotonic()-started}

'''+s[a:];p.write_text(s,encoding='utf-8')

# Result generation uses the same streaming adapter, with cumulative fact guards.
composer='core/utils/tool_harness/reply_composer.py'
edit(composer,'reply为最终口语回答。','控制字段必须全部先输出，retrieval_query为空、task_update=null、task_action=none、goal为空，reply最后输出，为最终口语回答。')
edit(composer,"    request=systems+recent+[", "    from .prompt_cache import cached_prefix\n    request=cached_prefix(systems+recent,GUIDANCE)+[")
edit(composer,"        draft=await asyncio.wait_for(asyncio.to_thread(harness.decide,request),remaining)","""        def emit(text):
            output=getattr(conn,'_harness_speech_output',None)
            if output:output.feed(text,lambda candidate:safe_speech(candidate)==candidate and not unsafe(candidate,results) and not status_conflict(candidate,results,harness.catalog()))
        call=(lambda:harness.stream_decide(request,emit)) if harness.stream_decide else (lambda:harness.decide(request))
        draft=await asyncio.wait_for(asyncio.to_thread(call),remaining)""")

connection='core/connection.py'
edit(connection,"                future=asyncio.run_coroutine_threadsafe(harness.run(query,messages,request_epoch=request_epoch),self.loop)","""                from core.utils.tool_harness.speech_output import SpeechOutput
                stream_turn=[turn_sid,turn_epoch]
                def stream_begin():
                    self.client_abort=False
                    sid,epoch=begin_tts_turn(self,stream_turn[0],epoch=getattr(self,'tts_abort_epoch',0))
                    stream_turn[:]=[sid,epoch]
                    self.enqueue_tts(TTSMessageDTO(sentence_id=sid,sentence_type=SentenceType.FIRST,content_type=ContentType.ACTION,abort_epoch=epoch))
                def stream_send(fragment):
                    sid,epoch=stream_turn
                    self.enqueue_tts(TTSMessageDTO(sentence_id=sid,sentence_type=SentenceType.MIDDLE,content_type=ContentType.TEXT,content_detail=fragment,abort_epoch=epoch))
                def stream_end():
                    sid,epoch=stream_turn
                    self.enqueue_tts(TTSMessageDTO(sentence_id=sid,sentence_type=SentenceType.LAST,content_type=ContentType.ACTION,abort_epoch=epoch))
                speech=SpeechOutput(lambda:harness.valid(request_scope,request_epoch),stream_begin,stream_send,stream_end)
                self._harness_speech_output=speech
                future=asyncio.run_coroutine_threadsafe(harness.run(query,messages,request_epoch=request_epoch),self.loop)""")
edit(connection,"                        harness.observe('discard',reason=outcome.error or 'superseded_response')\n                        return True", "                        speech.abort()\n                        harness.observe('discard',reason=outcome.error or 'superseded_response')\n                        return True")
p=root/connection;s=p.read_text(encoding='utf-8');a=s.index('                self.client_abort=False\n                if turn_epoch!=',s.index('                from core.utils.tool_harness.speech_output'));b=s.index('                self.llm_finish_task=True',a);s=s[:a]+'''                text=speech.finish(text)
                if text:self.dialogue.put(Message(role='assistant',content=text,caption_text=text))
                harness.observe('speech',first_text_at=speech.first_text_at,characters=len(text))
'''+s[b:];p.write_text(s,encoding='utf-8')
print('candidate integration written')
