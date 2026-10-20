"""设备语音人脸建档禁令：camera.face.register / camera.face.delete 不得写入 face-api。"""

from __future__ import annotations

from typing import Any, Optional

from plugins_func.register import Action, ActionResponse

FACE_REGISTER_BLOCK_MSG = (
    "人脸用户请在管理网页手动输入姓名并完成照片录入；设备语音不能创建或命名人脸。"
)

FACE_DELETE_BLOCK_MSG = (
    "已禁止通过设备语音按姓名删除人脸；请在管理网页按用户删除。"
)

_BLOCKED_REGISTER = {
    "camera.face.register",
    "camera_face_register",
    "self.camera.face.register",
    "self_camera_face_register",
}

_BLOCKED_DELETE = {
    "camera.face.delete",
    "camera_face_delete",
    "self.camera.face.delete",
    "self_camera_face_delete",
}


def normalize_tool_key(tool_name: str) -> str:
    return (tool_name or "").strip()


def maybe_intercept_face_enrollment_tool(
    tool_name: str, _arguments: Optional[dict] = None
) -> Optional[ActionResponse]:
    """若为语音建档/按名删除工具，返回拒绝响应；否则 None。"""
    name = normalize_tool_key(tool_name)
    if not name:
        return None
    # 同时匹配点号名与 sanitize 下划线名
    candidates = {name, name.replace(".", "_"), name.replace("_", ".")}
    if candidates & _BLOCKED_REGISTER:
        return ActionResponse(action=Action.RESPONSE, response=FACE_REGISTER_BLOCK_MSG)
    if candidates & _BLOCKED_DELETE:
        return ActionResponse(action=Action.RESPONSE, response=FACE_DELETE_BLOCK_MSG)
    # 宽松：任意含 face.register / face.delete 的 camera 工具
    lowered = name.lower().replace("-", ".")
    if "face.register" in lowered or "face_register" in lowered.replace(".", "_"):
        return ActionResponse(action=Action.RESPONSE, response=FACE_REGISTER_BLOCK_MSG)
    if "face.delete" in lowered or "face_delete" in lowered.replace(".", "_"):
        return ActionResponse(action=Action.RESPONSE, response=FACE_DELETE_BLOCK_MSG)
    return None
