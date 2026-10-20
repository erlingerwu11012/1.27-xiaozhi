"""Host-side behavior checks for the face-config executor protocol.

Does not require ESP-IDF or a device. Mirrors the production request
ownership rules in main/face_config_store.cc: heap-owned Request, refcount,
no fallback to caller-side NVS, and no write into caller outputs after
timeout/cancel.
"""

from __future__ import annotations

import threading
import time
import unittest
from collections import deque
from typing import Optional


class Request:
    def __init__(self) -> None:
        self.refs = 1
        self.op = ""
        self.in_value = None
        self.out_value = None
        self.ok = False
        self.done = threading.Event()
        self.released = False

    def retain(self) -> None:
        self.refs += 1

    def release(self) -> None:
        self.refs -= 1
        if self.refs == 0:
            self.released = True


class FaceConfigStoreHost:
    def __init__(self, queue_depth: int = 4, ready: bool = True) -> None:
        self.ready = ready
        self.queue_depth = queue_depth
        self.queue: deque[Request] = deque()
        self.nvs = {"websocket.token": "", "face.session_url": ""}
        self.lock = threading.Lock()
        self.alloc_fail = False
        self.direct_nvs_from_caller = 0
        self.worker_stop = False
        self.worker = threading.Thread(target=self._worker, daemon=True)
        self.worker_started = False
        self.hold_worker = threading.Event()
        self.hold_worker.set()

    def start(self) -> bool:
        if not self.ready:
            return False
        if not self.worker_started:
            self.worker_started = True
            self.worker.start()
        return True

    def ensure_ready(self) -> bool:
        return self.ready and self.start()

    def _worker(self) -> None:
        while not self.worker_stop:
            req = None
            with self.lock:
                if self.queue:
                    req = self.queue.popleft()
            if req is None:
                time.sleep(0.005)
                continue
            self.hold_worker.wait()
            with self.lock:
                if req.op == "load_token":
                    req.out_value = self.nvs.get("websocket.token", "")
                    req.ok = True
                elif req.op == "load_cap":
                    url = self.nvs.get("face.session_url", "")
                    if url == "invalid":
                        self.nvs["face.session_url"] = ""
                        req.out_value = ""
                        req.ok = True
                    else:
                        req.out_value = url
                        req.ok = True
                elif req.op == "save_cap":
                    self.nvs["face.session_url"] = req.in_value
                    req.ok = True
                elif req.op == "clear_cap":
                    self.nvs["face.session_url"] = ""
                    req.ok = True
            req.done.set()
            req.release()

    def _submit(self, op: str, in_value=None, timeout: float = 0.3) -> Optional[Request]:
        if not self.ensure_ready():
            return None
        if self.alloc_fail:
            return None
        req = Request()
        req.op = op
        req.in_value = in_value
        with self.lock:
            if len(self.queue) >= self.queue_depth:
                req.release()
                return None
            req.retain()
            self.queue.append(req)
        if not req.done.wait(timeout):
            req.release()
            return None
        return req

    def load_token(self, timeout: float = 0.3) -> tuple[bool, str]:
        caller_out = ""
        req = self._submit("load_token", timeout=timeout)
        if req is None:
            return False, caller_out
        caller_out = req.out_value or ""
        req.release()
        return True, caller_out

    def load_capability(self) -> tuple[bool, str]:
        req = self._submit("load_cap")
        if req is None:
            return False, ""
        value = req.out_value or ""
        req.release()
        return True, value

    def save_capability(self, url: str) -> bool:
        req = self._submit("save_cap", url)
        if req is None:
            return False
        ok = req.ok
        req.release()
        return ok

    def clear_capability(self) -> bool:
        req = self._submit("clear_cap")
        if req is None:
            return False
        ok = req.ok
        req.release()
        return ok


class FaceConfigStoreProtocolTests(unittest.TestCase):
    def tearDown(self) -> None:
        store = getattr(self, "store", None)
        if store is not None:
            store.worker_stop = True
            store.hold_worker.set()

    def test_normal_read_and_token_refresh(self) -> None:
        self.store = FaceConfigStoreHost()
        self.store.nvs["websocket.token"] = "first"
        ok, token = self.store.load_token()
        self.assertTrue(ok)
        self.assertEqual(token, "first")
        self.store.nvs["websocket.token"] = "second"
        ok, token = self.store.load_token()
        self.assertTrue(ok)
        self.assertEqual(token, "second")
        self.assertEqual(self.store.direct_nvs_from_caller, 0)

    def test_read_failure_when_not_ready(self) -> None:
        self.store = FaceConfigStoreHost(ready=False)
        ok, token = self.store.load_token()
        self.assertFalse(ok)
        self.assertEqual(token, "")
        self.assertEqual(self.store.direct_nvs_from_caller, 0)

    def test_invalid_capability_is_erased(self) -> None:
        self.store = FaceConfigStoreHost()
        self.store.nvs["face.session_url"] = "invalid"
        ok, url = self.store.load_capability()
        self.assertTrue(ok)
        self.assertEqual(url, "")
        self.assertEqual(self.store.nvs["face.session_url"], "")

    def test_save_then_load_sees_update(self) -> None:
        self.store = FaceConfigStoreHost()
        self.assertTrue(self.store.save_capability("https://example.com/s"))
        ok, url = self.store.load_capability()
        self.assertTrue(ok)
        self.assertEqual(url, "https://example.com/s")

    def test_concurrent_reads(self) -> None:
        self.store = FaceConfigStoreHost()
        self.store.nvs["websocket.token"] = "shared"
        results = []

        def worker() -> None:
            results.append(self.store.load_token())

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(results), 4)
        self.assertTrue(all(ok and token == "shared" for ok, token in results))

    def test_queue_full_does_not_fallback(self) -> None:
        self.store = FaceConfigStoreHost(queue_depth=1)
        self.store.hold_worker.clear()
        started = threading.Event()

        def blocked() -> None:
            started.set()
            self.store.load_token(timeout=0.4)

        t = threading.Thread(target=blocked)
        t.start()
        started.wait(1)
        time.sleep(0.05)
        ok, token = self.store.load_token(timeout=0.05)
        self.assertFalse(ok)
        self.assertEqual(token, "")
        self.assertEqual(self.store.direct_nvs_from_caller, 0)
        self.store.hold_worker.set()
        t.join()

    def test_alloc_failure_does_not_fallback(self) -> None:
        self.store = FaceConfigStoreHost()
        self.store.alloc_fail = True
        ok, token = self.store.load_token()
        self.assertFalse(ok)
        self.assertEqual(token, "")
        self.assertEqual(self.store.direct_nvs_from_caller, 0)

    def test_timeout_does_not_write_caller_output(self) -> None:
        self.store = FaceConfigStoreHost()
        self.store.hold_worker.clear()
        caller_out = "sentinel"
        ok, token = self.store.load_token(timeout=0.05)
        self.assertFalse(ok)
        self.assertEqual(token, "")
        self.assertNotEqual(token, "sentinel")
        self.assertEqual(caller_out, "sentinel")
        self.store.hold_worker.set()
        time.sleep(0.05)


class GraphicBenchmarkMacroTests(unittest.TestCase):
    def test_disabled_benchmark_still_contains_code(self) -> None:
        from pathlib import Path

        text = (Path(__file__).resolve().parents[1]
                / "components/cubicat_home_engine/utils/helper.h").read_text(
                    encoding="utf-8")
        disabled = text.split("#else", 1)[1].split("#endif", 1)[0]
        self.assertIn("do { code; } while (0);", disabled)
        self.assertNotIn("_timerStack", disabled)
        self.assertNotIn("_classifiedStatistics", disabled)
        # Execution of the production macro is tools/graphic_benchmark_macro_host_test.cpp.


class FaceConfigStoreSourceContractTests(unittest.TestCase):
    def test_executor_uses_internal_sram_stack(self) -> None:
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        store = (root / "main/face_config_store.cc").read_text(encoding="utf-8")
        client = (root / "main/face_enrollment_client.cc").read_text(encoding="utf-8")
        diag = (root / "main/task_diagnostics.cc").read_text(encoding="utf-8")
        self.assertIn('xTaskCreateWithCaps(', store)
        create = store.split("xTaskCreateWithCaps(", 1)[1].split(";", 1)[0]
        self.assertIn('"face_cfg"', create)
        self.assertIn("MALLOC_CAP_INTERNAL", create)
        self.assertNotIn("MALLOC_CAP_SPIRAM", create)
        self.assertNotIn("Settings settings(", client)
        self.assertIn("Settings settings(", store)
        self.assertIn("xTaskCreateWithCaps(", diag)
        diag_create = diag.split("PeriodicLoggerTask, \"task_diag\"", 1)[1].split(";", 1)[0]
        self.assertIn("MALLOC_CAP_SPIRAM", diag_create)
        task_list = diag.split("void LogTaskList", 1)[1].split("void RunPsramBenchmark", 1)[0]
        self.assertNotIn("MALLOC_CAP_INTERNAL", task_list)


if __name__ == "__main__":
    unittest.main()
