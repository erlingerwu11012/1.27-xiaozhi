from pathlib import Path
import json
S=Path(__file__).parent
p=S/'bootstrap.py';s=p.read_text();s=s.replace("work=stage/'work'","work=Path(os.environ.get('CANDIDATE_WORK',str(stage/'work')))")
s=s.replace("os.environ['EXPERIENCE_TEST_BUDGET']=str(stage/'budget.sqlite3')","os.environ['EXPERIENCE_TEST_BUDGET']=str(stage/'budget.sqlite3')\nos.environ['HARNESS_LEDGER_PATH']=str(stage/'work/data/test-operations.sqlite3')\nos.environ['PERSON_MATERIAL_OUTBOX']=str(stage/'work/data/test-material-outbox.sqlite3')")
p.write_text(s)
p=S/'stateful_device.py';s=p.read_text();s=s.replace("for name in ('memory_search','memory_correct','memory_forget'):","for name in ('memory_search','memory_correct','memory_forget'):")
needle="        d={'type':'function','function':{'name':'reminder_close_current'"
assert needle in s
s=s.replace(needle,"        self.tools['memory_add']=ToolDefinition(name='memory_add',description=copy.deepcopy(all_function_registry['memory_add'].description),tool_type=ToolType.SERVER_PLUGIN)\n"+needle)
p.write_text(s)
p=S/'wire_conversation.py';s=p.read_text();needle="    if name in {'memory_correct','memory_forget'}:"
assert needle in s
s=s.replace(needle,"    if name=='memory_add':\n     from core.utils.recent_memory import add\n     return ActionResponse(Action.REQLLM,result=await add(conn,args['fact']))\n"+needle)
# Retain returned user facts and exclude secrets while recording whole loopback traffic.
p.write_text(s)
print('fixtures ready')
