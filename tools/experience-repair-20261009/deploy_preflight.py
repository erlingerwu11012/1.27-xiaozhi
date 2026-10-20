from pathlib import Path
import json,hashlib,subprocess,re,socket
S=Path('/root/prjs/tmp/experience-repair-20261009');R=Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server');names=json.loads((S/'changed-files.json').read_text());base=json.loads((S/'baseline.json').read_text());sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
drift=[n for n,h in base.items() if n.endswith('.py') and n not in names and not n.startswith('test/') and (not(R/n).exists() or sha(R/n)!=h)];changed=[n for n in names if (sha(R/n) if (R/n).exists() else None)!=base.get(n)]
w=Path('/root/prjs/xiaozhi-esp32-server/secrets/start-manager-api.sh').read_text();shape=len(re.findall(r'exec java -jar target/xiaozhi-esp32-api\.jar',w))==1
print(json.dumps({'unrelated_drift':drift,'changed_file_drift':changed,'manager_start_shape':shape,'release_state_exists':Path('/root/prjs/releases/experience-repair-20261009/deployment-state.json').exists(),'nginx_compat_exists':Path('/etc/nginx/conf.d/experience-manager-compat.conf').exists()}))
