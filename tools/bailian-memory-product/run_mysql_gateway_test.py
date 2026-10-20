"""Run real MySQL transaction tests in a new synthetic-only schema."""
import json
import os
import secrets
import subprocess
from pathlib import Path

database='bailian_memory_wallet_test_'+secrets.token_hex(6)
mysql=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
subprocess.run(mysql,input='CREATE DATABASE `'+database+'` CHARACTER SET utf8mb4;',text=True,capture_output=True,check=True)
password=subprocess.run(['docker','exec','xiaozhi-esp32-server-db','sh','-c','printf "%s" "$MYSQL_ROOT_PASSWORD"'],capture_output=True,text=True,check=True).stdout
environment=dict(os.environ,GOPROXY='off',MEMORY_MYSQL_TEST_DATABASE=database,MEMORY_MYSQL_TEST_PASSWORD=password)
log='/tmp/bailian-memory-mysql-ledger.log'
with open(log,'w') as output:
    result=subprocess.run(['/usr/local/go/bin/go','test','./bailian','-run','TestMemoryMySQLConcurrentWalletPrecision','-count=1','-v'],cwd='/root/prjs/tmp/one-api-bailian-memory-product',env=environment,stdout=output,stderr=subprocess.STDOUT)
report={'passed':result.returncode==0,'database':database,'synthetic_only':True,'log':log}
Path('/tmp/bailian-memory-mysql-ledger-result.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report));print(Path(log).read_text()[-2500:]);raise SystemExit(result.returncode)
