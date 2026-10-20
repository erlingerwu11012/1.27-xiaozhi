"""同设备 Spine / Wallpaper 视觉 OTA 重连串行投递编排。"""

import asyncio

TAG = __name__


async def deliver_pending_visual_ota(conn) -> None:
    """设备重连后串行投递视觉 OTA：Spine 优先，同一时刻仅下发一类。"""
    try:
        await asyncio.sleep(1.0)
        if conn._is_stale_connection():
            conn.logger.bind(tag=TAG).info(
                f"[visual_ota] skip device_id={conn.device_id} "
                f"session_id={conn.session_id} reason=stale_before_claim"
            )
            return
        spine_sent = await conn._deliver_pending_spine_role(_skip_initial_sleep=True)
        if spine_sent:
            return
        await conn._deliver_pending_wallpaper(_skip_initial_sleep=True)
    except Exception as e:
        conn.logger.bind(tag=TAG).warning(
            f"[visual_ota] deliver_failed device_id={conn.device_id} reason={e}"
        )
