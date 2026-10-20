import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from core.utils.person_identity import PersonTurn
from core.utils.person_material_outbox import MaterialOutbox
from core.utils import person_short_memory as short
from core.providers.memory.bailian.bailian import MemoryProvider
from core.utils.dialogue import Dialogue,Message

def actor(agent="agent",status="matched"):
 return PersonTurn("10","dad",0,1,"personal",status,"turn","device",agent,1)
class ContinuityTest(unittest.TestCase):
 def test_unknown_selection_clears_person_background(self):
  from core.utils.person_identity import select_dialogue
  unknown=actor(status="unknown");conn=SimpleNamespace(config={},prompt="",memory=SimpleNamespace(short_memory="dad private summary"),session_id="unknown")
  select_dialogue(conn,unknown);self.assertEqual("",conn.memory.short_memory);self.assertTrue(conn.memory.person_context)
 def test_prompt_pipeline_id_does_not_drop_full_assistant_reply(self):
  with tempfile.TemporaryDirectory() as d,patch("core.utils.person_material_outbox.material_outbox",MaterialOutbox(str(Path(d)/"out.sqlite"))) as box:
   provider=MemoryProvider({});user=Message("user","original",utterance_id="asr-other-id");user.material_turn_id=actor().turn_id
   def schedule(coro,loop):coro.close()
   with patch("asyncio.run_coroutine_threadsafe",side_effect=schedule):provider.record_response(SimpleNamespace(loop=None),actor(),[user,Message("assistant","full original answer")])
   with box.connect() as db:rows=db.execute("SELECT kind,content FROM material ORDER BY rowid").fetchall()
   self.assertEqual([("dialogue_assistant","full original answer"),("dialogue_end","completed")],rows)
 def test_late_other_connection_cannot_replace_new_summary(self):
  from dataclasses import replace
  with tempfile.TemporaryDirectory() as d,patch.object(short,"material_outbox",MaterialOutbox(str(Path(d)/"out.sqlite"))):
   current=replace(actor(),captured_at=2000);old=replace(actor(),captured_at=1000)
   dialogue=Dialogue();dialogue.source_revision=0;dialogue.compact_summary="new"
   short.persist_compact(current,dialogue);dialogue.compact_summary="old";short.persist_compact(old,dialogue)
   self.assertEqual("new",short.load(current))
 def test_failed_turn_only_closes_own_material(self):
  with tempfile.TemporaryDirectory() as d,patch("core.utils.person_material_outbox.material_outbox",MaterialOutbox(str(Path(d)/"out.sqlite"))) as box:
   provider=MemoryProvider({});messages=[Message("user","previous",utterance_id="old"),Message("assistant","previous answer")]
   def schedule(coro,loop):coro.close()
   with patch("asyncio.run_coroutine_threadsafe",side_effect=schedule):provider.record_response(SimpleNamespace(loop=None),actor(),messages)
   with box.connect() as db:rows=db.execute("SELECT kind,content FROM material").fetchall()
   self.assertEqual([("dialogue_end","completed")],rows)
 def test_agent_summary_isolation_and_person_wide_invalidation(self):
  with tempfile.TemporaryDirectory() as d,patch.object(short,"material_outbox",MaterialOutbox(str(Path(d)/"out.sqlite"))):
   a=actor();b=actor("other");dialogue=Dialogue();dialogue.compact_summary="verified compact";dialogue.source_revision=0
   short.persist_compact(a,dialogue);self.assertEqual("verified compact",short.load(a));self.assertEqual("",short.load(b))
   short.invalidate(b);self.assertEqual("",short.load(a));short.persist_compact(a,dialogue);self.assertEqual("",short.load(a))
 def test_retirement_stops_late_summary_for_every_agent(self):
  with tempfile.TemporaryDirectory() as d,patch.object(short,"material_outbox",MaterialOutbox(str(Path(d)/"out.sqlite"))):
   a=actor();dialogue=Dialogue();dialogue.compact_summary="old";dialogue.source_revision=0;short.retire("10","dad",0);short.persist_compact(a,dialogue);self.assertEqual("",short.load(a))
 def test_full_reply_chunks_and_default_is_never_uploaded(self):
  with tempfile.TemporaryDirectory() as d:
   box=MaterialOutbox(str(Path(d)/"out.sqlite"));provider=MemoryProvider({})
   with patch("core.utils.person_material_outbox.material_outbox",box):
    provider._enqueue_text(actor(),"dialogue_assistant","长"*70000,"reply")
    with box.connect() as db:rows=db.execute("SELECT content FROM material ORDER BY rowid").fetchall()
    self.assertEqual("长"*70000,"".join(r[0] for r in rows))
    provider.record_turn(SimpleNamespace(),actor(status="default"),"不会上云")
    with box.connect() as db:self.assertEqual(2,db.execute("SELECT count(*) FROM material").fetchone()[0])
if __name__=="__main__":unittest.main()
