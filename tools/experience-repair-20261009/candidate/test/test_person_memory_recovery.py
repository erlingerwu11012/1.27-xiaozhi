import asyncio
import json
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from core.utils.person_identity import PersonTurn, freeze, refresh_directory
from core.utils.person_material_outbox import MaterialOutbox
from core.utils import person_short_memory
from core.utils.person_maintenance import replay_behavior


def actor(person="usr_a", account="10"):
    return PersonTurn(account,person,0,4,"personal","matched","turn_a","device","agent",1,"voice_a",2)


class PersonRecoveryTests(unittest.IsolatedAsyncioTestCase):
    def test_legacy_default_body_is_physically_deleted_without_other_account(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/".memory.yaml"
            path.write_text('owned: "旧默认正文"\nforeign: "另一账号"\n',encoding="utf-8")
            person_short_memory.retire_legacy_agents(["owned"],path)
            self.assertNotIn("旧默认正文",path.read_text(encoding="utf-8"))
            self.assertIn("另一账号",path.read_text(encoding="utf-8"))
    def test_new_firmware_waits_for_acknowledged_directory(self):
        conn=SimpleNamespace(config={"sys_user_id":"10"},device_id="device",listen_epoch=1,
            mcp_client=SimpleNamespace(capabilities={"experimental":{"personalIdentity":2}}))
        state={"mode":"default","directory_version":4,"default_generation":2,"default_user_id":"usr_default"}
        self.assertFalse(freeze(conn,state).eligible)
        conn.identity_synced_version=4
        self.assertTrue(freeze(conn,state).eligible)

    def test_old_firmware_cannot_enter_personal_memory_mode(self):
        conn=SimpleNamespace(config={"sys_user_id":"10"},device_id="device",listen_epoch=1,
            mcp_client=SimpleNamespace(capabilities={"experimental":{}}))
        state={"mode":"personal","directory_version":4,"voice_profiles":[{"speaker_id":"v","user_id":"usr_a"}]}
        self.assertFalse(freeze(conn,state,{"speaker_id":"v","user_id":"usr_a"}).eligible)

    async def test_late_authority_reply_does_not_overwrite_new_audio(self):
        gate=asyncio.Event()
        async def request(*args,**kwargs):
            await gate.wait()
            return {"account_id":"10","mode":"default","directory_version":1,"voice_profiles":[]}
        conn=SimpleNamespace(config={"sys_user_id":"10"},session_id="session",listen_epoch=1,
            identity_state={"mode":"unavailable"},person_turn=actor())
        with patch("config.manage_api_client.ManageApiClient") as client:
            client.return_value.request=request
            task=asyncio.create_task(refresh_directory(conn))
            await asyncio.sleep(0)
            conn.listen_epoch=2
            conn.identity_state={"mode":"personal","directory_version":8}
            gate.set();await task
        self.assertEqual(conn.identity_state["directory_version"],8)
        self.assertEqual(conn.person_turn,actor())

    def test_short_summary_isolated_by_account_person_and_generation(self):
        with tempfile.TemporaryDirectory() as folder:
            queue=MaterialOutbox(str(Path(folder)/"queue.sqlite"))
            a=actor();b=actor("usr_b");foreign=actor(account="11")
            with patch.object(person_short_memory,"material_outbox",queue):
                with queue.connect() as db:
                    person_short_memory.schema(db)
                    for who,text in ((a,"爸爸"),(b,"孩子"),(foreign,"其他账号")):
                        db.execute("INSERT INTO short_summary VALUES(?,?,?)",(person_short_memory.scope(who),text,int(time.time())))
                self.assertEqual(person_short_memory.load(a),"爸爸")
                self.assertEqual(person_short_memory.load(b),"孩子")
                person_short_memory.retire(a.account_id,a.person_id,a.generation)
                self.assertEqual(person_short_memory.load(a),"")
                self.assertEqual(person_short_memory.load(b),"孩子")
                self.assertEqual(person_short_memory.load(foreign),"其他账号")
                self.assertEqual(person_short_memory.load(replace(b,generation=1)),"")
                with queue.connect() as db:
                    self.assertIsNotNone(db.execute("SELECT 1 FROM retired_short_scope WHERE scope=?",(person_short_memory.scope(a),)).fetchone())

    async def test_device_replay_preserves_original_actor_and_event(self):
        who=actor()
        record={"account":"10","person":"usr_a","generation":"0","turn":"original_turn",
                "event":"original_turn:20","seq":"20","directory_version":"3",
                "voiceprint_id":"original_voice","template_version":"1","outcome":"failed","raw":"中文"}
        conn=SimpleNamespace()
        with tempfile.TemporaryDirectory() as folder:
            queue=MaterialOutbox(str(Path(folder)/"queue.sqlite"));queue.pump=AsyncMock()
            with patch("core.utils.person_directory_sync.private_rpc",new=AsyncMock(return_value={"records":[record],"cursor":"20","more":False})),patch("core.utils.person_material_outbox.material_outbox",queue):
                await replay_behavior(conn,who)
                await replay_behavior(conn,who)
            with queue.connect() as db:
                rows=db.execute("SELECT actor,content FROM material").fetchall()
            self.assertEqual(len(rows),1)
            original=json.loads(rows[0][0])
            self.assertEqual((original["turn_id"],original["directory_version"],original["voiceprint_id"]),("original_turn",3,"original_voice"))
            self.assertEqual(json.loads(rows[0][1])["outcome"],"failed")

    async def test_foreign_device_export_is_not_enqueued(self):
        conn=SimpleNamespace()
        with patch("core.utils.person_directory_sync.private_rpc",new=AsyncMock(return_value={"records":[{"account":"11","person":"usr_a","generation":"0"}],"cursor":"1","more":False})):
            with self.assertRaisesRegex(ValueError,"owner_mismatch"):
                await replay_behavior(conn,actor())
