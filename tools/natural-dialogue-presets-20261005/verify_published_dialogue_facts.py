"""Production default's synthetic voice chain; keep candidate evidence intact."""
from pathlib import Path
source=Path(__file__).with_name('dialogue_fix_voice_chain.py').read_text()
source=source.replace("os.environ['CANDIDATE_RUNTIME']='1'", "os.environ['CANDIDATE_RUNTIME']='0'")
source=source.replace("MODEL=os.environ.get('ACCEPTANCE_MODEL','qwen3.8-max')", "MODEL='qwen3.8-flash'")
source=source.replace('dialogue-fix-voice-chain.json','dialogue-facts-production-voice.json')
source=source.replace('dialogue-fix-voice-','dialogue-facts-production-voice-')
source=source.replace("check_budget();row={'turn':index", "assert index<=5,'five_turn_cap';row={'turn':index")
source=source.replace("'source':'real ASR and TTS with synthetic recordings; actual candidate ConnectionHandler and live read-only MCP'", "'source':'real ASR and TTS with synthetic recordings; published production ConnectionHandler, default model and live read-only MCP'")
exec(compile(source,'<production-voice-verification>','exec'))
