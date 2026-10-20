from pathlib import Path
S=Path(__file__).parent
p=S/'work/test/test_primary_answer_direct_tts.py';s=p.read_text()
old='h.actor = SimpleNamespace(eligible=False, listen_epoch=1, turn_id="synthetic-turn", status="unknown")'
new='from core.utils.person_identity import PersonTurn\n        h.actor = PersonTurn("synthetic-account","",0,1,"personal","unknown","synthetic-turn",h.device_id,h.agent_id,1)'
if old in s:s=s.replace(old,new);p.write_text(s)
p=S/'work/test/test_interaction_lifecycle_regression.py';s=p.read_text()
s=s.replace('"instance_id": "note:1:1",\n                        "reason": reason,','"instance_id": "note:1:1",\n                        "revision": 2,\n                        "reason": reason,');p.write_text(s)
print('Legacy fixtures now provide real actor contract and matched close revision; original assertions unchanged.')
