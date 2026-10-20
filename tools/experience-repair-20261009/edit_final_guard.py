from pathlib import Path
S=Path(__file__).parent/'candidate'
p=S/'core/connection.py';s=p.read_text(encoding='utf-8');s=s.replace('''                turn_sid,turn_epoch=begin_tts_turn(self,turn_sid)
                self.dialogue.put(Message(role='assistant',content=text,caption_text=text))''','''                if turn_epoch!=getattr(self,'tts_abort_epoch',0):
                    turn_sid=uuid.uuid4().hex;self.sentence_id=turn_sid
                    self._report_actors[(self.session_id,turn_sid,getattr(self,'tts_abort_epoch',0))]=current_turn(self)
                turn_sid,turn_epoch=begin_tts_turn(self,turn_sid,epoch=getattr(self,'tts_abort_epoch',0))
                self.dialogue.put(Message(role='assistant',content=text,caption_text=text))''');p.write_text(s,encoding='utf-8')
p=S/'core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8');needle="        stop=getattr(self.conn,'stop_event',None)";s=s.replace(needle,"""        from core.utils.person_identity import current_turn
        captured=current_turn(self.conn);live=getattr(self.conn,'person_turn',None)
        if captured and live and captured.eligible and live.eligible and captured.key!=live.key:return False
"""+needle,1);p.write_text(s,encoding='utf-8')
p=S/'core/providers/tools/device_mcp/mcp_executor.py';s=p.read_text(encoding='utf-8');start=s.index('            if (\n                resultJson is not None');end=s.index('            return ActionResponse(action=Action.REQLLM, result=str(result))',start);s=s[:start]+'''            # Device business fields named "action" (primary/secondary) are data,
            # never a request to select a server Action enum or bypass receipts.
'''+s[end:];p.write_text(s,encoding='utf-8')
p=Path(__file__).parent/'package_candidate.py';s=p.read_text(encoding='utf-8-sig').replace("'core/connection.py'","'core/handle/helloHandle.py','core/utils/vision_capability.py','core/providers/tools/device_mcp/mcp_executor.py','core/connection.py'",1);p.write_text(s,encoding='utf-8')
