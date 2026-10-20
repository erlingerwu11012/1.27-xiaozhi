from pathlib import Path
p=Path('tools/experience-repair-20261009/candidate/core/utils/tool_harness/runtime.py')
s=p.read_text(encoding='utf-8-sig')
s=s.replace("        context['conversation_feedback']=", "        snapshot=getattr(self,'_card_snapshot',None)\n        if snapshot is not None:context['active_card']=snapshot\n        context['conversation_feedback']=",1)
s=s.replace("        fast=None if prohibited else self.fast_decision(query,tools)","""        # Read-only grounding for a live interaction. Its receipt is planning
        # context, never evidence that the user's requested action completed.
        self._card_snapshot=None
        from core.utils.reminder_interaction import get_interaction_state,is_interaction_active
        card=get_interaction_state(self.conn)
        if is_interaction_active(self.conn) and 'reminder_get_current' in tools:
            grounded=await self.dispatch('reminder_get_current',{},scope,turn,epoch,tools,deadline)
            executed+=1
            body=grounded.payload if isinstance(grounded.payload,dict) else {}
            if grounded.state=='completed' and body.get('instance_id')==card.instance_id and body.get('revision')==card.revision:
                self._card_snapshot=copy.deepcopy(body)
                self._card_snapshot['instruction']='这是刚读取的当前提醒。理解本轮话语与该事项的关系：询问内容应查询；用户确认已完成对应事项时读取最新版本后执行主动作；仅闲聊或说的是其他事情时不执行。以后继续提醒与本次完成是不同操作，不能擅自永久删除。'
            else:
                self._card_snapshot={'active':False,'read_status':grounded.state,'instruction':'未确认可访问的当前卡片，不能凭历史猜测或操作。'}
        fast=None if prohibited else self.fast_decision(query,tools)""",1)
p.write_text(s,encoding='utf-8')
