import ast,pathlib,types
p=pathlib.Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server/core/utils/tool_harness/runtime.py')
tree=ast.parse(p.read_text());cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and any(isinstance(m,ast.FunctionDef) and m.name=='epoch' for m in n.body))
methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in {'valid','epoch'}]
minimal=ast.Module(body=[ast.ClassDef(name='Check',bases=[],keywords=[],body=methods,decorator_list=[])],type_ignores=[]);ast.fix_missing_locations(minimal);ns={};exec(compile(minimal,'<live-methods>','exec'),ns)
x=ns['Check']();x.conn=types.SimpleNamespace(session_id='same',listen_epoch=12,utterance_id=11,tts_abort_epoch=0,person_turn=types.SimpleNamespace(turn_id='same'),superseded=False,client_abort=False)
x.scope=lambda:'same';old=x.epoch();before=x.valid('same',old);x.conn.utterance_id=12;after=x.valid('same',old)
print({'offline_check':'unchanged_session_actor_and_abort_epoch; only empty-ASR utterance advances','valid_before':before,'valid_after':after,'model_requests':0,'production_mutations':0})
