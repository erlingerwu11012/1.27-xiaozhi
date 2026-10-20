import hashlib
import hmac
import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parents[1] / "core/utils/hardware_billing.py"
spec = importlib.util.spec_from_file_location("hardware_billing_proof", path)
hb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hb)

class BillingProofTests(unittest.TestCase):
    def request(self, body=b'{"model":"qwen-plus"}'):
        return SimpleNamespace(url="http://127.0.0.1:3000/v1/chat/completions", method="POST", content=body,
                               headers=hb.request_headers("123", "llm", "request1"))
    def env(self):
        return patch.dict(os.environ, {"HW_BILLING_SERVICE_KEY": "synthetic-test-key-only-0123456789abcdef",
                                      "HW_BILLING_GATEWAY_ORIGIN": "http://127.0.0.1:3000"})
    def test_cross_language_signature_contract(self):
        r=self.request()
        with self.env(),patch.object(hb.time,"time",return_value=1790820000): hb.sign_request(r)
        expected="\n".join(["POST","/v1/chat/completions",hashlib.sha256(r.content).hexdigest(),"1790820000","request1","123","llm"])
        self.assertEqual(r.headers["X-HW-Signature"],hmac.new(b"synthetic-test-key-only-0123456789abcdef",expected.encode(),hashlib.sha256).hexdigest())
    def test_retries_keep_id_and_bind_bytes(self):
        a,b=self.request(),self.request(b'{"model":"changed"}')
        with self.env(): hb.sign_request(a);hb.sign_request(b)
        self.assertEqual(a.headers["X-HW-Request-ID"],b.headers["X-HW-Request-ID"])
        self.assertNotEqual(a.headers["X-HW-Signature"],b.headers["X-HW-Signature"])
    def test_external_origin_rejected(self):
        r=self.request();r.url="https://example.invalid/v1/chat/completions"
        with self.env(),self.assertRaises(ValueError):hb.sign_request(r)
    def test_missing_secret_rejected(self):
        with patch.dict(os.environ,{},clear=True),self.assertRaises(ValueError):hb.sign_request(self.request())
    def test_unknown_account_and_operation_rejected(self):
        for account,operation in [(None,"llm"),("abc","llm"),("123","aimi-chat"),("123","portrait_add")]:
            with self.assertRaises(ValueError):hb.request_headers(account,operation)
    def test_no_aimi_crossing(self):
        with self.assertRaises(ValueError):hb.provider_context({"hardware_billing":True,"aimi_device_gateway":True})
        with self.assertRaises(ValueError):hb.provider_context({"hardware_billing":True,"hardware_account_id":"123","model_name":"aimi-chat"})
        self.assertIsNone(hb.provider_context({"aimi_device_gateway":True}))
    def test_verified_provider_context(self):
        self.assertEqual(hb.provider_context({"hardware_billing":True,"hardware_account_id":"123","model_name":"qwen-plus"}),{"account_id":"123","operation":"llm"})

    def test_audio_signature_binds_account_model_and_fresh_socket(self):
        config={"hardware_billing":True,"hardware_account_id":"123","hardware_operation":"asr","model_name":"qwen3-asr-flash-realtime"}
        url="ws://127.0.0.1:3000/bailian/api-ws/v1/realtime?model=qwen3-asr-flash-realtime"
        with self.env(),patch.dict(os.environ,{"HW_BILLING_AUDIO_GATEWAY_ORIGIN":"http://127.0.0.1:3000"}):
            a=hb.websocket_headers(url,config,{"Authorization":"Bearer synthetic"})
            b=hb.websocket_headers(url,config,{"Authorization":"Bearer synthetic"})
            self.assertNotEqual(a["X-HW-Request-ID"],b["X-HW-Request-ID"])
            self.assertEqual(a["X-HW-Account"],"123")
            self.assertEqual(a["X-HW-Operation"],"asr")
            self.assertEqual(a["Authorization"],"Bearer synthetic")
            self.assertEqual(len(a["X-HW-Signature"]),64)
            with self.assertRaises(ValueError):hb.websocket_headers(url.replace("3000","9999"),config,{})
            with self.assertRaises(ValueError):hb.websocket_headers(url.replace("qwen3-asr-flash-realtime","qwen-plus"),config,{})
            with self.assertRaises(ValueError):hb.provider_context({**config,"aimi_device_gateway":True})

    def test_habit_prefers_owned_route_and_signs_each_call(self):
        from core.utils import habit_router
        from unittest.mock import MagicMock
        cfg={"hardware_billing":True,"hardware_account_id":"123","model_name":"qwen-plus",
             "hardware_operation":"llm","base_url":"http://127.0.0.1:3000/v1","api_key":"synthetic"}
        conn=SimpleNamespace(config={"selected_module":{"LLM":"owned"},"LLM":{"owned":cfg}})
        with patch("config.manage_api_client.get_server_config") as shared:
            route=habit_router._get_habit_analyze_config(conn)
            shared.assert_not_called()
        self.assertEqual(route["hardware_context"]["operation"],"habit")
        client=MagicMock();response=MagicMock();response.choices[0].message.tool_calls=[]
        response.choices[0].message.model_dump.return_value={"role":"assistant","content":"无规律"}
        client.chat.completions.create.return_value=response
        with patch("openai.OpenAI",return_value=client):
            self.assertEqual(habit_router._call_llm_with_tools(route,"合成材料",[],lambda *_:None),[])
        call=client.chat.completions.create.call_args.kwargs
        self.assertEqual(call["extra_headers"]["X-HW-Account"],"123")
        self.assertEqual(call["extra_headers"]["X-HW-Operation"],"habit")
        self.assertFalse(call["extra_body"]["enable_thinking"])
        client.close.assert_called_once()

if __name__ == "__main__":unittest.main(verbosity=2)
