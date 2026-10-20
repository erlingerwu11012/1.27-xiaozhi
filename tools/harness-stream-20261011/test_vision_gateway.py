"""Real vision through an isolated One-API relay and isolated paid ledger."""
import os,json,subprocess,re,shutil,pymysql
from pathlib import Path
from budget import Budget
S=Path(__file__).parent;D=S/'oneapi-candidate'
if not D.exists():shutil.copytree('/root/prjs/one-api-bailian',D,ignore=shutil.ignore_patterns('.git','node_modules','*.exe','*-linux'))
p=D/'relay/controller/hardware_cloud_test.go';text=p.read_text()
text,n=re.subn(r'for _, tc := range \[\]struct\{ operation, question string \}\{.*?\} \{','for _, tc := range []struct{ operation, question string }{{"vision", "这张合成图片是什么颜色？只说颜色。"}} {',text,count=1,flags=re.S)
assert n==1;p.write_text(text)
text=p.read_text().replace('t.Fatalf("operation=%s status=%d", tc.operation, out.Code)', 't.Fatalf("operation=%s status=%d code=%s", tc.operation, out.Code, out.Body.String())')
text=text.replace('qwen3-vl-flash','qwen3-vl-plus')
p.write_text(text)
shutil.copy2(S/'oneapi/hardwarebilling/pricing.go',D/'hardwarebilling/pricing.go')
env=dict(os.environ,GOMAXPROCS='2',GOCACHE=str(S/'go-cache'),GOPROXY='https://goproxy.cn,direct')
case=Budget().reserve('case','isolated-oneapi-vision-compile')
with (S/'go-vision-build.log').open('w') as out:r=subprocess.run(['/usr/local/go/bin/go','test','-c','-tags','cloud_hardware','-o',str(S/'oneapi-vision.test'),'./relay/controller'],cwd=D,env=env,stdout=out,stderr=subprocess.STDOUT,timeout=900)
Budget().finish(case,{'exit':r.returncode});print('BUILD',r.returncode,flush=True)
if r.returncode:raise SystemExit(r.returncode)
meta=json.loads(subprocess.check_output(['docker','inspect','one-api']))[0];settings=dict(x.split('=',1) for x in meta['Config']['Env'] if '=' in x)
auth,_,tail=settings['SQL_DSN'].rpartition('@tcp(');host,_,tail=tail.partition(')/');user,_,password=auth.partition(':');hostname,_,port=host.partition(':')
with pymysql.connect(host=hostname,port=int(port or 3306),user=user,password=password,database=tail.split('?')[0]) as d:
 with d.cursor() as c:
  c.execute('SELECT id,`key` FROM channels WHERE id IN(8,9)');keys=dict(c.fetchall())
env.update(CLOUD_HW_AUTHORIZED='1',CLOUD_HW_TEST_KEY=keys[8],CLOUD_HW_VISION_KEY=keys[9],CLOUD_HW_RESULT_FILE=str(S/'isolated-vision-gateway-result.json'))
b=Budget();case=b.reserve('case','isolated-oneapi-real-vision');charge=b.reserve('vision','isolated-oneapi-compatible-vision')
with (S/'go-vision-test.log').open('w') as out:r=subprocess.run([str(S/'oneapi-vision.test'),'-test.run','^TestHardwareRealAliRelayAndPaidLedger$','-test.v'],cwd=D,env=env,stdout=out,stderr=subprocess.STDOUT,timeout=90)
result={'exit':r.returncode,'isolated_gateway':True,'isolated_business_and_billing_db':True}
b.finish(case,result);b.finish(charge,result);print('VISION_GATEWAY',result,flush=True)
raise SystemExit(r.returncode)
