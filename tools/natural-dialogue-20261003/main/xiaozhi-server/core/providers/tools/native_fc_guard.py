"""Plain response text is never a tool transport in the controlled pipeline."""
from core.utils.operation_control import enabled
from .tool_routing_config import get_native_fc_only_config


def should_reject_text_tool_call(conn):
    cfg = get_native_fc_only_config(getattr(conn, "config", {}))
    return enabled(conn) or (cfg["enabled"] and cfg["reject_text_tool_call"])
