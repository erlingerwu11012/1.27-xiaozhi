"""Read-only money/usage audit; never reads prompts, audio, portraits or keys."""
from pathlib import Path
from fractions import Fraction as F
import subprocess,json,hashlib,time,shutil
ROOT=Path('/root/prjs/tmp/hardware-billing70-20261001')
MYSQL=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def sql(q):return subprocess.run(MYSQL,input=q,text=True,capture_output=True,check=True).stdout.strip()
def exact_cost(p,u):
    assert u['confirmed'] and u['source']=='upstream' and u['upstream_request_id']
    if p['unit']!='tokens':return F(u['units'])*F(p['unit_cny'])
    i,o,c=u['input_tokens'],u['output_tokens'],u['cached_tokens'];assert 0<=c<=i and o>=0
    t=next(t for t in p['tiers'] if i<=t['max_input'])
    return (F(i-c)*F(t['input_per_million'])+F(o)*F(t['output_per_million'])+F(c)*F(t['cached_per_million']))/1_000_000
records=sql("SELECT price_json,usage_json,cost_cny,sale_cny,allocations FROM one_api.hardware_billing_bill WHERE state IN ('settled','refunded');").splitlines()
checked=0
for line in records:
    p,u,cost,sale,a=line.split('\t');p,u,a=json.loads(p),json.loads(u),json.loads(a)
    cost,sale=F(cost),F(sale);assert cost==exact_cost(p,u) and sale==cost/F('0.30')
    for item in a:
        if item['kind']=='paid':
            rate=sql("SELECT cny_per_point FROM one_api.hardware_billing_lot WHERE id='"+item['lot_id'].replace("'","''")+"';")
            assert F(item['points'])*F(rate)==F(item['sale_cny'])
        else:assert item['kind']=='legacy' and F(item['sale_cny'])==0
    checked+=1
states=sql('SELECT state,COUNT(*) FROM one_api.hardware_billing_bill GROUP BY state;')
old=sql("SELECT x.state,COUNT(*),SUM(x.held),SUM(x.charged) FROM one_api.bailian_bills x JOIN xiaozhi_esp32_server.sys_user_oneapi_binding b ON b.oneapi_user_id=x.user_id WHERE x.state='manual_review' GROUP BY x.state;")
assert old=='manual_review\t10\t6777\t0'
assert sql("SELECT COUNT(*) FROM one_api.bailian_bills WHERE created_at>=1790852532;")=='0'
packages=sql('SELECT id,amount_cents,quota_points FROM xiaozhi_esp32_server.pay_package WHERE id IN (1,2,3) ORDER BY id;')
assert packages.splitlines()==['1\t100\t100','2\t2900\t50000','3\t9900\t200000']
health={}
for name,url in [('native','http://127.0.0.1:3011/healthz'),('gateway','https://api.realecho.cn/api/status'),('frontend','https://www.realecho.cn'),('manager','http://127.0.0.1:8002/xiaozhi/user/pub-config')]:
    r=subprocess.run(['curl','-s','--max-time','5','-o','/dev/null','-w','%{http_code}',url],capture_output=True,text=True);health[name]=r.stdout;assert r.stdout=='200'
assets={}
for path in ['candidate/one-api-hardware70','candidate/one-api-bailian-hardware70','candidate/server/main/manager-api/target/xiaozhi-esp32-api.jar','candidate/server/main/manager-web/dist/index.html']:
    assets[path]=hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
frontend_ok=hashlib.sha256(Path('/var/www/realecho-www/index.html').read_bytes()).hexdigest()==assets['candidate/server/main/manager-web/dist/index.html'];assert frontend_ok
result={'passed':True,'checked_settled_or_refunded_bills':checked,'states':states,'legacy_pending_bound_aggregate':old,'packages_verified':True,'health':health,'deployed_frontend_matches_build':frontend_ok,'artifacts':assets,'portrait_enabled':False,'firmware_ota':False,'time':int(time.time()),'free_gb':round(shutil.disk_usage('/root').free/1e9,3)}
(ROOT/'tests/published-financial-audit.json').write_text(json.dumps(result,indent=2))
print(json.dumps({k:result[k] for k in ['passed','checked_settled_or_refunded_bills','states','legacy_pending_bound_aggregate','health','free_gb']}))
