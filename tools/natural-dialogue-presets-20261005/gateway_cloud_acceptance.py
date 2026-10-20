"""Run real Ali model through the candidate authenticated relay and isolated ledger."""
import json,os,re,subprocess
from pathlib import Path
import yaml
OUT=Path('/root/prjs/tmp/natural-dialogue-presets-20261005')
ROOT=OUT/'gateway-candidate'
source=(ROOT/'relay/controller/hardware_cloud_test.go').read_text()
source=source.replace('//go:build cloud_hardware','//go:build cloud_qwen38')
source=source.replace('TestHardwareRealAliRelayAndPaidLedger','TestQwen38RealAliRelayAndPaidLedger')
for unused in ('"encoding/base64"','"image"','"image/color"','"image/png"'):
 source=source.replace('\t'+unused+'\n','')
source=source.replace('qwen-plus','qwen3.8-flash')
source=source.replace('Type: channeltype.Ali,','Type: channeltype.OpenAICompatible,').replace('BaseURL: &nativeBase','BaseURL: &base').replace('\tnativeBase := "https://dashscope.aliyuncs.com"\n','')
start=source.index('\n\tfor _, tc := range')
end=source.index('\n\t\tstreaming :=',start)
source=source[:start]+'''\n\tfor _, tc := range []struct{ operation, question string }{{"native", "只说结果：一加一等于几？"}, {"native-stream", "只说结果：一加一等于几？"}, {"stream", "只说结果：一加一等于几？"}, {"llm", "只说结果：一加一等于几？"}, {"summary", "概括虚构原文：用户喜欢绿茶，周五买茶；助手答应提醒。不新增事实。"}, {"habit", "根据合成材料只返回JSON对象，键为habit和repeat_days：周一至周五每天七点读书，repeat_days=62。"}} {
        payload := map[string]interface{}{"model": "qwen3.8-flash", "messages": []map[string]string{{"role": "user", "content": tc.question}}, "max_tokens": 120, "temperature": 0, "enable_thinking": false, "preserve_thinking": false}
'''+source[end:]
source=source.replace('"native"','"compat"').replace('"native-stream"','"compat-stream"').replace('"real-native"','"real-compat"')
(ROOT/'relay/controller/qwen38_cloud_test.go').write_text(source)
db=yaml.safe_load(Path('/root/prjs/xiaozhi-esp32-server/main/manager-api/src/main/resources/application-dev.yml').read_text())['spring']['datasource']['druid']
m=re.search(r'mysql://([^:/]+)(?::(\d+))?/([^?]+)',db['url'])
env=dict(os.environ,MYSQL_PWD=str(db['password']))
query="SELECT `key` FROM one_api.channels WHERE id=8 AND status=1;"
p=subprocess.run(['mysql','--host='+m[1],'--port='+(m[2]or'3306'),'--user='+str(db['username']),'--batch','--raw','--skip-column-names',m[3]],input=query,env=env,capture_output=True,text=True,timeout=15)
assert p.returncode==0 and p.stdout.strip(),'credential_unavailable'
env.update(CLOUD_HW_TEST_KEY=p.stdout.strip(),CLOUD_HW_AUTHORIZED='1',CLOUD_HW_RESULT_FILE=str(OUT/'gateway-cloud-acceptance.json'))
subprocess.run(['/usr/local/go/bin/gofmt','-w','relay/controller/qwen38_cloud_test.go'],cwd=ROOT,check=True)
with (OUT/'gateway-cloud-acceptance.log').open('w') as log:
 result=subprocess.run(['/usr/local/go/bin/go','test','-tags','cloud_qwen38','./relay/controller','-run','TestQwen38RealAliRelayAndPaidLedger','-count=1','-v'],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=180)
print(json.dumps({'real_gateway_test_exit':result.returncode,'report_exists':(OUT/'gateway-cloud-acceptance.json').exists()}))
raise SystemExit(result.returncode)

