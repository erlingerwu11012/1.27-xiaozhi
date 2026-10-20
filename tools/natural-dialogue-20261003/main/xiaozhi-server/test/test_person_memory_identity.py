import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from core.utils.person_identity import freeze,reset_speaker,activate,deactivate,current_turn
from core.utils.person_material_outbox import MaterialOutbox


class PersonIdentityTest(unittest.TestCase):
    def connection(self,account="10"):
        return SimpleNamespace(config={"sys_user_id":account,"agent_id":"agent"},device_id="device",listen_epoch=7,
            mcp_client=SimpleNamespace(capabilities={"experimental":{"personalIdentity":2,"identityCleanup":2}}),identity_synced_version=2)

    def state(self):
        return {"mode":"personal","directory_version":2,"voice_profiles":[{"speaker_id":"v_a","voiceprint_id":"logic_a","user_id":"usr_a","display_name":"爸爸","template_version":3}]}

    def test_unknown_does_not_reuse_previous_actor(self):
        conn=self.connection();match={"speaker_id":"v_a","user_id":"usr_a"}
        first=freeze(conn,self.state(),match)
        self.assertTrue(first.eligible)
        reset_speaker(conn)
        second=freeze(conn,self.state(),None)
        self.assertFalse(second.eligible)
        self.assertIsNone(conn.current_speaker_user)
        self.assertNotEqual(first.key,second.key)

    def test_foreign_or_unbound_candidate_rejected(self):
        for match in ({"speaker_id":"foreign","user_id":"usr_a"},{"speaker_id":"v_a","user_id":"usr_other"},{"speaker_id":"v_a"}):
            self.assertFalse(freeze(self.connection(),self.state(),match).eligible)

    def test_default_requires_authoritative_zero_voice_mode(self):
        default={"mode":"default","directory_version":5,"default_user_id":"usr_default","default_generation":3}
        conn=self.connection();conn.identity_synced_version=5
        actor=freeze(conn,default)
        self.assertEqual((actor.status,actor.generation),("default",3))
        self.assertFalse(freeze(self.connection(),{"mode":"unavailable"}).eligible)
        self.assertFalse(freeze(self.connection(""),default).eligible)

    def test_callback_context_keeps_original_actor(self):
        conn=self.connection();first=freeze(conn,self.state(),{"speaker_id":"v_a","user_id":"usr_a"})
        token=activate(conn,first)
        try:
            freeze(conn,self.state())
            self.assertEqual(current_turn(conn),first)
        finally:deactivate(token)
        self.assertIsNone(current_turn(conn))

    def test_outbox_idempotency_and_person_scoped_retirement(self):
        with tempfile.TemporaryDirectory() as folder:
            queue=MaterialOutbox(str(Path(folder)/"queue.sqlite"))
            a=freeze(self.connection(),self.state(),{"speaker_id":"v_a","user_id":"usr_a"})
            state={"mode":"default","directory_version":1,"default_user_id":"usr_b","default_generation":2}
            conn=self.connection("11");conn.identity_synced_version=1
            b=freeze(conn,state)
            self.assertTrue(queue.enqueue(a,"dialogue","中文不截断","event-a"))
            self.assertTrue(queue.enqueue(a,"dialogue","中文不截断","event-a"))
            queue.enqueue(b,"dialogue","another account","event-b")
            with queue.connect() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM material").fetchone()[0],2)
            queue.retire(a.account_id,a.person_id,a.generation)
            with queue.connect() as db:self.assertEqual(db.execute("SELECT event FROM material").fetchall(),[("event-b",)])


if __name__=="__main__":unittest.main()
