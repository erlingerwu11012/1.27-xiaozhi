"""人脸采集限流与匿名化指标（不记录 token / 姓名 / 图片）。"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Deque, Dict, Optional, Tuple

# 创建 session：同一 Device-Id / account 滑动窗口
DEVICE_CREATE_LIMIT = 5
DEVICE_CREATE_WINDOW_SEC = 600
ACCOUNT_CREATE_LIMIT = 20
ACCOUNT_CREATE_WINDOW_SEC = 600

# 同一 session 质量失败：达到阈值后要求重新开始（retryable=false）
SESSION_QUALITY_FAIL_LIMIT = 8
SESSION_QUALITY_FAIL_WINDOW_SEC = 120

# 上传失败（任意）短时限流，防刷算力
SESSION_UPLOAD_FAIL_LIMIT = 20
SESSION_UPLOAD_FAIL_WINDOW_SEC = 60


@dataclass
class EnrollmentMetrics:
    created: int = 0
    ready: int = 0
    confirmed: int = 0
    cancelled: int = 0
    expired: int = 0
    rejected_by_quality: int = 0
    rate_limited: int = 0
    sweeper_deleted: int = 0

    def as_dict(self) -> Dict[str, int]:
        return {
            "created": self.created,
            "ready": self.ready,
            "confirmed": self.confirmed,
            "cancelled": self.cancelled,
            "expired": self.expired,
            "rejected_by_quality": self.rejected_by_quality,
            "rate_limited": self.rate_limited,
            "sweeper_deleted": self.sweeper_deleted,
        }


_METRICS = EnrollmentMetrics()
_METRICS_LOCK = threading.Lock()


def incr_metric(name: str, n: int = 1) -> None:
    with _METRICS_LOCK:
        if hasattr(_METRICS, name):
            setattr(_METRICS, name, int(getattr(_METRICS, name)) + n)


def get_metrics() -> Dict[str, int]:
    with _METRICS_LOCK:
        return _METRICS.as_dict()


def reset_metrics_for_tests() -> None:
    with _METRICS_LOCK:
        for k in _METRICS.as_dict():
            setattr(_METRICS, k, 0)


class SlidingWindowLimiter:
    def __init__(self):
        self._guard = threading.Lock()
        self._buckets: Dict[str, Deque[float]] = defaultdict(deque)

    def allow(self, key: str, limit: int, window_sec: int) -> bool:
        now = time.time()
        with self._guard:
            q = self._buckets[key]
            while q and q[0] <= now - window_sec:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def record(self, key: str) -> None:
        with self._guard:
            self._buckets[key].append(time.time())

    def count(self, key: str, window_sec: int) -> int:
        now = time.time()
        with self._guard:
            q = self._buckets[key]
            while q and q[0] <= now - window_sec:
                q.popleft()
            return len(q)

    def clear(self, key: str) -> None:
        with self._guard:
            self._buckets.pop(key, None)

    def reset_all(self) -> None:
        with self._guard:
            self._buckets.clear()


_CREATE_LIMITER = SlidingWindowLimiter()
_UPLOAD_FAIL_LIMITER = SlidingWindowLimiter()
_QUALITY_FAIL_LIMITER = SlidingWindowLimiter()


def check_create_rate(device_id: str, account_id: str) -> Optional[str]:
    """返回拒绝原因码，或 None 表示允许。key 仅用脱敏哈希前缀，不存 token。"""
    dkey = f"dev:{_hash_id(device_id)}"
    akey = f"acct:{_hash_id(account_id)}"
    if not _CREATE_LIMITER.allow(dkey, DEVICE_CREATE_LIMIT, DEVICE_CREATE_WINDOW_SEC):
        return "rate_limited"
    if not _CREATE_LIMITER.allow(akey, ACCOUNT_CREATE_LIMIT, ACCOUNT_CREATE_WINDOW_SEC):
        # 回滚 device 刚写入的一次（简单：不回滚，略偏严可接受；或 clear last）
        return "rate_limited"
    return None


def check_upload_fail_rate(session_id: str) -> Optional[str]:
    key = f"upfail:{_hash_id(session_id)}"
    if not _UPLOAD_FAIL_LIMITER.allow(
        key, SESSION_UPLOAD_FAIL_LIMIT, SESSION_UPLOAD_FAIL_WINDOW_SEC
    ):
        return "rate_limited"
    return None


def record_quality_fail(session_id: str) -> Tuple[int, bool]:
    """返回 (当前窗口失败次数, 是否应中止并要求重新开始)。"""
    key = f"qfail:{_hash_id(session_id)}"
    _QUALITY_FAIL_LIMITER.record(key)
    n = _QUALITY_FAIL_LIMITER.count(key, SESSION_QUALITY_FAIL_WINDOW_SEC)
    return n, n >= SESSION_QUALITY_FAIL_LIMIT


def clear_session_limits(session_id: str) -> None:
    sid = _hash_id(session_id)
    _UPLOAD_FAIL_LIMITER.clear(f"upfail:{sid}")
    _QUALITY_FAIL_LIMITER.clear(f"qfail:{sid}")


def reset_limiters_for_tests() -> None:
    _CREATE_LIMITER.reset_all()
    _UPLOAD_FAIL_LIMITER.reset_all()
    _QUALITY_FAIL_LIMITER.reset_all()


def _hash_id(value: str) -> str:
    import hashlib

    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()[:16]
