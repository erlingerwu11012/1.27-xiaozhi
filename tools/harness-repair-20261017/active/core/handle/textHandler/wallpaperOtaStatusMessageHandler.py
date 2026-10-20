"""设备上行 wallpaper_ota_status → 上报 manager-api（中央真相源）→ 按中央结果回 wallpaper_ota_ack。

安全边界（上线前审计补强）：
- 设备身份严格取自连接 device_id，不信任 payload.device_id；
  任务归属（task_id + device_id）由 manager-api 中央校验，拒绝/异常时绝不发 ACK。
- success 先由 manager-api 原子落 completed，仅当返回 completed=true 才回 wallpaper_ota_ack。
- ACK 仅投递给该 device_id 的「当前有效 connection generation」，绝不发给已被取代的旧连接。
- ACK 发送失败在当前连接生命周期内有限重试；失败绝不回退中央 completed，也绝不重新下发 update_wallpaper。
- 本地 SQLite 仅作审计镜像（best-effort），不参与投递决策，可安全丢失/重建。
"""

import asyncio
import json
from typing import Any, Dict, Optional

from config.manage_api_client import ManageApiClient
from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType
from config.logger import setup_logging

TAG = __name__
logger = setup_logging()

# ACK 有限重试：只在当前连接生命周期内短间隔重试，绝不触发重新下发
ACK_MAX_RETRIES = 3
ACK_RETRY_DELAY_S = 0.2


class WallpaperOtaStatusMessageHandler(TextMessageHandler):
    """处理 type=wallpaper_ota_status 的进度/完成回执"""

    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.WALLPAPER_OTA_STATUS

    async def handle(self, conn, msg_json: Dict[str, Any]) -> None:
        device_id = conn.device_id
        session_id = getattr(conn, "session_id", None)
        correlation_id = getattr(conn, "correlation_id", None)
        if not device_id:
            conn.logger.bind(tag=TAG).warning(
                f"[update_wallpaper] status_reject connection_id={session_id} reason=no_device_id"
            )
            return

        task_id = msg_json.get("task_id")
        pack_id = msg_json.get("pack_id")
        phase = msg_json.get("phase")
        if not task_id or not pack_id or not phase:
            conn.logger.bind(tag=TAG).warning(
                f"[update_wallpaper] status_reject task_id={task_id} device_id={device_id} "
                f"connection_id={session_id} reason=missing_fields"
            )
            return

        progress = msg_json.get("progress", 0)
        error = msg_json.get("error")

        # 1) 中央权威：上报 manager-api ACK，获取中央最新状态与 completed 标志。
        #    task_id 不存在 / device_id 不匹配 / 非法状态倒退 均由 manager-api 拒绝并抛异常，
        #    此处 catch 后直接 return，绝不发 ACK。
        body = {
            "taskId": task_id,
            "packId": pack_id,
            "phase": phase,
            "progress": progress,
            "error": error,
        }
        try:
            client = ManageApiClient._instance
            if client is None:
                from config.manage_api_client import init_service

                init_service(conn.config)
                client = ManageApiClient._instance
            if client is None:
                conn.logger.bind(tag=TAG).error(
                    f"[update_wallpaper] central_ack_failed task_id={task_id} device_id={device_id} "
                    f"connection_id={session_id} reason=no_client"
                )
                return
            ack_result = await client.request(
                "POST",
                "wallpaper-packs/device/ack",
                json=body,
                headers={"X-Device-Id": device_id},
            )
        except Exception as e:
            # 中央未确认（含拒绝/不匹配/倒退），不得向设备回 wallpaper_ota_ack
            conn.logger.bind(tag=TAG).error(
                f"[update_wallpaper] central_ack_failed task_id={task_id} device_id={device_id} "
                f"connection_id={session_id} phase={phase} reason={e}"
            )
            return

        central_state = ack_result.get("state") if isinstance(ack_result, dict) else None
        central_completed = bool(ack_result.get("completed")) if isinstance(ack_result, dict) else False
        central_duplicate = bool(ack_result.get("duplicate")) if isinstance(ack_result, dict) else False
        attempt_count = ack_result.get("attemptCount") if isinstance(ack_result, dict) else None

        conn.logger.bind(tag=TAG).info(
            f"[update_wallpaper] status task_id={task_id} device_id={device_id} "
            f"connection_id={session_id} correlation_id={correlation_id} phase={phase} "
            f"central_state={central_state} completed={central_completed} "
            f"duplicate={central_duplicate} attempt_count={attempt_count}"
        )

        # 2) 本地审计镜像（best-effort，不影响决策；失败可安全忽略）
        try:
            from core.utils import wallpaper_ota_store

            if phase == "success":
                wallpaper_ota_store.mark_completed(
                    task_id=task_id, device_id=device_id, pack_id=pack_id
                )
            elif phase == "failed":
                wallpaper_ota_store.mark_failed(
                    task_id=task_id,
                    device_id=device_id,
                    pack_id=pack_id,
                    error_code=error,
                    last_error=error,
                )
            else:
                wallpaper_ota_store.mark_status(
                    task_id=task_id,
                    device_id=device_id,
                    pack_id=pack_id,
                    phase=phase,
                    progress=progress,
                )
        except Exception as mirror_err:
            conn.logger.bind(tag=TAG).debug(
                f"[update_wallpaper] local_mirror_failed task_id={task_id} device_id={device_id} "
                f"connection_id={session_id} reason={mirror_err}"
            )

        # 3) 仅当中央 completed 落库成功后，才向设备回 wallpaper_ota_ack
        if phase != "success":
            return
        if not central_completed:
            conn.logger.bind(tag=TAG).warning(
                f"[update_wallpaper] ack_skipped task_id={task_id} device_id={device_id} "
                f"connection_id={session_id} central_state={central_state} reason=not_completed"
            )
            return

        ack = {
            "type": "wallpaper_ota_ack",
            "task_id": task_id,
            "status": "completed",
        }
        target = self._resolve_ack_target(conn, device_id)
        if target is None or getattr(target, "websocket", None) is None:
            conn.logger.bind(tag=TAG).warning(
                f"[update_wallpaper] ack_dropped task_id={task_id} device_id={device_id} "
                f"connection_id={session_id} reason=no_current_connection"
            )
            return
        target_session_id = getattr(target, "session_id", None)
        sent = await self._send_ack_with_retry(
            conn, target, ack, task_id, device_id, session_id, target_session_id, central_duplicate
        )
        if not sent:
            # 只记录失败；中央已 completed，绝不回退、绝不重新下发 update_wallpaper。
            conn.logger.bind(tag=TAG).error(
                f"[update_wallpaper] ack_failed task_id={task_id} device_id={device_id} "
                f"connection_id={session_id} target_connection_id={target_session_id} "
                f"reason=send_failed_after_retries state=completed(kept)"
            )

    def _resolve_ack_target(self, conn, device_id: str):
        """解析 ACK 目标：仅投递给该 device_id 的当前有效 generation。

        旧连接即使仍存活也不得接收 ACK；无当前有效连接时返回 None（不退回发起连接）。
        """
        server = getattr(conn, "server", None)
        if server is not None:
            cur = getattr(server, "_current_connection", None)
            if callable(cur):
                current = cur(device_id)
                if current is not None and getattr(current, "websocket", None) is not None:
                    return current
            return None
        # 无 server（单元测试直连 handler）：仅当本连接仍有 websocket 时回退自身
        if getattr(conn, "websocket", None) is not None:
            return conn
        return None

    async def _send_ack_with_retry(
        self,
        conn,
        target,
        ack: Dict[str, Any],
        task_id: str,
        device_id: str,
        session_id: Optional[str],
        target_session_id: Optional[str],
        duplicate: bool,
    ) -> bool:
        raw = json.dumps(ack, ensure_ascii=False)
        last_err = None
        for attempt in range(1, ACK_MAX_RETRIES + 1):
            try:
                from core.utils.device_outbound import guarded_ws_send

                ok = await guarded_ws_send(
                    target,
                    raw,
                    command="wallpaper_ota_ack",
                    msg_type="wallpaper_ota_ack",
                    task_id=task_id,
                )
                if not ok:
                    last_err = RuntimeError("not_current_connection")
                    break
                conn.logger.bind(tag=TAG).info(
                    f"[update_wallpaper] ack task_id={task_id} device_id={device_id} "
                    f"connection_id={session_id} target_connection_id={target_session_id} "
                    f"status=completed duplicate={duplicate} attempt={attempt} result=sent"
                )
                return True
            except Exception as e:  # noqa: BLE001
                last_err = e
                if attempt < ACK_MAX_RETRIES:
                    await asyncio.sleep(ACK_RETRY_DELAY_S)
        conn.logger.bind(tag=TAG).warning(
            f"[update_wallpaper] ack_retry_exhausted task_id={task_id} device_id={device_id} "
            f"connection_id={session_id} target_connection_id={target_session_id} reason={last_err}"
        )
        return False
