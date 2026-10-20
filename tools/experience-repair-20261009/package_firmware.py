from pathlib import Path
import sys
root=Path(__file__).parent
src=Path('tools/nvs-habit-renewal-20261007/package_firmware.py').read_text(encoding='utf-8-sig')
src=src.replace("stage=Path(__file__).parent;build=Path('build-nvs64');out=Path('releases/nvs64-habit-renewal-20261007')", "stage=Path('tools/nvs-habit-renewal-20261007');build=Path('build-experience-repair-20261009');out=Path('releases/experience-repair-20261009')")
src=src.replace('NVS64KB、习惯同步固件','对话体验修复固件（保留64KB NVS布局）')
src=src.replace('本包已完整编译、通过主机故障注入和迁移算法测试。','本包已完整编译，视觉凭据生命周期真实源码主机测试通过；升级脚本沿用已验证的保留数据迁移逻辑。')
src=src.replace("(stage/'firmware-package-result.json')", "(Path('tools/experience-repair-20261009')/'firmware-package-result.json')")
src=src.replace("(out/'README.md').write_text(readme,encoding='utf-8')","readme="+repr('交付状态：服务端已通过最终模拟验收，并于2026年10月9日上线 www.realecho.cn，完成至少30分钟上线观察。此包是待用户烧录的固件；服务端上线不等于硬件验收通过。\n\n本轮固件修复包括视觉凭据未就绪原因的明确反馈，以及在身份权限通过后，将当前卡片绑定到新的有效音频会话。保留既有64KB NVS与用户数据分区布局。本编译也包含工作区此前已有的 application.cc TTS中断改动；本轮未重置其他工作区成果。未刷机，未证明真实摄像头、存储、显示和扬声器效果。\n\n默认使用 Upgrade-Preserve.ps1，先备份校验；不要把 new-device-reset 镜像作为普通升级使用。\n\n')+"+readme\n(out/'README.md').write_text(readme,encoding='utf-8')")
sys.path.insert(0,str(Path('tools/nvs-habit-renewal-20261007').resolve()));exec(compile(src,'package_experience_firmware','exec'))
