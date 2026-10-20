"""Read-only production handler acceptance through the production one-api gateway."""
import os
from pathlib import Path
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
os.environ.pop('CANDIDATE_RUNTIME',None)
bootstrap=(OUT/'runtime_production_acceptance.py').read_text().split('async def runtime_mcp():')[0]
bootstrap=bootstrap.replace("=='qwen3.8-flash'","=='qwen3.7-plus'")
source=(OUT/'complete_chat_mcp_acceptance.py').read_text()
source=source.replace("os.environ['CANDIDATE_RUNTIME']='1'",'')
source=source.replace("s=Path(__file__).with_name('runtime_production_acceptance.py').read_text().split('async def runtime_mcp():')[0]",'s=BOOTSTRAP')
source=source.replace(" h.config['conversation_validation']={'semantic_enabled':True,'model_names':['qwen3.8-max']}\n",'')
source=source.replace("model_name='qwen3.8-max',temperature=0.3,timeout=45,max_tokens=250","model_name='qwen3.7-plus',temperature=0.4,timeout=45,max_tokens=600")
source=source.replace("report={'hardware_writes':0,", "report={'model':'qwen3.7-plus','production_gateway':True,'semantic_validation':False,'hardware_writes':0,")
source=source.replace("'core/utils/conversation_turn.py'","'core/utils/prompt_manager.py'")
os.environ['CHAT_REPORT']='qwen37-production-mcp-20261007'
exec(compile(source,'<production-mcp-verify>','exec'),{'BOOTSTRAP':bootstrap,'__file__':str(OUT/'complete_chat_mcp_acceptance.py'),'__name__':'__main__'})
