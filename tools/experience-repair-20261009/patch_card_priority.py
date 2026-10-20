from pathlib import Path
p=Path('tools/experience-repair-20261009/candidate/core/utils/tool_harness/runtime.py');s=p.read_text(encoding='utf-8')
s=s.replace('用户陈述近况、进度、感受或询问已说过的内容时用chat，不主动改成设置提醒、保存便签等任务。','用户陈述近况、进度、感受或询问已说过的内容时用chat，不主动改成设置提醒、保存便签等任务。但处于当前提醒交互中，且本轮确认已办完该提醒对应事项时，应执行本次卡片主动作；这不是新建提醒或记录近况。')
s=s.replace("            grounded=await self.dispatch('reminder_get_current',{},scope,turn,epoch,tools,deadline)\n            executed+=1", "            try:\n                grounded=await self.dispatch('reminder_get_current',{},scope,turn,epoch,tools,deadline)\n            except (ValueError,RuntimeError):\n                grounded=StepResult(state='unknown',tool='reminder_get_current',call_id='',arguments={},reply='',error='card_context_unavailable')\n            executed+=1")
s=s.replace("            prerequisites=list(PREREQUISITES.get(name,[]))", "            prerequisites=list(PREREQUISITES.get(name,[]))",1)
# Active-card operations must have their full schemas from the first decision.
s=s.replace("        names=required+list(names)","        from core.utils.reminder_interaction import is_interaction_active\n        contextual=['reminder_get_current','reminder_action'] if is_interaction_active(self.conn) else []\n        names=required+contextual+list(names)",1)
p.write_text(s,encoding='utf-8')
