import bootstrap,threading,json,time,uuid,requests,dataclasses
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from test_followup import Followup,sql,HEADERS,API
from config.manage_api_client import ManageApiClient,report
from bootstrap import budget,stage
charge=budget.reserve('case','history-real-http-commit-500-retry-same-event')
t=Followup();t.setUp();event='retry-'+uuid.uuid4().hex;seen=[]
class Proxy(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_POST(self):
  body=self.rfile.read(int(self.headers['Content-Length']));seen.append(json.loads(body))
  response=requests.post(API+'/agent/chat-history/report',headers=HEADERS,json=json.loads(body),timeout=8);assert response.status_code==200 and response.json()['code']==0,(response.status_code,response.text[:150])
  self.send_response(500 if len(seen)==1 else 200);self.send_header('Content-Type','application/json');self.end_headers();self.wfile.write(response.content)
server=ThreadingHTTPServer(('127.0.0.1',0),Proxy);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
try:
 sql("UPDATE ai_agent SET chat_history_conf=1 WHERE id='agent_http' AND user_id=99003")
 ManageApiClient({'manager-api':{'url':'http://127.0.0.1:'+str(server.server_port)+'/xiaozhi','secret':HEADERS['Authorization'][7:],'max_retries':1,'retry_delay':.01}})
 report('test-device-http','isolated-retry',2,'历史网络重试隔离样本',None,int(time.time()),{'identity':t.actor.payload(),'eventId':event,'turnId':t.actor.turn_id})
 count=sql('SELECT count(*) FROM ai_agent_chat_history WHERE account_id=99003 AND event_id=%s',(event,),True)[0][0]
 assert len(seen)==2 and seen[0]==seen[1] and count==1
 result={'passed':True,'requests':len(seen),'persisted_events':count,'first_response_after_commit':500,'second_response':200,'business_operations':0};budget.finish(charge,result);(stage/'history-retry-evidence.json').write_text(json.dumps(result));print(result)
except Exception as exc:budget.finish(charge,{'passed':False,'error':repr(exc)});raise
finally:server.shutdown();ManageApiClient.safe_close()
