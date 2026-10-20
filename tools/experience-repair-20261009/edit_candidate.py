"""Apply audited edits to isolated Python candidate only."""
from pathlib import Path
S=Path(__file__).parent/'candidate'
def edit(name,old,new,count=1):
    p=S/name;s=p.read_text(encoding='utf-8-sig')
    if s.count(old)!=count:raise RuntimeError((name,'replacement_count',s.count(old),old[:70]))
    p.write_text(s.replace(old,new),encoding='utf-8')
edit('core/utils/tool_harness/runtime.py',"""        return json.dumps([getattr(self.conn,'device_id',''),actor_scope(self.conn),live_key],ensure_ascii=False,default=str)""","""        from core.utils.person_identity import current_turn
        actor=current_turn(self.conn) or actor
        key=getattr(actor,'key',None)
        return json.dumps([getattr(self.conn,'device_id',''),getattr(self.conn,'session_id',''),key],ensure_ascii=False,default=str)""")
edit('core/utils/tool_harness/runtime.py',"scope!=self.scope() or self.epoch()!=epoch or getattr(self.conn,'superseded',False) or getattr(self.conn,'client_abort',False)","scope!=self.scope() or self.epoch()!=epoch or getattr(self.conn,'superseded',False)")
edit('core/utils/tool_harness/runtime.py',"""        return (getattr(self.conn,'session_id',None),getattr(self.conn,'listen_epoch',None),getattr(self.conn,'utterance_id',None),getattr(self.conn,'tts_abort_epoch',None),getattr(actor,'turn_id',None))""","""        return (getattr(self.conn,'session_id',None),getattr(self.conn,'_harness_request_generation',0),getattr(self.conn,'_harness_explicit_abort_generation',0))""")
edit('core/utils/tool_harness/runtime.py',"""    async def run(self,query,messages):
        scope,epoch=self.scope(),self.epoch()
        async with self.lock:
            if not self.valid(scope,epoch):
                outcome=OperationOutcome(mode='operate',reply='',interrupted=True,error='stale_queued_request')
            else:
                outcome=await self._run(query,messages)
            self.last_outcome=outcome
            return outcome
    async def _run(self,query,messages):
        started=time.monotonic();deadline=started+90;scope=self.scope();epoch=self.epoch()""","""    async def run(self,query,messages,request_epoch=None):
        scope,epoch=self.scope(),request_epoch or self.epoch()
        deadline=time.monotonic()+90
        acquired=False
        try:
            while not acquired:
                if not self.valid(scope,epoch):
                    self.observe('discard',reason='superseded_queued_request')
                    return OperationOutcome(mode='chat',reply='',interrupted=True,error='superseded_queued_request')
                remaining=deadline-time.monotonic()
                if remaining<=0:return OperationOutcome(mode='chat',reply='处理请求超时了，请稍后再试。',error='queue_timeout')
                try:
                    await asyncio.wait_for(self.lock.acquire(),min(.1,remaining));acquired=True
                except asyncio.TimeoutError:pass
            outcome=await self._run(query,messages,deadline,scope,epoch)
            self.last_outcome=outcome
            return outcome
        finally:
            if acquired:self.lock.release()
    async def _run(self,query,messages,deadline=None,scope=None,epoch=None):
        started=time.monotonic();deadline=deadline or started+90;scope=scope or self.scope();epoch=epoch or self.epoch()""")
edit('core/utils/tool_harness/runtime.py',"""        if actor:context['identity']={'status':actor.status,'mode':actor.mode,'eligible':actor.eligible}""","""        if actor:context['identity']={'status':actor.status,'mode':actor.mode,'eligible':actor.eligible}
        from core.utils.reminder_interaction import get_interaction_state,is_interaction_active
        card=get_interaction_state(self.conn)
        if is_interaction_active(self.conn):
            context['active_card']={'instance_id':card.instance_id,'revision':card.revision,'instruction':'本轮说已经拿完、喝完或办好了，结合此卡片先读取内容与动作，确实对应才完成；不要猜动作或删除未来规则。'}
        context['conversation_feedback']='最新用户反馈优先：别逗、别反问、别教育或说过了，都要立即调整表达。按最后已确认状态回答；不嘲讽用户，不虚构行动或事实，不照抄上轮回复。失败后明确再试是新的请求，重新检查并尝试可用能力，不能只复述上次失败。'""")
edit('core/utils/tool_harness/runtime.py',"""memory_search返回对象为{"status":"found","text":"实际旧记录原文","source":"local"}，原文路径只能是text；不存在content、matches或matches[0]。删除或更正明确的一条记忆时，在同一计划中先查、后写，用match={"$ref":{"step":"读取编号","path":"text"}}和depends_on引用真实原文，不需要再请求模型决策；如果已有verified_results，match直接用其中实际text字符串，不要再用$ref。如果查询内容不足以确定哪条才澄清。例：{"mode":"operate","steps":[{"id":"r","tool":"memory_search","arguments":{"query":"旧偏好"}},{"id":"w","tool":"memory_correct","arguments":{"match":{"$ref":{"step":"r","path":"text"}},"replacement":"新偏好"},"depends_on":["r"]}]}。""","""memory_search返回items，每项包含record_id、text、source；text是单条用户事实，不含来源包装。更正或遗忘先读取，finished=false并声明最终写工具；收到verified_results后选择与用户目标唯一匹配的项，用其完整单条text作为match（最多1024字）。禁止引用顶层text整段档案或取前1024字；多条有歧义先问。查询回答仅使用相关事实，不能把档案、检索过程或JSON念给用户。""")
edit('core/utils/tool_harness/runtime.py',"""                self.observe('validation',request_id=turn,error_type=type(exc).__name__,repairs=outcome.repairs)""","""                reason=error.split(':',1)[0].split('\\n',1)[0]
                self.observe('validation',request_id=turn,error_type=type(exc).__name__,reason=reason if re.fullmatch('[a-zA-Z0-9_ .-]{1,100}',reason) else 'schema_validation_failed',repairs=outcome.repairs)
                if reason=='catalog_changed' and not any(contract(r.tool).write for r in outcome.results):
                    tools=self.catalog();catalog_version=version(tools);outcome.catalog_version=catalog_version""")
edit('core/utils/tool_harness/runtime.py',"""        if any(r.state!='completed' for r in outcome.results):outcome.reply+='未确认的操作不会自动重复执行。'""","""        # Result adapters already explain failure or pending stages once.""")
edit('core/utils/tool_harness/runtime.py',"""        outcome.reply=''.join(r.reply for r in meaningful)""","""        outcome.reply=''.join(dict.fromkeys(r.reply for r in meaningful))""")
# Guard against unresolved giant archive references even with legacy clients.
edit('core/utils/tool_harness/runtime.py',"""                        if pre=='memory_search' and (not isinstance(pre_result.payload,dict) or arguments.get('match','') not in pre_result.payload.get('text','')):raise ValueError('memory_match_not_in_verified_record')""","""                        if pre=='memory_search':
                            from .presentation import memory_items
                            verified_items=memory_items(pre_result.payload)
                            match=arguments.get('match','')
                            if match!='*' and (not isinstance(match,str) or not match or len(match)>1024 or not any(match==item['text'] for item in verified_items)):
                                raise ValueError('memory_requires_single_verified_fact')""")
# Snapshot schema containers fully; shallow copies shared live catalog state.
edit('core/utils/tool_harness/runtime.py',"d.parameters=dict(d.parameters or {})","d.parameters=copy.deepcopy(d.parameters or {})\n            d.description=copy.deepcopy(d.description)")
# Effective API errors must never be spoken as names.
edit('core/utils/tool_harness/contracts.py',"LABELS.update(dict(zip(","LABELS.update({'memory_search':'记忆查询','reminder_get_current':'当前提醒查询','reminder_list_pending':'待办查询','self_camera_take_photo':'拍照','self_camera_identify_person':'识人','self_get_device_status':'设备状态查询','alarm_list':'闹钟查询','note_list':'便签查询','habit_list':'习惯查询','get_world_time':'时间查询','get_weather':'天气查询','get_news_from_newsnow':'新闻查询','get_lunar':'农历查询','self_get_system_info':'系统信息查询','self_screen_get_info':'屏幕信息查询','camera_face_enroll_status':'人脸采集查询'})\nLABELS.update(dict(zip(")
edit('core/utils/tool_harness/contracts.py',"if reminder_action_completed(args,body):return out('completed',str(body))","if reminder_action_completed(args,body):\n            from .presentation import card_action_reply\n            return out('completed',card_action_reply(args,body))")
edit('core/utils/tool_harness/contracts.py',"""            elif name=='memory_search':reply=body['text'] or '未找到对应记忆。'""","""            elif name=='memory_search':
                from .presentation import memory_reply
                reply=memory_reply(body)""")
edit('core/utils/tool_harness/contracts.py',"""            elif name=='reminder_get_current':reply='当前没有提醒卡片。' if body.get('active') is False else '当前提醒：'+str(body.get('title') or body.get('status') or '已读取')+'。'""","""            elif name in {'reminder_get_current','reminder_list_pending'}:
                from .presentation import reminder_reply
                reply=reminder_reply(body,current=name=='reminder_get_current')""")
edit('core/utils/tool_harness/contracts.py',"""            return out('completed',reply)""","""            from .presentation import safe_speech
            return out('completed',safe_speech(reply))""")
edit('core/utils/tool_result.py',"MESSAGES = {","MESSAGES = {\n    'vision_not_ready':'视觉服务尚未就绪，这次没有拍照，请稍后再试。',\n    'vision_session_mismatch':'视觉授权与当前连接不一致，这次没有完成拍照。',\n    'vision_upload_failed':'照片上传失败，这次没有获得识别结果。',\n    'vision_http_401':'视觉授权已失效，请重新连接后再试。',\n    'vision_http_403':'当前没有使用视觉服务的权限。',\n    'vision_http_413':'照片超过服务端允许的大小。',\n    'vision_http_500':'视觉服务处理失败，请稍后再试。',\n    'vision_http_502':'视觉服务暂时无法连接，请稍后再试。',\n    'vision_http_504':'视觉服务响应超时，请稍后再试。',\n    'vision_timeout':'视觉服务响应超时，请稍后再试。',")
edit('core/utils/tool_result.py',"if prefix and prefix[1] in MESSAGES:","if prefix and (prefix[1] in MESSAGES or re.fullmatch(r'(?:vision|identity)_http_[1-5][0-9]{2}',prefix[1])):")
edit('core/utils/unified_recipient_resolver.py',"""        else:
            resolution = _all_resolution()

    log_recipient_resolution(""","""        else:
            resolution = RecipientResolution(code=RecipientResultCode.NOT_FOUND,
                selector_type='unconfirmed_self',message='这次没有确认你的身份。要提醒哪位已登记用户，还是设为公共提醒？')

    log_recipient_resolution(""")
# Real speaker snapshot wins over mutable ASR reset fields.
edit('core/utils/unified_recipient_resolver.py',"""        current = getattr(conn, "current_speaker_user", None)""","""        from core.utils.person_identity import current_turn
        actor=current_turn(conn)
        current=({'user_id':actor.person_id,'display_name':actor.display_name} if actor and actor.eligible else None)""")
# Empty ASR never creates a request; acceptance is before the chat serialization lock.
edit('core/connection.py',"""        with self._person_chat_lock:
            actor=_identity""","""        request_generation=None
        if depth==0:
            if not str(query or '').strip():return False
            if not hasattr(self,'_harness_generation_lock'):self._harness_generation_lock=threading.Lock()
            with self._harness_generation_lock:
                self._harness_request_generation=getattr(self,'_harness_request_generation',0)+1
                request_generation=self._harness_request_generation
                prior=getattr(self,'_harness_future',None)
                if prior is not None and not prior.done():prior.cancel()
        with self._person_chat_lock:
            if depth==0 and request_generation!=getattr(self,'_harness_request_generation',0):return False
            actor=_identity""")
edit('core/connection.py',"""                    if actor.listen_epoch != int(getattr(self,"listen_epoch",0)):
                        return""","""                    # Listen/ASR counters may advance after a final transcript.
                    # Accepted request generation and immutable actor own this work.
                    if request_generation!=getattr(self,'_harness_request_generation',0):return False""")
edit('core/connection.py',"""                    if (actor.listen_epoch == int(getattr(self, "listen_epoch", 0))
                            and not getattr(self, "client_abort", False)):""","""                    if (request_generation==getattr(self,'_harness_request_generation',0)
                            and not getattr(self, 'client_abort', False)):""")
edit('core/connection.py',"""                deactivate(token)

    def _chat_impl""","""                if depth==0 and request_generation==getattr(self,'_harness_request_generation',0):self.llm_finish_task=True
                deactivate(token)

    def _chat_impl""")
edit('core/connection.py',"""future=asyncio.run_coroutine_threadsafe(harness.run(query,messages),self.loop)""","""future=asyncio.run_coroutine_threadsafe(harness.run(query,messages,request_epoch=request_epoch),self.loop)
                self._harness_future=future""")
edit('core/connection.py',"""                    if outcome.interrupted or not harness.valid(request_scope,request_epoch):
                        return True""","""                    if outcome.interrupted or not harness.valid(request_scope,request_epoch):
                        harness.observe('discard',reason=outcome.error or 'superseded_response')
                        return True""")
edit('core/connection.py',"""                self.dialogue.put(Message(role='assistant',content=text,caption_text=text))
                if not silent_face_start:""","""                from core.utils.tool_harness.presentation import safe_speech
                text=safe_speech(text)
                if not text:text='处理这次请求时没有得到有效结果，请再试一次。'
                self.client_abort=False
                turn_sid,turn_epoch=begin_tts_turn(self,turn_sid)
                self.dialogue.put(Message(role='assistant',content=text,caption_text=text))
                if not silent_face_start:""")
edit('core/handle/abortHandle.py',"async def handleAbortMessage(conn):","async def handleAbortMessage(conn, reason='explicit'):\n    if reason=='explicit':\n        conn._harness_explicit_abort_generation=getattr(conn,'_harness_explicit_abort_generation',0)+1\n        prior=getattr(conn,'_harness_future',None)\n        if prior is not None and not prior.done():prior.cancel()")
edit('core/handle/receiveAudioHandle.py',"await handleAbortMessage(conn)","await handleAbortMessage(conn,reason='speech_activity')",count=2)
print('isolated edits applied')
