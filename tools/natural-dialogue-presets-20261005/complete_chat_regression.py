from pathlib import Path
source=Path(__file__).with_name('run_dialogue_fix_regression.py').read_text()
source=source.replace("'test_verified_tool_facts.VerifiedToolFactsTests'", "'test_verified_tool_facts.VerifiedToolFactsTests','test_conversation_turn'")
source=source.replace('dialogue-fix-regression','complete-chat-regression')
source=source.replace("'test_conversation_turn'", "'test_conversation_turn','test_semantic_conversation_guard'")
source=source.replace("'test_semantic_conversation_guard'", "'test_semantic_conversation_guard','test_conversation_config'")
exec(compile(source,'<complete-chat-regression>','exec'))
