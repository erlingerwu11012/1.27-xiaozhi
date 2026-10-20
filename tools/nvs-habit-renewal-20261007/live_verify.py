"""Real manager HTTP/SQL plus the actual Python MCP pipeline with a software device.
The synthetic MAC has no physical device; no hardware commands are issued.
"""
import asyncio,importlib.util,json,os,sys,time,uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock,patch,AsyncMock
import httpx,pymysql,yaml
stage=Path(__file__).parent
root=stage/'work/xiaozhi-server';sys.path.insert(0,str(root))
import config.config_loader
config.config_loader.get_config_from_api=lambda config:dict(config,read_config_from_api=False)
import config.settings
config.settings.config_file_valid=True
import config.logger
config.logger.setup_logging=lambda:MagicMock()
import app
from config.manage_api_client import ManageApiClient
from core.providers.tools.device_mcp.mcp_client import MCPClient
from core.providers.tools.device_mcp.mcp_handler import handle_mcp_message
spec=importlib.util.spec_from_file_location('private_db','/root/prjs/xiaozhi_mcp_gateway/core/db_config.py');dbconfig=importlib.util.module_from_spec(spec);spec.loader.exec_module(dbconfig)
db=pymysql.connect(host=dbconfig.DB_HOST,port=dbconfig.DB_PORT,user=dbconfig.DB_USER,password=dbconfig.DB_PASSWORD,database=dbconfig.DB_NAME,charset='utf8mb4',autocommit=True,cursorclass=pymysql.cursors.DictCursor)
cfg=yaml.safe_load(Path('/root/prjs/xiaozhi-esp32-server/main/xiaozhi-server/data/.config.yaml').read_text())
api=ManageApiClient(cfg)
device='02:'+':'.join(uuid.uuid4().hex[i:i+2] for i in range(0,10,2));device_row=uuid.uuid4().hex
checks=[];habit_id=None
def sql(statement,*args):
    with db.cursor() as c:c.execute(statement,args);return c.fetchall() if c.description else c.lastrowid
def check(name,condition):
    if not condition:raise AssertionError(name)
    checks.append(name);print('PASS '+name,flush=True)
class SoftwareDevice:
    def __init__(self):self.rows={};self.mode='normal';self.sends=0;self.writes=0
    def reply(self,p):
        self.sends+=1
        if self.mode=='storage_full':return {'ok':False,'persisted':False,'error':'storage_full'}
        key=p['sync_id'];existing=self.rows.get(key)
        if not existing or existing['content_hash']!=p['content_hash']:
            self.writes+=1;self.rows[key]=dict(p,device_rule_id=(existing or {}).get('device_rule_id',len(self.rows)+1))
        row=self.rows[key]
        return dict(ok=True,persisted=True,sync_id=key,content_hash='f'*64 if self.mode=='bad_hash' else p['content_hash'],device_rule_id=row['device_rule_id'],enabled=row['enabled'])
async def main():
    global habit_id
    accounts=sql('SELECT user_id FROM ai_device WHERE user_id IS NOT NULL LIMIT 1');account=str(accounts[0]['user_id'])
    # Read the existing account state. This is an account directory, never a fabricated voice actor.
    directory=await api.request('GET',f'user-identities/internal/state/{account}',timeout=5)
    version=int(directory['directory_version'])
    sql('INSERT INTO ai_device(id,user_id,mac_address,alias,create_date) VALUES(%s,%s,%s,%s,NOW())',device_row,account,device,'临时软件协议验收')
    habit_id=sql("INSERT INTO sys_habits(intent,description,hour,minute,advance_minutes,source,enabled,synced,device_id,user_id,recipient_person_id,recipient_display_name,sync_state) VALUES('integration_test','软件协议验收',8,0,2,'integration_test',1,0,%s,%s,'all','公共接收人','pending')",device,account)
    software=SoftwareDevice();conn=SimpleNamespace(device_id=device,session_id='software-test-session',features={'mcp':True},config=dict(cfg,sys_user_id=account),logger=MagicMock(),identity_synced_version=version,_outbound_tasks=set(),superseded=False)
    conn.mcp_client=MCPClient(device_id=device,session_id=conn.session_id);conn.mcp_client.capabilities={'experimental':{'habitSync':1}}
    class Server:
        _connections={device:{conn.session_id:conn}}
        def get_current_main_session_id(self,d):return conn.session_id if self._connections.get(d) else None
        def is_current_connection(self,d,c):return self._connections.get(d,{}).get(c.session_id) is c
        async def send_to_current(self,d,data,handler=None,**kw):
            if not self.is_current_connection(d,handler):return False
            rpc=json.loads(data)['payload'];check_method=rpc.get('method')
            if check_method!='habit/sync':raise AssertionError('unexpected software RPC')
            await handle_mcp_message(conn,conn.mcp_client,{'jsonrpc':'2.0','id':rpc['id'],'result':software.reply(rpc['params'])});return True
    server=Server();conn.server=server
    app.broadcast_app.state.config=cfg;app.broadcast_app.state.ws_server=server
    headers={'Authorization':'Bearer '+cfg['manager-api']['secret']}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app.broadcast_app),base_url='http://software') as client:
        async def sync():return (await client.post('/api/v1/habit/sync',headers=headers,json={'habit_id':habit_id})).json()
        async def state():return sql('SELECT synced,sync_state,sync_error,device_rule_id FROM sys_habits WHERE id=%s',habit_id)[0]
        unauth=await client.post('/api/v1/habit/sync',json={'habit_id':habit_id});check('Python internal entry rejects missing Bearer',unauth.status_code==401)
        base=cfg['manager-api']['url'].rstrip('/');base=base if base.endswith('/xiaozhi') else base+'/xiaozhi'
        async with httpx.AsyncClient(timeout=10) as network:
            unauth=await network.get(base+'/habits/internal/'+str(habit_id));check('Java internal entry rejects missing Bearer',unauth.status_code==401)
        with patch('core.utils.person_identity.refresh_directory',new=AsyncMock(return_value=dict(directory,directory_version=version,account_id=account))):
            server._connections={};out=await sync();check('offline never marks saved',out['error']=='device_offline' and (await state())['synced']==0)
            server._connections={device:{conn.session_id:conn}};conn.mcp_client.capabilities={};out=await sync();check('legacy firmware classified without RPC',out['sync_state']=='upgrade_required' and software.sends==0)
            conn.mcp_client.capabilities={'experimental':{'habitSync':1}};conn.config['sys_user_id']='foreign';out=await sync();check('connection account mismatch refused',out['error']=='ownership_mismatch' and software.sends==0)
            conn.config['sys_user_id']=account;software.mode='storage_full';out=await sync();check('storage failure persists a truthful failure state',out['error']=='storage_full' and (await state())['synced']==0)
            software.mode='bad_hash';out=await sync();check('mismatched persisted receipt refused',out['error']=='invalid_receipt' and (await state())['synced']==0)
            software.mode='normal';out=await sync();first=out['device_rule_id'];check('real HTTP and SQL acknowledge only matched software MCP receipt',out['ok'] and (await state())['synced']==1)
            writes=software.writes;out=await sync();check('duplicate source ID retains the same device rule',out['ok'] and out['device_rule_id']==first and software.writes==writes and len(software.rows)==1)
            previous=await api.request('GET',f'habits/internal/{habit_id}',timeout=5)
            sql('UPDATE sys_habits SET hour=9,config_version=config_version+1,synced=0,sync_state=%s WHERE id=%s','pending',habit_id)
            late=await api.request('POST','habits/internal/ack',json={'habitId':habit_id,'contentHash':previous['payload']['content_hash'],'configVersion':previous['config_version'],'state':'synced','deviceRuleId':first},timeout=5)
            check('late acknowledgement cannot overwrite a changed configuration',late['accepted'] is False)
            out=await sync();check('changed schedule updates the existing rule',out['ok'] and out['device_rule_id']==first and software.rows[str(habit_id)]['hour']==9)
            sql("UPDATE sys_habits SET enabled=0,config_version=config_version+1,synced=0,sync_state='pending' WHERE id=%s",habit_id)
            out=await sync();check('delete synchronizes disabled state through matching save receipt',out['ok'] and software.rows[str(habit_id)]['enabled'] is False)
    # Verify the actual production endpoint auth and application availability too.
    async with httpx.AsyncClient(timeout=10) as http:
        r=await http.post('http://127.0.0.1:8006/api/v1/habit/sync',json={'habit_id':habit_id});check('production Python requires Bearer',r.status_code==401)
        r=await http.post('http://127.0.0.1:8006/api/v1/habit/sync',headers=headers,json={'habit_id':habit_id});check('production routes synthetic offline device without success claims',r.status_code==200 and r.json().get('error')=='device_offline' and r.json().get('ok') is False)
        for url in ('https://www.realecho.cn/','https://realecho.cn/'):
            r=await http.get(url,follow_redirects=True);check('production domain '+url,r.status_code==200 and '<html' in r.text.lower())
    (stage/'live-verification.json').write_text(json.dumps({'passed':True,'checks':checks,'software_device':True,'hardware_writes':0,'test_records_removed':True},indent=2))
try:
    asyncio.run(main())
finally:
    if habit_id is not None:sql('DELETE FROM sys_habits WHERE id=%s AND device_id=%s',habit_id,device)
    sql('DELETE FROM ai_device WHERE id=%s AND mac_address=%s',device_row,device)
    db.close()
