import os
from pathlib import Path
os.environ['CANDIDATE_RUNTIME']='1'
s=Path(__file__).with_name('runtime_production_acceptance.py').read_text().split('async def runtime_mcp():')[0]
exec(compile(s,'<bootstrap>','exec'))
import core.connection as connection
import core.utils.conversation_guidance as guide
from test_primary_answer_direct_tts import PrimaryAnswerDirectTtsTests
from core.utils.conversation_turn import attach_conversation_evidence
from core.providers.tts.dto.dto import ContentType
print({'connection':connection.__file__,'guide':guide.__file__,'guide_chars':len(guide.NATURAL_CONVERSATION_GUIDANCE),'hardware_billing_enabled':bool(provider.hardware_context)})
provider.client.close()
t=PrimaryAnswerDirectTtsTests();t.setUpClass();t.setUp();h=t.handler()
h.config['operation_control']={'enabled':True};h.actor.key=('synthetic','diagnostic',1)
h.dialogue.update_system_message(prompt)
h.llm=LLMProvider(dict(llm,model_name='qwen3.8-max',temperature=0.3,max_tokens=150))
original=h.llm.client.chat.completions.create
def capture(**params):
    print({'request_model':params['model'],'last_user':params['messages'][-1],
           'guide_in_request':guide.NATURAL_CONVERSATION_GUIDANCE.strip() in params['messages'][0]['content']})
    response=original(**params)
    if not params.get('stream'):print({'upstream_model':response.model});return response
    def chunks():
        first=True
        for chunk in response:
            if first: print({'upstream_model':chunk.model});first=False
            yield chunk
    return chunks()
h.llm.client.chat.completions.create=capture
try:
    print({'ok':h.chat('刚买了书架，还没发货，不要建议。',_identity=h.actor)})
    print({'spoken':''.join(str(e.content_detail) for e in h.tts_events if e.content_type==ContentType.TEXT)})
finally:
    h.llm.client.close();t.doCleanups();t.tearDownClass()
