"""Read-only directory sync and cleanup aggregate after service patch."""
from collections import Counter
from pathlib import Path
import json
import re
import subprocess

pm = json.loads(subprocess.run(['pm2', 'jlist'], check=True,
                               capture_output=True, text=True).stdout)
service = next(row for row in pm if row['name'] == 'xiaozhi-server')
counts = Counter()
reasons = Counter()
timestamps = {}
for stream in ('pm_out_log_path', 'pm_err_log_path'):
    path = Path(service['pm2_env'].get(stream) or '')
    if not path.is_file():
        continue
    for line in path.read_bytes()[-16_000_000:].decode('utf-8', 'replace').splitlines():
        at = re.search(r'260930 (\d\d:\d\d:\d\d)', line)
        if not at or at.group(1) < '02:10:00':
            continue
        for label, marker in (
            ('directory_ready', 'directory_sync_ready'),
            ('directory_rejected', 'directory_sync_rejected'),
            ('directory_failed', 'directory_sync_failed'),
            ('voiceprint_enabled', '声纹识别已启用'),
            ('voiceprint_url_missing', '声纹识别URL未配置'),
            ('archive_rejected', '存档归属无效'),
        ):
            if marker in line:
                counts[label] += 1
                timestamps[label] = at.group(1)
        match = re.search(r'directory_sync_rejected reason=([a-z_]+)', line)
        if match:
            reasons[match.group(1)] += 1
print(json.dumps({'pm2_status': service['pm2_env'].get('status'),
                  'counts': dict(counts), 'last_times': timestamps,
                  'rejection_reasons': dict(reasons)}, ensure_ascii=False))
