from pathlib import Path
p=Path(__file__).parent
names=['self_get_system_info','self_reboot','self_screen_get_info','self_screen_set_render_mode','self_screen_set_render_options','self_screen_get_render_status']
(p/'retired_tools.py').write_text('''"""Explicitly retired maintenance endpoints, including old device catalogs."""
from core.utils.util import sanitize_tool_name

RETIRED_TOOL_NAMES = frozenset('''+repr(names)+''')

def is_retired_tool(name: str) -> bool:
    return sanitize_tool_name(name or "") in RETIRED_TOOL_NAMES
''',encoding='utf-8')
f=p/'unified_tool_manager.py';s=f.read_text(encoding='utf-8');s=s.replace('from .base import ToolType, ToolDefinition, ToolExecutor','from .base import ToolType, ToolDefinition, ToolExecutor\nfrom .retired_tools import is_retired_tool')
s=s.replace('for name, definition in tools.items():\n','for name, definition in tools.items():\n                    if is_retired_tool(name):\n                        continue\n',1)
s=s.replace('        """执行工具调用"""\n        try:', '''        """执行工具调用"""
        if is_retired_tool(tool_name):
            return ActionResponse(action=Action.ERROR, response="这项维护工具已停用，这次没有执行。")
        try:''',1)
s=s.replace('stats[tool_type.value] = len(tools)','stats[tool_type.value] = sum(not is_retired_tool(name) for name in tools)')
assert 'if is_retired_tool(tool_name):' in s;f.write_text(s,encoding='utf-8')
f=p/'mcp_handler.py';s=f.read_text(encoding='utf-8');needle="async def call_mcp_tool(conn, mcp_client, tool_name, args='{}', timeout=30):\n";assert needle in s;s=s.replace(needle,needle+'''    from core.providers.tools.retired_tools import is_retired_tool
    if is_retired_tool(tool_name):
        raise ValueError("这项维护工具已停用，禁止下发。")
''');f.write_text(s,encoding='utf-8')
