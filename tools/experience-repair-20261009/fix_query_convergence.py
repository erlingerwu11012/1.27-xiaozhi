from pathlib import Path
p=Path(__file__).parent/'candidate/core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8');old="        fast=None if prohibited or quoted_note or card_operation or query_card else self.fast_decision(query,tools)";new="""        if query_card and 'reminder_get_current' in tools:
            # The grounding receipt already belongs to this accepted request.
            # A query needs no subsequent planning or redundant status reads.
            current=grounded if grounded is not None and grounded.state=='completed' else await self.dispatch('reminder_get_current',{},scope,turn,epoch,tools,deadline)
            current.intermediate=False;outcome.results.append(current);outcome.reply=current.reply;outcome.interrupted=not self.valid(scope,epoch);return outcome
        fast=None if prohibited or quoted_note or card_operation or query_card else self.fast_decision(query,tools)""";assert old in s;s=s.replace(old,new)
s=s.replace('不要因自己看不到现实，就否定对话中已说明的状态。','不要因自己看不到现实，就否定对话中已说明的状态。未明确更新的状态仍按最后用户原话保持；助手的建议、猜测和催促不构成用户已行动的证据。回答现在状态的问题，先核对相关的最后用户陈述，只报告其支持的状态；缺少后续证据就说没有新的确认，禁止按时间过去了推断事项已完成。')
p.write_text(s,encoding='utf-8')
