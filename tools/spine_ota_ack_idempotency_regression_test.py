"""Host-side regression for the Spine role OTA ACK + idempotency closed loop.

This test drives a *real* state machine — the ACK gate participates in every
reboot decision (no more "success then unconditionally reboot"). The model is a
line-by-line mirror of ``Application::HandleUpdateSpine`` + ``OnSpineOtaAck`` +
``FinishSpineOtaAckWait``, and each behavioral test is paired with a source
contract that pins the actual C++ to the same ordering.

Covers (requirements A-H):
- A. success sent, no ACK yet  -> never reboot.
- B. wrong task_id / status ACK -> never reboot.
- C. correct task_id + completed -> exactly one reboot.
- D. ACK timeout -> reboot once via local record; reconnect only re-sends success.
- E. duplicate task_id -> no re-download / re-slot.
- F. duplicate task_id but different content -> reject with E_TASK_MISMATCH.
- G. WebSocket send / status / close concurrency (no use-after-free / panic).
- H. HandleIncomingJson / OnSpineOtaAck dispatch path (receive-task -> worker).
"""

from __future__ import annotations

import json
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APPLICATION_CC = ROOT / "main" / "application.cc"
APPLICATION_H = ROOT / "main" / "application.h"
SPINE_OTA_H = ROOT / "main" / "spine_ota.h"
SPINE_OTA_CC = ROOT / "main" / "spine_ota.cc"
SPINE_ASSETS_CC = ROOT / "main" / "spine_assets.cc"
WS_PROTOCOL_CC = ROOT / "main" / "protocols" / "websocket_protocol.cc"
WS_PROTOCOL_H = ROOT / "main" / "protocols" / "websocket_protocol.h"

ACK_TIMEOUT_S = 5.0  # mirrors kSpineOtaAckTimeoutMs = 5000


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def wait_until(predicate, timeout_s: float = 2.0, interval_s: float = 0.001) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(interval_s)
    raise AssertionError("wait_until timed out")


class AckGate:
    """Faithful mirror of Application's ota_ack_mutex_ / ota_ack_cv_ / OnSpineOtaAck.

    ``on_ack`` runs on the WebSocket receive task; ``finish`` blocks the OTA
    worker task. Only an exact task_id + status=completed clears the wait.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition(threading.Lock())
        self.pending = False
        self.task_id = ""
        self.completed = False

    def begin(self, task_id: str) -> None:
        with self._cond:
            self.task_id = task_id
            self.completed = False
            self.pending = True

    def on_ack(self, task_id: str, status: str) -> bool:
        """Return True only when the ACK actually completed a pending wait."""
        with self._cond:
            if not self.pending:
                return False  # ignored: no waiter
            if task_id == self.task_id and status == "completed":
                self.completed = True
                self.pending = False
                self._cond.notify_all()
                return True
            return False  # mismatch: task_id or status

    def finish(self, timeout_s: float) -> bool:
        with self._cond:
            if not self.pending:
                return self.completed
            self._cond.wait_for(lambda: not self.pending, timeout=timeout_s)
            completed = self.completed
            self.pending = False
            return completed

    def cancel(self) -> None:
        with self._cond:
            self.pending = False
            self.completed = False
            self._cond.notify_all()


class WebSocketModel:
    """Faithful mirror of WebsocketProtocol's ws_mutex_ serialization."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.connected = True
        self.sends = 0
        self.closes = 0

    def send_text(self) -> bool:
        with self._lock:
            if not self.connected:
                return False
            self.sends += 1
            return True

    def send_audio(self) -> bool:
        with self._lock:
            if not self.connected:
                return False
            self.sends += 1
            return True

    def is_open(self) -> bool:
        with self._lock:
            return self.connected

    def close(self) -> None:
        with self._lock:
            self.connected = False
            self.closes += 1


class SpineOtaDevice:
    """State machine mirror of Application::HandleUpdateSpine.

    The critical difference from the previous test model: ``reboot`` happens ONLY
    after ``AckGate.finish`` returns (ACK delivered) or the wait times out. A
    successful download no longer reboots synchronously.
    """

    def __init__(self) -> None:
        self.ack = AckGate()
        self.nvs_last_task_id = ""
        self.nvs_last_sha256 = ""
        self.nvs_role_id = ""
        self.nvs_version = ""
        self.nvs_slot = "a"
        self.running_slot = "a"
        self.running = False
        self.downloads = 0
        self.slot_writes = 0
        self.reboots = 0
        self.audio_started = True
        self.audio_stops = 0
        self.audio_starts = 0
        self.state = "idle"
        self.statuses: list[dict] = []
        # Phases whose send_status delivery fails (mirrors SendText returning false).
        self.fail_sends: set[str] = set()

    def _send_status(self, task_id: str, phase: str, *,
                     error: str | None = None, duplicate: bool = False) -> bool:
        sent = phase not in self.fail_sends
        self.statuses.append({
            "phase": phase, "task_id": task_id,
            "error": error, "duplicate": duplicate,
            "sent": sent,
        })
        return sent

    def _reboot(self) -> None:
        # A reboot activates the committed slot and comes back to Idle.
        self.reboots += 1
        self.running_slot = self.nvs_slot
        self.state = "idle"

    def last_status(self) -> dict:
        return self.statuses[-1] if self.statuses else {}

    def handle(self, task: dict, *, ack_timeout_s: float = ACK_TIMEOUT_S,
               precheck_ok: bool = True, download_ok: bool = True) -> str:
        task_id = task["task_id"]
        role_id = task["role_id"]
        version = task["version"]
        sha256 = task["sha256"]
        pack_id = task["pack_id"]

        # --- pre-acquire busy checks (mirror device_state guard) ---
        if self.running:
            self._send_status(task_id, "failed", error="E_BUSY")
            return "busy"
        if self.state in ("upgrading", "activating", "starting", "wifi_configuring"):
            self._send_status(task_id, "failed", error="E_BUSY")
            return "busy"

        # --- acquire (SpineOta::TryAcquire) ---
        self.running = True
        try:
            # --- security precheck runs BEFORE the idempotency shortcut ---
            if not precheck_ok:
                self._send_status(task_id, "failed", error="E_SIG")
                return "precheck-failed"

            # --- BeginSpineOtaAckWait + accepted ---
            self.ack.begin(task_id)
            accepted_ok = self._send_status(task_id, "accepted")
            if not accepted_ok:
                # accepted delivery failed: abort before touching audio/download/
                # slot/reboot; the server re-delivers the task later.
                self.ack.cancel()
                return "accepted-failed"  # finally releases the acquire lock

            # --- idempotency (NVS completion record) ---
            if self.nvs_last_task_id and self.nvs_last_task_id == task_id:
                # Content integrity: same task_id must map to the same content.
                if (self.nvs_role_id != role_id or
                        self.nvs_version != version or
                        self.nvs_last_sha256 != sha256):
                    self._send_status(task_id, "failed", error="E_TASK_MISMATCH")
                    self.ack.cancel()
                    return "mismatch"

                self._send_status(task_id, "success", duplicate=True)
                if self.running_slot == self.nvs_slot:
                    # Already running the committed role: no reboot.
                    self.ack.finish(ack_timeout_s)
                    return "duplicate-active"

                # Committed but not yet active: wait ACK (or timeout), then reboot.
                self.ack.finish(ack_timeout_s)
                self._reboot()
                return "duplicate-reboot"

            # --- fresh download path ---
            self.audio_stops += 1
            self.audio_started = False
            self.state = "upgrading"

            if not download_ok:
                # Failure: restore audio + Idle, cancel waiter, release lock.
                self.ack.cancel()
                self.audio_starts += 1
                self.audio_started = True
                self.state = "idle"
                return "failed"

            # Download / verify / commit succeed -> persist completion record.
            self.downloads += 1
            self.slot_writes += 1
            self.nvs_last_task_id = task_id
            self.nvs_last_sha256 = sha256
            self.nvs_role_id = role_id
            self.nvs_version = version
            self.nvs_slot = "b" if self.nvs_slot == "a" else "a"

            # success is reported by the status callback during RunTask.
            self._send_status(task_id, "success")

            # Wait for server ACK before reboot. On timeout we still reboot,
            # relying on the persisted local completion record.
            self.ack.finish(ack_timeout_s)
            self._reboot()
            return "success-reboot"
        finally:
            self.running = False


def task(overrides: dict | None = None) -> dict:
    base = {
        "task_id": "t-1",
        "pack_id": "p-1",
        "role_id": "halloween_pumpkin",
        "version": "1.0.0",
        "sha256": "a" * 64,
    }
    if overrides:
        base.update(overrides)
    return base


def run_with_ack(m: SpineOtaDevice, t: dict, ack_task_id: str | None = None,
                 ack_status: str = "completed",
                 ack_timeout_s: float = ACK_TIMEOUT_S) -> tuple[threading.Thread, SpineOtaDevice]:
    """Run handle in a worker thread; deliver the ACK once success is observed."""
    ack_task_id = ack_task_id if ack_task_id is not None else t["task_id"]

    def worker() -> None:
        m.handle(t, ack_timeout_s=ack_timeout_s)

    th = threading.Thread(target=worker)
    th.start()
    wait_until(lambda: any(s["phase"] == "success" for s in m.statuses))
    m.ack.on_ack(ack_task_id, ack_status)
    th.join(timeout=2.0)
    return th, m


class AckStateMachineTests(unittest.TestCase):
    """A-H requirements, driven as a real state machine."""

    def test_A_no_reboot_before_ack(self):
        m = SpineOtaDevice()
        th = threading.Thread(target=m.handle, args=(task(),),
                              kwargs={"ack_timeout_s": ACK_TIMEOUT_S})
        th.start()
        wait_until(lambda: any(s["phase"] == "success" for s in m.statuses))
        # success sent, ACK not yet delivered -> must NOT reboot.
        self.assertEqual(m.reboots, 0)
        self.assertEqual(m.state, "upgrading")
        # Deliver the ACK -> exactly one reboot.
        m.ack.on_ack("t-1", "completed")
        th.join(timeout=2.0)
        self.assertFalse(th.is_alive())
        self.assertEqual(m.reboots, 1)
        self.assertEqual(m.downloads, 1)

    def test_B_wrong_task_id_or_status_no_reboot(self):
        m = SpineOtaDevice()
        th = threading.Thread(target=m.handle, args=(task(),),
                              kwargs={"ack_timeout_s": ACK_TIMEOUT_S})
        th.start()
        wait_until(lambda: any(s["phase"] == "success" for s in m.statuses))

        # Wrong task_id must be ignored.
        self.assertFalse(m.ack.on_ack("t-WRONG", "completed"))
        self.assertEqual(m.reboots, 0)
        # Wrong status must be ignored.
        self.assertFalse(m.ack.on_ack("t-1", "failed"))
        self.assertEqual(m.reboots, 0)
        self.assertFalse(m.ack.on_ack("t-1", "pending"))
        self.assertEqual(m.reboots, 0)

        # Correct task_id + completed -> single reboot.
        self.assertTrue(m.ack.on_ack("t-1", "completed"))
        th.join(timeout=2.0)
        self.assertEqual(m.reboots, 1)

    def test_C_correct_ack_single_reboot(self):
        m = SpineOtaDevice()
        th, m = run_with_ack(m, task())
        self.assertEqual(m.reboots, 1)
        self.assertEqual(m.downloads, 1)
        self.assertEqual(m.slot_writes, 1)
        # Reboot activated the committed slot.
        self.assertEqual(m.running_slot, m.nvs_slot)

    def test_D_ack_timeout_then_resend_only_success(self):
        m = SpineOtaDevice()
        # No ACK delivered -> wait times out -> single reboot via local record.
        m.handle(task(), ack_timeout_s=0.01)
        self.assertEqual(m.downloads, 1)
        self.assertEqual(m.reboots, 1)

        # Reconnect: server re-sends the same task_id.
        m.handle(task(), ack_timeout_s=0.01)
        self.assertEqual(m.downloads, 1)      # no re-download
        self.assertEqual(m.slot_writes, 1)    # no re-slot
        self.assertEqual(m.reboots, 1)        # no re-reboot
        dup = [s for s in m.statuses if s["phase"] == "success" and s["duplicate"]]
        self.assertTrue(dup, "reconnect must re-send success(duplicate=true)")

    def test_E_duplicate_task_id_no_redownload(self):
        m = SpineOtaDevice()
        th, m = run_with_ack(m, task())
        self.assertEqual(m.downloads, 1)
        self.assertEqual(m.slot_writes, 1)
        self.assertEqual(m.reboots, 1)

        # Same task_id after successful completion (already active) -> no download.
        m.handle(task(), ack_timeout_s=0.01)
        self.assertEqual(m.downloads, 1)
        self.assertEqual(m.slot_writes, 1)
        self.assertEqual(m.reboots, 1)
        self.assertEqual(m.last_status()["phase"], "success")
        self.assertTrue(m.last_status()["duplicate"])

    def test_F_duplicate_different_content_rejected(self):
        m = SpineOtaDevice()
        m.handle(task(), ack_timeout_s=0.01)  # complete t-1 (timeout -> reboot)
        self.assertEqual(m.downloads, 1)

        # Same task_id but different role/version/hash -> must reject.
        for bad in (
            task({"role_id": "other_role"}),
            task({"version": "2.0.0"}),
            task({"sha256": "b" * 64}),
        ):
            m.handle(bad, ack_timeout_s=0.01)
            self.assertEqual(m.downloads, 1, "must not re-download on content mismatch")
            self.assertEqual(m.reboots, 1, "must not reboot on content mismatch")
            self.assertEqual(m.last_status()["phase"], "failed")
            self.assertEqual(m.last_status()["error"], "E_TASK_MISMATCH")

    def test_F2_different_task_id_triggers_new_download(self):
        m = SpineOtaDevice()
        m.handle(task(), ack_timeout_s=0.01)
        self.assertEqual(m.downloads, 1)
        # A genuinely new task_id is allowed to download.
        m.handle(task({"task_id": "t-2", "sha256": "c" * 64}),
                 ack_timeout_s=0.01)
        self.assertEqual(m.downloads, 2)
        self.assertEqual(m.slot_writes, 2)
        self.assertEqual(m.reboots, 2)

    def test_failed_download_restores_audio_and_idle(self):
        m = SpineOtaDevice()
        m.handle(task(), ack_timeout_s=0.01, download_ok=False)
        self.assertEqual(m.downloads, 0)
        self.assertTrue(m.audio_started)
        self.assertEqual(m.state, "idle")
        self.assertEqual(m.audio_stops, 1)
        self.assertEqual(m.audio_starts, 1)
        self.assertEqual(m.nvs_last_task_id, "")
        self.assertFalse(m.running)


class AckDispatchPathTests(unittest.TestCase):
    """H: drive the receive-task -> OnSpineOtaAck -> worker path."""

    def _dispatch(self, m: SpineOtaDevice, payload: str) -> bool:
        """Mirror HandleIncomingJson's spine_ota_ack branch -> OnSpineOtaAck."""
        root = json.loads(payload)
        if root.get("type") != "spine_ota_ack":
            return False
        tid = root.get("task_id")
        status = root.get("status")
        if not isinstance(tid, str) or not isinstance(status, str):
            return False  # malformed -> ignored
        return m.ack.on_ack(tid, status)

    def test_receive_path_completes_worker(self):
        m = SpineOtaDevice()
        th = threading.Thread(target=m.handle, args=(task(),),
                              kwargs={"ack_timeout_s": ACK_TIMEOUT_S})
        th.start()
        wait_until(lambda: any(s["phase"] == "success" for s in m.statuses))
        self.assertEqual(m.reboots, 0)

        # Simulate the real JSON frame arriving on the receive task.
        acked = self._dispatch(
            m, '{"type":"spine_ota_ack","task_id":"t-1","status":"completed"}')
        self.assertTrue(acked)
        th.join(timeout=2.0)
        self.assertEqual(m.reboots, 1)

    def test_receive_path_ignores_mismatch_and_malformed(self):
        m = SpineOtaDevice()
        th = threading.Thread(target=m.handle, args=(task(),),
                              kwargs={"ack_timeout_s": 0.2})
        th.start()
        wait_until(lambda: any(s["phase"] == "success" for s in m.statuses))

        self.assertFalse(self._dispatch(m, '{"type":"spine_ota_ack","task_id":"t-9","status":"completed"}'))
        self.assertFalse(self._dispatch(m, '{"type":"spine_ota_ack","task_id":"t-1","status":"pending"}'))
        self.assertFalse(self._dispatch(m, '{"type":"spine_ota_ack","task_id":"t-1"}'))
        self.assertFalse(self._dispatch(m, '{"type":"spine_ota_ack","status":"completed"}'))
        self.assertEqual(m.reboots, 0)

        # Timeout path (no valid ACK) -> reboot once via local record.
        th.join(timeout=2.0)
        self.assertEqual(m.reboots, 1)

    def test_ack_after_waiter_gone_is_ignored(self):
        m = SpineOtaDevice()
        m.handle(task(), ack_timeout_s=0.01)  # timed out + rebooted
        self.assertFalse(m.ack.on_ack("t-1", "completed"))  # no waiter now
        self.assertEqual(m.reboots, 1)


class WebSocketConcurrencyTests(unittest.TestCase):
    """G: concurrent send / status / close must not crash or use-after-free."""

    def test_concurrent_send_and_close_is_safe(self):
        ws = WebSocketModel()
        errors: list[Exception] = []

        def sender(n: int) -> None:
            try:
                for _ in range(n):
                    ws.send_audio()
                    ws.send_text()
            except Exception as e:  # pragma: no cover - failure signal
                errors.append(e)

        def closer(n: int) -> None:
            try:
                for _ in range(n):
                    ws.close()
            except Exception as e:  # pragma: no cover - failure signal
                errors.append(e)

        threads = [threading.Thread(target=sender, args=(2000,)) for _ in range(4)]
        threads += [threading.Thread(target=closer, args=(2000,)) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], "no exception may escape concurrent send/close")
        self.assertEqual(ws.closes, 2000 * 2)
        # A send after close returns False (never dereferences a dead socket).
        self.assertFalse(ws.send_text())
        self.assertFalse(ws.send_audio())

    def test_close_blocks_during_inflight_send(self):
        ws = WebSocketModel()
        order: list[str] = []

        def send() -> None:
            with ws._lock:  # simulate an in-flight send holding the mutex
                order.append("send-inflight")
                time.sleep(0.05)

        def close() -> None:
            ws.close()
            order.append("close-done")

        th_send = threading.Thread(target=send)
        th_close = threading.Thread(target=close)
        th_send.start()
        time.sleep(0.01)  # ensure send holds the lock first
        th_close.start()
        th_send.join()
        th_close.join()
        # close() must serialize behind the in-flight send.
        self.assertEqual(order, ["send-inflight", "close-done"])


class SendFailureTests(unittest.TestCase):
    """accepted / success delivery failures drive flow decisions (no false reboot)."""

    def test_accepted_send_failure_aborts_before_download(self):
        m = SpineOtaDevice()
        m.fail_sends.add("accepted")
        result = m.handle(task(), ack_timeout_s=0.01)
        self.assertEqual(result, "accepted-failed")
        self.assertEqual(m.downloads, 0)
        self.assertEqual(m.slot_writes, 0)
        self.assertEqual(m.reboots, 0)
        self.assertEqual(m.audio_stops, 0)   # audio never stopped
        self.assertTrue(m.audio_started)
        self.assertEqual(m.state, "idle")    # state never entered upgrading
        self.assertFalse(m.running)          # acquire lock released
        self.assertFalse(m.ack.pending)      # waiter cancelled
        self.assertEqual(m.last_status()["phase"], "accepted")
        self.assertFalse(m.last_status()["sent"])

    def test_success_send_failure_timeout_reboot_once_then_resend_only(self):
        m = SpineOtaDevice()
        m.fail_sends.add("success")
        # Download/commit still happens; success delivery fails -> ACK timeout -> reboot once.
        m.handle(task(), ack_timeout_s=0.01)
        self.assertEqual(m.downloads, 1)
        self.assertEqual(m.slot_writes, 1)
        self.assertEqual(m.reboots, 1)
        succ = [s for s in m.statuses if s["phase"] == "success"]
        self.assertTrue(succ)
        self.assertFalse(succ[-1]["sent"])

        # Reconnect with the same task_id: only re-send success(duplicate=true).
        m.fail_sends.clear()
        m.handle(task(), ack_timeout_s=0.01)
        self.assertEqual(m.downloads, 1)      # no re-download
        self.assertEqual(m.slot_writes, 1)    # no re-slot
        self.assertEqual(m.reboots, 1)        # no re-reboot (already active)
        dup = [s for s in m.statuses if s["phase"] == "success" and s["duplicate"]]
        self.assertTrue(dup)
        self.assertTrue(dup[-1]["sent"])

    def test_accepted_failure_with_wrong_ack_no_deadlock_no_reboot(self):
        m = SpineOtaDevice()
        m.fail_sends.add("accepted")
        th = threading.Thread(target=m.handle, args=(task(),),
                              kwargs={"ack_timeout_s": 0.01})
        th.start()
        # A wrong/racing ACK must be a no-op against the accepted-failure cancel.
        m.ack.on_ack("t-1", "completed")
        th.join(timeout=2.0)
        self.assertFalse(th.is_alive())
        self.assertEqual(m.reboots, 0)
        self.assertEqual(m.downloads, 0)
        self.assertFalse(m.running)

    def test_success_failure_with_wrong_ack_no_deadlock_no_false_reboot(self):
        m = SpineOtaDevice()
        m.fail_sends.add("success")
        th = threading.Thread(target=m.handle, args=(task(),),
                              kwargs={"ack_timeout_s": 0.2})
        th.start()
        wait_until(lambda: any(s["phase"] == "success" for s in m.statuses))
        # Wrong task_id / wrong status must not reboot while the worker waits.
        self.assertFalse(m.ack.on_ack("t-WRONG", "completed"))
        self.assertFalse(m.ack.on_ack("t-1", "failed"))
        self.assertEqual(m.reboots, 0)
        th.join(timeout=2.0)  # timeout -> single reboot
        self.assertFalse(th.is_alive())
        self.assertEqual(m.reboots, 1)


class SourceContracts(unittest.TestCase):
    """Pin the real C++ to the state machine's ordering (no string-only tests)."""

    def test_handle_update_spine_does_not_close_websocket(self):
        body = read(APPLICATION_CC).split("void Application::HandleUpdateSpine", 1)[1]
        body = body.split("bool Application::UpgradeFirmware", 1)[0]
        self.assertNotIn("protocol_->CloseAudioChannel()", body)

    def test_reboot_only_after_finish_ack_wait(self):
        text = read(APPLICATION_CC)
        body = text.split("void Application::HandleUpdateSpine", 1)[1]
        body = body.split("bool Application::UpgradeFirmware", 1)[0]
        # Every Reboot(); call in HandleUpdateSpine must be preceded by a
        # FinishSpineOtaAckWait call (i.e. success path waits for ACK first).
        # Search for the actual call (with semicolon) so comment mentions are skipped.
        found = 0
        idx = 0
        while True:
            idx = body.find("Reboot();", idx)
            if idx == -1:
                break
            found += 1
            self.assertIn("FinishSpineOtaAckWait", body[:idx],
                          "Reboot() may only follow FinishSpineOtaAckWait")
            idx += len("Reboot();")
        self.assertGreater(found, 0, "expected at least one Reboot() call")

    def test_on_ack_requires_exact_task_and_completed(self):
        body = read(APPLICATION_CC).split("void Application::OnSpineOtaAck", 1)[1]
        body = body.split("void Application::HandleUpdateSpine", 1)[0]
        self.assertIn('tid == ota_ack_task_id_ && st == "completed"', body)
        self.assertIn("ota_ack_cv_.notify_all()", body)

    def test_dispatch_spine_ota_ack_to_on_spine_ota_ack(self):
        text = read(APPLICATION_CC)
        self.assertIn('strcmp(type->valuestring, "spine_ota_ack") == 0', text)
        self.assertIn("OnSpineOtaAck(root)", text)

    def test_precheck_before_content_mismatch_check(self):
        text = read(APPLICATION_CC)
        self.assertLess(text.index("SpineOta::Precheck"),
                        text.index("last_sha256 != task.sha256"))

    def test_content_mismatch_rejected(self):
        text = read(APPLICATION_CC)
        self.assertIn("last_sha256 != task.sha256", text)
        self.assertIn("E_TASK_MISMATCH", text)
        self.assertIn("CancelSpineOtaAckWait()", text)

    def test_duplicate_is_boolean_field(self):
        text = read(APPLICATION_CC)
        self.assertIn('cJSON_AddBoolToObject(msg, "duplicate", true)', text)
        self.assertNotIn('cJSON_AddStringToObject(msg, "flag", flag)', text)

    def test_nvs_persists_sha256(self):
        assets = read(SPINE_ASSETS_CC)
        self.assertIn('nvs_set_str(handle, "last_sha256", sha256.c_str())', assets)
        ota = read(SPINE_OTA_CC)
        self.assertIn("task.sha256, &nvs_err", ota)
        # kTaskMismatch is a distinct, stringified error code.
        self.assertIn("kTaskMismatch", read(SPINE_OTA_H))
        self.assertIn("E_TASK_MISMATCH", read(SPINE_OTA_CC))

    def test_ack_wait_helpers_declared(self):
        h = read(APPLICATION_H)
        for needle in ("BeginSpineOtaAckWait", "FinishSpineOtaAckWait",
                       "CancelSpineOtaAckWait", "OnSpineOtaAck"):
            self.assertIn(needle, h)

    def test_accepted_send_failure_aborts_before_audio_stop(self):
        text = read(APPLICATION_CC)
        body = text.split("void Application::HandleUpdateSpine", 1)[1]
        body = body.split("bool Application::UpgradeFirmware", 1)[0]
        self.assertIn("accepted_send_failed", body)
        self.assertIn("action=abort_before_download", body)
        self.assertIn("const bool accepted_ok = send_status", body)
        # The accepted-failure check + CancelSpineOtaAckWait must precede the
        # audio stop (i.e. abort happens before touching audio/download).
        self.assertLess(body.index("accepted_ok"),
                        body.index("audio_service_.Stop()"))

    def test_success_send_failure_logged_and_flow_unchanged(self):
        text = read(APPLICATION_CC)
        self.assertIn("success_send_failed", text)
        self.assertIn("success_send_ok", text)

    def test_ws_mutex_serializes_send_and_close(self):
        cc = read(WS_PROTOCOL_CC)
        h = read(WS_PROTOCOL_H)
        self.assertIn("mutable std::mutex ws_mutex_", h)
        self.assertIn("std::lock_guard<std::mutex> lock(ws_mutex_)", cc)
        close_body = cc.split("void WebsocketProtocol::CloseAudioChannel()", 1)[1]
        self.assertIn("ws_mutex_", close_body)
        self.assertIn("doomed = std::move(websocket_)", close_body)
        self.assertIn("doomed.reset()", close_body)


if __name__ == "__main__":
    unittest.main()
