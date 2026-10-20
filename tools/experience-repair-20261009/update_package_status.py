from pathlib import Path
p=Path('tools/experience-repair-20261009/package_firmware.py');s=p.read_text(encoding='utf-8-sig');s=s.replace('候选交付状态：服务端尚未完成最终全量验收，未上线。','交付状态：服务端已通过最终模拟验收，并于2026年10月9日上线 www.realecho.cn，完成至少30分钟上线观察。此包是待用户烧录的固件；服务端上线不等于硬件验收通过。');p.write_text(s,encoding='utf-8')
