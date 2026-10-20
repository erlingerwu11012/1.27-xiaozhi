import json
from pathlib import Path
root=Path(__file__).resolve().parents[2]/'tmp/bailian-memory-product/server';mf=Path(__file__).with_name('changed.json');changed=json.loads(mf.read_text())
n='main/xiaozhi-server/test/test_person_memory_chat_init.py';t=(root/n).read_text(encoding='utf-8');s=t.index('    def test_chat_compaction_call_matches_actual_dialogue_signature');e=t.index('    def actor(self):',s)
t=t[:s]+'''    def test_complete_request_budget_call_matches_actual_dialogue_signature(self):
        from core.utils.dialogue import Dialogue
        root = Path(__file__).parents[1]
        connection=ast.parse((root/"core/connection.py").read_text(encoding="utf-8"))
        calls=[n for n in ast.walk(connection) if isinstance(n,ast.Call)
               and isinstance(n.func,ast.Attribute) and n.func.attr=="prepare_request"]
        self.assertEqual(len(calls),1)
        dialogue=Dialogue()
        conn=SimpleNamespace(dialogue=dialogue,llm=SimpleNamespace(input_limit_tokens=997952,context_limit_tokens=1000000),session_id="synthetic")
        messages=[{"role":"system","content":"rules"},{"role":"user","content":"hello"}]
        expression=ast.fix_missing_locations(ast.Expression(body=calls[0]))
        result=eval(compile(expression,"connection.py","eval"),{"self":conn,"messages":messages,"functions":None})
        self.assertEqual(result,messages);self.assertEqual(dialogue.context_window.limit,200000)

'''+t[e:];(root/n).write_text(t,encoding='utf-8');changed.append(n)
n='main/xiaozhi-server/core/utils/person_short_memory.py';t=(root/n).read_text(encoding='utf-8');anchor='        db.execute("INSERT OR IGNORE INTO retired_short_scope VALUES(?)",(key,))';t=t.replace(anchor,anchor+'''
        for (agent_scope,) in db.execute("SELECT scope FROM short_summary WHERE json_extract(scope,'$[0]')=? AND json_extract(scope,'$[1]')=? AND json_extract(scope,'$[2]')=?",(str(account),person,generation)).fetchall():
            db.execute("INSERT OR IGNORE INTO retired_short_scope VALUES(?)",(agent_scope,))''');(root/n).write_text(t,encoding='utf-8');changed.append(n)
mf.write_text(json.dumps(sorted(set(changed)),indent=2))
