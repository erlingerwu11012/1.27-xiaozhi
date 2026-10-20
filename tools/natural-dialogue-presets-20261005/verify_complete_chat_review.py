"""Verify the saved candidate, not just the older experimentation worktree."""
from pathlib import Path
import json,os,subprocess,sys
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
REVIEW=Path('/root/prjs/tmp/complete-chat-review-20261006')
old='/root/prjs/tmp/natural-dialogue-presets-20261005/worktree/main/xiaozhi-server'
root=str(REVIEW/'main/xiaozhi-server')
runner=(OUT/'run_dialogue_fix_regression.py').read_text()
runner=runner.replace(old,root).replace('dialogue-fix-regression','complete-chat-review-regression')
runner=runner.replace("'test_verified_tool_facts.VerifiedToolFactsTests'",
    "'test_verified_tool_facts.VerifiedToolFactsTests','test_conversation_turn','test_semantic_conversation_guard','test_conversation_config'")
result=subprocess.run([sys.executable,'-c',runner],capture_output=True,text=True,timeout=90)
print(result.stdout[-1200:]);assert result.returncode==0,'saved_candidate_regression_failed'
# MCP test bootstrap imports the same remote read-only configuration, with
# the saved source root substituted before the ConnectionHandler is imported.
bootstrap=(OUT/'runtime_production_acceptance.py').read_text().split('async def runtime_mcp():')[0]
bootstrap=bootstrap.replace(old,root)
source=(OUT/'complete_chat_mcp_acceptance.py').read_text()
start=source.index("s=Path(__file__)")
end=source.index(';provider.client.close()',start)
source=source[:start]+'s='+repr(bootstrap)+'\nexec(compile(s,"<saved-source-bootstrap>","exec"))'+source[end:]
os.environ['CHAT_REPORT']='complete-chat-review-mcp'
exec(compile(source,'<saved-candidate-live-mcp>', 'exec'))
