from pathlib import Path
R=Path(__file__).parent
p=R/'candidate/core/utils/tool_harness/presentation.py';s=p.read_text(encoding='utf-8');s=s.replace("    return text.strip()\n", "    return re.sub(r'。{2,}','。',text).strip()\n",1);p.write_text(s,encoding='utf-8')
p=R/'package_firmware.py';s=p.read_text(encoding='utf-8-sig');needle="sys.path.insert(0,str(Path('tools/nvs-habit-renewal-20261007').resolve()));exec";notice='候选交付状态：服务端尚未完成最终全量验收，未上线。\n\n本轮固件修复包括视觉凭据未就绪原因的明确反馈，以及在身份权限通过后，将当前卡片绑定到新的有效音频会话。保留既有64KB NVS与用户数据分区布局。本编译也包含工作区此前已有的 application.cc TTS中断改动；本轮未重置其他工作区成果。未刷机，未证明真实摄像头、存储、显示和扬声器效果。\n\n默认使用 Upgrade-Preserve.ps1，先备份校验；不要把 new-device-reset 镜像作为普通升级使用。\n\n'
patch="src=src.replace(\"(out/'README.md').write_text(readme,encoding='utf-8')\",\"readme=\"+repr("+repr(notice)+")+\"+readme\\n(out/'README.md').write_text(readme,encoding='utf-8')\")\n"
assert needle in s;s=s.replace(needle,patch+needle);p.write_text(s,encoding='utf-8')
