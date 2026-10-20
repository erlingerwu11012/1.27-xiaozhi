from pathlib import Path
R=Path('tools/hardware-repair-20261009');p=R/'package_firmware.py';s=p.read_text(encoding='utf-8')
s=s.replace("readme=f'''#", "readme=f'''交付状态：候选固件已编译，尚未烧录。本轮服务端未通过完整上线门槛，正式域名尚未部署此批修改。建议待配套服务端完成验收后再使用。自动化结果不是实机验收。\n\n#")
p.write_text(s,encoding='utf-8')
