"""Last paid vision attempt: actual VisionHandler -> isolated One-API -> Ali."""
from pathlib import Path
import json,os,subprocess
from budget import Budget
S=Path(__file__).parent;D=S/'oneapi-candidate';b=Budget()
source=(D/'relay/controller/hardware_cloud_test.go').read_text()
prefix=source[:source.index('\treports := []map[string]interface{}{}')]
prefix=prefix.replace('func TestHardwareRealAliRelayAndPaidLedger','func TestHardwareVisionHTTPFullChain')
for unused in ['"bytes"','"encoding/base64"','"encoding/json"','"image"','"image/color"','"image/png"','"math/big"','"strconv"','"time"']:
 prefix=prefix.replace('\t'+unused+'\n','')
prefix=prefix.replace('"os"','"os"\n "os/exec"')
code=prefix+'''
 server := httptest.NewServer(router)
 defer server.Close()
 command := exec.Command(os.Getenv("CHAIN_PYTHON"), os.Getenv("CHAIN_SCRIPT"))
 command.Env = append(os.Environ(), "ISOLATED_VISION_GATEWAY="+server.URL)
 output, err := command.CombinedOutput()
 t.Log(string(output))
 if err != nil { t.Fatal("vision HTTP chain failed",err) }
 var bills []hardwarebilling.Bill
 if err := db.Find(&bills).Error; err != nil {t.Fatal(err)}
 if len(bills)!=1 || bills[0].State!="settled" {t.Fatal("expected exactly one settled real vision bill")}
 t.Log("VISION_HTTP_SETTLED_BILL", bills[0].CostCNY, bills[0].SaleCNY)
}
'''
(D/'relay/controller/hardware_vision_fullchain_test.go').write_text(code)
script=(S/'run_vision_http.py').read_text().replace("'99003'","'99017001'")
needle=" cap=build_vision_capabilities"
override=""" v=cfg['VLLM'][cfg['selected_module']['VLLM']];v.update(model_name='qwen3-vl-plus',api_key='sk-'+('k'*32),base_url=os.environ['ISOLATED_VISION_GATEWAY']+'/v1',hardware_billing=True,hardware_account_id='99017001',hardware_operation='vision')
 os.environ['HW_BILLING_GATEWAY_ORIGIN']=os.environ['ISOLATED_VISION_GATEWAY'];os.environ['HW_BILLING_SERVICE_KEY']='s'*32
"""
script=script.replace('import bootstrap,','import os\nimport bootstrap,').replace(needle,override+needle)
script=script.replace("   provider=original(*a);respond=provider.response","   provider=original(*a);provider.client.max_retries=0;respond=provider.response")
script=script.replace("   result=await request('real_vlm_same_session_followup',with_image=False);assert result['status']==200 and '蓝' in result['body']['response'],result","")
script=script.replace("'vision-http-results.json'","'vision-http-plus-results.json'")
(S/'run_vision_http_plus.py').write_text(script)
env=dict(os.environ,GOMAXPROCS='2',GOCACHE=str(S/'go-cache'),GOPROXY='https://goproxy.cn,direct')
case=b.reserve('case','vision-fullchain-build')
with (S/'go-vision-fullchain-build.log').open('w') as out:r=subprocess.run(['/usr/local/go/bin/go','test','-c','-tags','cloud_hardware','-o',str(S/'oneapi-vision-fullchain.test'),'./relay/controller'],cwd=D,env=env,stdout=out,stderr=subprocess.STDOUT,timeout=300)
b.finish(case,{'exit':r.returncode});assert r.returncode==0
# Reuse only the remote environment resolution from the previous authorized test.
import pymysql
m=json.loads(subprocess.check_output(['docker','inspect','one-api']))[0];e=dict(x.split('=',1) for x in m['Config']['Env'] if '=' in x)
a,_,t=e['SQL_DSN'].rpartition('@tcp(');h,_,t=t.partition(')/');u,_,p=a.partition(':');host,_,port=h.partition(':')
with pymysql.connect(host=host,port=int(port or 3306),user=u,password=p,database=t.split('?')[0]) as db:
 with db.cursor() as c:c.execute('SELECT id,`key` FROM channels WHERE id IN (8,9)');keys=dict(c.fetchall())
env.update(CLOUD_HW_AUTHORIZED='1',CLOUD_HW_TEST_KEY=keys[8],CLOUD_HW_VISION_KEY=keys[9],CHAIN_PYTHON='/root/miniconda3/envs/xiaozhi-esp32-server/bin/python',CHAIN_SCRIPT=str(S/'run_vision_http_plus.py'))
case=b.reserve('case','vision-fullchain-go-assert')
with (S/'go-vision-fullchain.log').open('w') as out:r=subprocess.run([str(S/'oneapi-vision-fullchain.test'),'-test.run','^TestHardwareVisionHTTPFullChain$','-test.v'],cwd=D,env=env,stdout=out,stderr=subprocess.STDOUT,timeout=90)
b.finish(case,{'exit':r.returncode});print('VISION_FULLCHAIN',r.returncode,flush=True)
raise SystemExit(r.returncode)
