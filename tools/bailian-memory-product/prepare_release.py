"""Build and preserve a bounded recovery set. Does not publish services."""
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

os.umask(0o077)
production=Path('/root/prjs/xiaozhi-esp32-server')
candidate=Path('/root/prjs/tmp/bailian-memory-product')
gateway=Path('/root/prjs/tmp/one-api-bailian-memory-product')
release=Path('/root/prjs/tmp/bailian-memory-release-20260929')
release.mkdir(exist_ok=True)
manifest=json.loads(Path('/tmp/bailian-memory-delivery-manifest.json').read_text())
def run(command,cwd,log):
    with (release/log).open('w') as output:
        result=subprocess.run(command,cwd=cwd,stdout=output,stderr=subprocess.STDOUT)
    print(json.dumps({'step':log,'exit':result.returncode}),flush=True)
    if result.returncode:raise RuntimeError('release preparation failed: '+log)

# Refuse to overwrite a file that somebody changed after our baseline.
for component,root in [('server',production),('gateway',Path('/root/prjs/one-api-bailian'))]:
    for name,base in manifest[component]['base_files'].items():
        file=root/name;digest=hashlib.sha256(file.read_bytes()).hexdigest() if file.exists() else None
        if digest not in (base,manifest[component]['files'][name]):raise RuntimeError('concurrent source change: '+component+'/'+name)
    backup=release/(component+'-source-before.tar.gz')
    if not backup.exists():
        with tarfile.open(backup,'w:gz') as archive:
            for name in manifest[component]['files']:
                if (root/name).exists():archive.add(root/name,arcname=name)
    shutil.copy2('/tmp/'+component+'-overlay.tar.gz',release/(component+'-overlay.tar.gz'))

for source,name in [('/opt/one-api-bailian/one-api-bailian','gateway-before'),('/etc/one-api-bailian.env','gateway-before.env'),
    (str(production/'main/manager-api/target/xiaozhi-esp32-api.jar'),'manager-api-before.jar'),
    (str(production/'secrets/start-manager-api.sh'),'start-manager-api-before.sh')]:
    target=release/name
    if not target.exists():shutil.copy2(source,target);target.chmod(0o600)
if not (release/'frontend-before.tar.gz').exists():
    run(['tar','-czf',str(release/'frontend-before.tar.gz'),'-C','/var/www/realecho-www','.'],release,'frontend-backup.log')
inspect=json.loads(subprocess.run(['docker','inspect','face-api'],capture_output=True,text=True,check=True).stdout)[0]
if not (release/'face-before.json').exists():(release/'face-before.json').write_text(json.dumps(inspect))
mysql=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
schema=subprocess.run(['docker','exec','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump --user=root --no-data --skip-comments --set-gtid-purged=OFF xiaozhi_esp32_server'],capture_output=True,text=True,check=True).stdout
(release/'product-schema-before.sql').write_text(schema)
# No memory, profile, transcript, summary or behavior bodies enter recovery files.
balances=subprocess.run(mysql,input='SELECT id,quota,used_quota,request_count FROM one_api.users; SELECT id,user_id,remain_quota,used_quota FROM one_api.tokens;',capture_output=True,text=True,check=True).stdout
(release/'wallet-balances-before.tsv').write_text(balances)
ledger=subprocess.run(['docker','exec','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysqldump --user=root --single-transaction --no-create-info --skip-comments --set-gtid-purged=OFF one_api bailian_bills bailian_audits bailian_admin_ops'],capture_output=True,text=True,check=True).stdout
(release/'gateway-ledger-before.sql').write_text(ledger)

run(['mvn','-o','package','-Dmaven.test.skip=true'],candidate/'main/manager-api','java-build.log')
run(['/usr/local/go/bin/go','build','-o',str(release/'one-api-bailian'), './cmd/bailian'],gateway,'gateway-build.log')
run(['npm','run','build'],candidate/'main/manager-web','web-build.log')
dockerfile=release/'Dockerfile.face'
run(['docker','tag',inspect['Image'],'face-memory-baseline:20260929'],release,'face-baseline-tag.log')
dockerfile.write_text('FROM face-memory-baseline:20260929\nCOPY app /app/app\n')
run(['docker','build','--pull=false','-t','face-api-memory-product:20260929','-f',str(dockerfile),str(candidate/'main/face-api')],release,'face-build.log')
shutil.copy2(candidate/'main/manager-api/target/xiaozhi-esp32-api.jar',release/'manager-api.jar')
run(['tar','-czf',str(release/'frontend.tar.gz'),'-C',str(candidate/'main/manager-web/dist'),'.'],release,'frontend-package.log')
report={'prepared':True,'published':False,'release':str(release),'artifacts':{name:hashlib.sha256((release/name).read_bytes()).hexdigest() for name in ['manager-api.jar','one-api-bailian','frontend.tar.gz','server-overlay.tar.gz','gateway-overlay.tar.gz']}}
(release/'prepared.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
