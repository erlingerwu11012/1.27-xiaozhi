"""Explicitly retired maintenance endpoints, including old device catalogs."""
from core.utils.util import sanitize_tool_name

RETIRED_TOOL_NAMES = frozenset(['self_get_system_info', 'self_reboot', 'self_screen_get_info', 'self_screen_set_render_mode', 'self_screen_set_render_options', 'self_screen_get_render_status'])

def is_retired_tool(name: str) -> bool:
    return sanitize_tool_name(name or "") in RETIRED_TOOL_NAMES
