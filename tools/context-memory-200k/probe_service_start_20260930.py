"""Read-only PM2 service startup times, without app configuration."""
import datetime
import json
import subprocess

rows = json.loads(subprocess.run(['pm2', 'jlist'], capture_output=True,
                                 text=True, check=True).stdout)
zone = datetime.timezone(datetime.timedelta(hours=8))
print(json.dumps({row['name']: {
    'status': row['pm2_env'].get('status'),
    'started_at_beijing': datetime.datetime.fromtimestamp(
        row['pm2_env'].get('pm_uptime', 0) / 1000, zone).isoformat(),
} for row in rows if row['name'] in ('manager-api', 'xiaozhi-server',
                                     'voiceprint-api')}, ensure_ascii=False))
