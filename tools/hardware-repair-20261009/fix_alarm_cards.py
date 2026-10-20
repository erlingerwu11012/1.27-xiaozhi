from pathlib import Path
p=Path('main/mcp_tools/mcp_tools_alarm.cc');s=p.read_text().replace('            if (id < 0) return McpError{"闹钟已满，最多8个"};','            if (id < 0) return McpError{"闹钟保存失败或数量已满，请检查存储状态", "storage_write_failed"};\n            ReminderCoordinator::GetInstance().InvalidateInformation("闹钟列表", creator);');p.write_text(s)
