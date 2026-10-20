"""Run existing audio chain against this exact candidate without touching hardware."""
from pathlib import Path
source=Path(__file__).with_name('dialogue_fix_voice_chain.py').read_text()
source=source.replace("h.config['operation_control']={'enabled':True}",
    "h.config['operation_control']={'enabled':True};h.config['conversation_validation']={'semantic_enabled':True}")
source=source.replace('model_name=MODEL,timeout=40', 'model_name=MODEL,temperature=0.3,timeout=40')
source=source.replace('check_budget();row=', 'row=') # Exactly 5 chat turns, 10 TTS requests.
source=source.replace('dialogue-fix-voice-chain.json','complete-chat-voice.json')
source=source.replace("f'dialogue-fix-voice-{index}.wav'", "f'complete-chat-voice-{index}.wav'")
source=source.replace('tool_events=list(tool_events),tts_events=len(h.tts_events)',
    "tool_events=list(tool_events),tts_events=len(h.tts_events),response_check=getattr(h,'_conversation_gate',None)")
exec(compile(source,'<complete-chat-voice-chain>','exec'))
