from pathlib import Path
import subprocess,json,collections
root=Path.cwd()
files=subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z']).decode().split('\0');groups=collections.defaultdict(lambda:[0,0])
for n in filter(None,files):
 p=root/n;k='/'.join(n.split('/')[:2]);groups[k][0]+=1;groups[k][1]+=p.stat().st_size
print(json.dumps(groups,indent=2))
p=root/'main/mcp_tools/mcp_tools_device.cc'
s=p.read_text(encoding='utf-8');s=s[:s.index('void RegisterDeviceUserTools(')]+'''void RegisterDeviceUserTools(McpServer&) {
    // Maintenance MCP endpoints are intentionally unavailable. Internal reboot
    // and renderer configuration remain available to the firmware itself.
}
''';s=s.replace('#include "application.h"\n','').replace('#include "display/home_render_config.h"\n','');p.write_text(s,encoding='utf-8')
