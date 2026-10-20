"""
设备状态管理器：管理每台设备的 pc_mode 开关、角色、超时检测。
通过 active_roles.json 文件实现跨进程通信（网关写、esp32-server 读）。
"""
import json
import os
import time
from pathlib import Path

try:
    from filelock import FileLock
except ImportError:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "filelock 未安装，多进程并发写 active_roles.json 时可能出现数据竞争。"
        "建议执行: pip install filelock"
    )

    class FileLock:
        """无锁 fallback：单进程场景可用，多进程有竞争风险。"""
        def __init__(self, *a, **kw):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

PC_MODE_TIMEOUT = 15 * 60  # 15 分钟无 pc_* 调用自动退出


class StateManager:
    """每台设备独立状态，持久化到 JSON 文件。"""

    def __init__(self, base_dir: str | Path | None = None):
        base = Path(base_dir) if base_dir else Path(
            os.environ.get("AGENT_PERSONAS_DIR", str(Path(__file__).parent))
        )
        self.state_file = base / "active_roles.json"
        self.lock_file = base / "active_roles.json.lock"

    # ── 读 ──────────────────────────────────────────

    def get(self, device_id: str) -> dict:
        data = self._read_all()
        return data.get(device_id, self._default())

    # ── 写 ──────────────────────────────────────────

    def set_bound_pc(self, controller_id: str, pc_device_id: str):
        """存储控制器 → PC 设备的绑定关系。"""
        with FileLock(str(self.lock_file)):
            data = self._read_all()
            s = data.get(controller_id, self._default())
            s["bound_pc_id"] = pc_device_id
            data[controller_id] = s
            self._write(data)

    def get_bound_pc(self, controller_id: str) -> str:
        """查询控制器绑定的 PC 设备 ID，未绑定返回空字符串。"""
        s = self.get(controller_id)
        return s.get("bound_pc_id", "")

    def set_pc_mode(self, device_id: str, enabled: bool, role: str | None = None):
        with FileLock(str(self.lock_file)):
            data = self._read_all()
            s = data.get(device_id, self._default())
            s["pc_mode"] = enabled
            if role is not None:
                s["role"] = role
            if enabled:
                s["last_pc_call_ts"] = time.time()
                s["timeout_notified"] = False
            else:
                s["last_pc_call_ts"] = 0
                s["timeout_notified"] = False
            data[device_id] = s
            self._write(data)

    def touch_pc_call(self, device_id: str):
        """每次 pc_* 工具被成功调用时刷新时间戳。"""
        with FileLock(str(self.lock_file)):
            data = self._read_all()
            s = data.get(device_id, self._default())
            s["last_pc_call_ts"] = time.time()
            data[device_id] = s
            self._write(data)

    # ── 超时 ────────────────────────────────────────

    def check_timeout(self, device_id: str) -> bool:
        """若超时则自动关闭 pc_mode 并标记 timeout_notified，返回 True。"""
        s = self.get(device_id)
        if not s["pc_mode"]:
            return False
        ts = s["last_pc_call_ts"]
        if ts <= 0:
            return False
        if (time.time() - ts) <= PC_MODE_TIMEOUT:
            return False
        with FileLock(str(self.lock_file)):
            data = self._read_all()
            s2 = data.get(device_id, self._default())
            # 双重检查：防止并发重复写
            if s2["pc_mode"] and s2["last_pc_call_ts"] == ts:
                s2["pc_mode"] = False
                s2["timeout_notified"] = True
                data[device_id] = s2
                self._write(data)
        return True

    def consume_timeout_notification(self, device_id: str) -> bool:
        """一次性消费 timeout_notified 标记。"""
        with FileLock(str(self.lock_file)):
            data = self._read_all()
            s = data.get(device_id, self._default())
            if s.get("timeout_notified"):
                s["timeout_notified"] = False
                data[device_id] = s
                self._write(data)
                return True
        return False

    # ── 内部 ────────────────────────────────────────

    @staticmethod
    def _default() -> dict:
        return {
            "pc_mode": False,
            "role": "default",
            "last_pc_call_ts": 0,
            "timeout_notified": False,
            "bound_pc_id": "",
        }

    def _read_all(self) -> dict:
        if not self.state_file.exists():
            return {}
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _write(self, data: dict):
        self.state_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
