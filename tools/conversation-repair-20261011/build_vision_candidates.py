from pathlib import Path
import subprocess,os,json,xml.etree.ElementTree as ET
import shutil
from budget import Budget
S=Path(__file__).parent;D=S/'oneapi-candidate';b=Budget()
if not (D/'web/build').exists():shutil.copytree('/root/prjs/tmp/hardware-billing70-20261001/candidate/gateway/web/build',D/'web/build')
test='''package hardwarebilling
import "testing"
func TestVLPlusApprovedPrice(t *testing.T) {
 p,e:=BeijingPrice("qwen3-vl-plus","vision",false)
 if e!=nil || p.Model!="qwen3-vl-plus" || p.Region!="cn-beijing" || len(p.Tiers)!=3 {t.Fatal("unverified plus")}
 for _,tc:=range []struct{input int64;cost Exact}{{32000,"4/125"},{32001,"96003/2000000"},{128000,"24/125"},{128001,"384003/1000000"},{256000,"96/125"}} {
  zero:=int64(0);c,e:=p.Cost(Usage{Confirmed:true,Source:"upstream",UpstreamRequestID:"synthetic",Input:tc.input,Cached:&zero})
  if e!=nil || c!=tc.cost {t.Fatalf("input %d cost %s error %v",tc.input,c,e)}
 }
 if _,e:=BeijingPrice("qwen3-vl-plus","llm",false);e==nil {t.Fatal("operation scope widened")}
 old,e:=BeijingPrice("qwen3-vl-flash","vision",false);if e!=nil || old.Tiers[0].Input!="0.15" {t.Fatal("flash pricing changed")}
}
'''
(D/'hardwarebilling/vision_plus_test.go').write_text(test)
env=dict(os.environ,GOMAXPROCS='2',GOCACHE=str(S/'go-cache'),GOPROXY='https://goproxy.cn,direct')
cases=[b.reserve('case','vision-plus-price:'+str(i)) for i in range(8)]
with (S/'vision-plus-price.log').open('w') as out:r=subprocess.run(['/usr/local/go/bin/go','test','./hardwarebilling','-run','^TestVLPlusApprovedPrice$','-v'],cwd=D,env=env,stdout=out,stderr=subprocess.STDOUT,timeout=120)
for c in cases:b.finish(c,{'exit':r.returncode})
assert r.returncode==0,'price test failed'
case=b.reserve('case','oneapi-static-build')
with (S/'oneapi-static-build.log').open('w') as out:r=subprocess.run(['/usr/local/go/bin/go','build','-trimpath','-ldflags',"-s -w -linkmode external -extldflags -static",'-o',str(S/'one-api-candidate'),'./'],cwd=D,env=env,stdout=out,stderr=subprocess.STDOUT,timeout=600)
b.finish(case,{'exit':r.returncode});assert r.returncode==0
cases=[b.reserve('case','java-billing-policy:'+str(i)) for i in range(4)]
with (S/'java-billing-build.log').open('w') as out:r=subprocess.run(['mvn','-q','-Dtest=HardwareBillingPolicyTest','test','package'],cwd=S/'manager-api',stdout=out,stderr=subprocess.STDOUT,timeout=600)
for c in cases:b.finish(c,{'exit':r.returncode})
assert r.returncode==0
print('VISION_CANDIDATES_BUILT',b.report(),flush=True)
