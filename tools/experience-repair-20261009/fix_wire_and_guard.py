from pathlib import Path
R=Path(__file__).parent
p=R/'wire_conversation.py';s=p.read_text(encoding='utf-8-sig');s=s.replace('c.mcp_client=old.mcp_client;c.server=old.server;', "c.features=old.features;c.headers={};c.account_id='simulation-account';c.mcp_client=old.mcp_client;c.server=old.server;")
s=s.replace('  c.func_handler.current_support_functions=', '''  from core.utils.reminder_interaction import open_interaction
  import time
  open_interaction(c,instance_id='sim-card',revision=2,expires_at=int(time.time())+180)
  c.func_handler.current_support_functions=''')
s=s.replace("  self.directory_patch.stop();await", "  from core.utils.reminder_interaction import close_interaction\n  close_interaction(self.c)\n  self.directory_patch.stop();await");p.write_text(s,encoding='utf-8')
p=R/'candidate/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8-sig')
s=s.replace("        return bool(re.search(r'(?:我(?:已经|已)", "        text='。'.join(part for part in re.split(r'[，,；;。]|但是|不过|但',str(text)) if not re.search(r'没有|没能|尚未|未能|不能|不代表|并未|还没|没有确认',part))\n        return bool(re.search(r'(?:我(?:已经|已)")
s=s.replace('当前卡片支持跨步骤$ref；不要编造实例ID。','当前卡片支持跨步骤$ref；不要编造实例ID。存在active_card时，用户问“提醒了什么”“刚才那个提醒是什么”应读取reminder_get_current，不能用早前闹钟或失败记录代替当前卡片。')
p.write_text(s,encoding='utf-8')
