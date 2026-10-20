from pathlib import Path
R=Path(__file__).parent
p=R/'candidate/core/utils/unified_recipient_resolver.py';s=p.read_text(encoding='utf-8-sig').replace('显式用户 > 当前声纹用户 > all','显式接收人 > 本轮不可变身份；身份未知须澄清');s=s.replace('    requested_id = str(recipient_user_id or "").strip()','    if normalize_display_name(selector) in {"all","所有人","大家","公共","公共提醒"}:return _all_resolution()\n    requested_id = str(recipient_user_id or "").strip()');p.write_text(s,encoding='utf-8')
p=R/'test_lifecycle.py';s=p.read_text(encoding='utf-8-sig').replace("user_text='公共提醒喝水'","user_text='公共提醒喝水',selector='all'");p.write_text(s,encoding='utf-8')
