from pathlib import Path
p=Path('main/mcp_tools/mcp_tools_camera.cc');s=p.read_text();old='                throw;\n            \n        };';assert old in s;s=s.replace(old,'                throw;\n            }\n        };');p.write_text(s)
