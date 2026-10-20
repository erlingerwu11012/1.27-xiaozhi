"""20 actual ASR/chat/TTS turns; synthetic speech, read-only time tools only."""
from pathlib import Path
source=Path(__file__).with_name('dialogue_fix_voice_chain.py').read_text()
source=source.replace("h.config['operation_control']={'enabled':True}",
    "h.config['operation_control']={'enabled':True};h.config['conversation_validation']={'semantic_enabled':True}")
source=source.replace('model_name=MODEL,timeout=40', 'model_name=MODEL,temperature=0.3,timeout=40')
source=source.replace('check_budget();row=', 'row=')
source=source.replace("result['providers']={'asr_model':asr_cfg.get('model_name'),'tts_model':tts_cfg.get('model')}",
    "asr_cfg['api_key']=llm['api_key'];tts_cfg['api_key']=llm['api_key'];result['providers']={'asr_model':asr_cfg.get('model_name'),'tts_model':tts_cfg.get('model')};result['credential_scope']='existing authorized test credential; production configuration unchanged'")
source=source.replace('dialogue-fix-voice-chain.json','complete-chat-voice20.json')
source=source.replace("f'dialogue-fix-voice-{index}.wav'", "f'complete-chat-voice20-{index}.wav'")
source=source.replace('tool_events=list(tool_events),tts_events=len(h.tts_events)',
    "tool_events=list(tool_events),tts_events=len(h.tts_events),response_check=getattr(h,'_conversation_gate',None)")
source=source.replace("'tts_calls':10,'asr_sessions':5,'chat_turns':5", "'tts_calls':40,'asr_sessions':20,'chat_turns':20")
old="samples=['刚买了个书架，还没发货，我就是随便聊聊，别替我安排。',\n           '成年人的朋友为什么越来越难约？别反问我，说说你的看法。',\n           '查询伦敦现在的时间','查询东京现在的时间','查询上海现在的时间']"
samples=[
 '刚买了个书架，还没发货，我就是随便聊聊，别替我安排。',
 '成年人的朋友为什么越来越难约？别反问我，说说你的看法。',
 '查询伦敦现在的时间','查询东京现在的时间','查询上海现在的时间',
 '最近又开始学吉他，前半段能弹下来，后半段还没练。先别指导我。',
 '我打算换琴弦，不过还没有买，也没有换。',
 '今天别逗我，也别每句话都反问，正常聊就好。',
 '有首老歌以前没兴趣，现在反而喜欢了，你说说为什么。',
 '更新一下，琴弦已经买了，店家还没有发货，也没换上。',
 '只按我说过的内容，琴弦现在什么状态？',
 '报告已经写好一半，昨天只是改了标题，没继续写剩下的正文。',
 '昨天没写正文，不等于正文从来没写过，你说对吧。',
 '朋友本来约周五吃饭，不过还没有确认有没有空。',
 '我没订餐厅，现在只是说到这个想法。',
 '刚收到消息，他周五没空，这次没约成，也没改约别的日期。',
 '不要给安排，说说你对成年人的友谊有什么看法。',
 '我新买的落地灯，商家只出了单号，快递还没有收件。',
 '不要替我补现实情况，刚才这个落地灯已经在路上了吗？',
 '换个话题，为什么有些菜名字很好听，吃起来却很一般。']
assert old in source
source=source.replace(old,'samples='+repr(samples))
source=source.replace('if index>=3:', 'if index in (3,4,5):')
source=source.replace("len(result['cases'])==5", "len(result['cases'])==20")
exec(compile(source,'<complete-chat-voice20-chain>','exec'))
