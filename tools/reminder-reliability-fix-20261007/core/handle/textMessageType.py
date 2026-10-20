from enum import Enum


class TextMessageType(Enum):
    """消息类型枚举"""
    HELLO = "hello"
    ABORT = "abort"
    LISTEN = "listen"
    IOT = "iot"
    MCP = "mcp"
    SERVER = "server"
    PING = "ping"
    SPINE_OTA_STATUS = "spine_ota_status"
    WALLPAPER_OTA_STATUS = "wallpaper_ota_status"
    REMINDER_VOICE_REQUEST = "reminder_voice_request"
    REMINDER_VOICE_ASSET = "reminder_voice_asset"
    REMINDER_VOICE_ERROR = "reminder_voice_error"
    REMINDER_EVENT = "reminder_event"
    IDENTITY_CONTEXT = "identity_context"
