import os
import bootstrap,asyncio,json,copy,io,time,base64
from bootstrap import stage,budget,production_provider
from aiohttp import web,ClientSession,FormData
import base64
from unittest.mock import patch
import core.api.vision_handler as module
from core.utils.vision_capability import build_vision_capabilities
async def main():
 _,cfg=production_provider();cfg=copy.deepcopy(cfg);cfg['read_config_from_api']=False;cfg['sys_user_id']='99017001';cfg['server']['auth_key']='synthetic-vision-auth-key-20261009';cfg['server']['face']={'enabled':False,'account_id':'99017001','allow_legacy_vision_tokens':False};cfg['server']['public_base_url']='https://simulation.realecho.test';cfg['server']['vision_explain']='https://simulation.realecho.test/mcp/vision/explain';cfg['server']['vision_identity']='https://simulation.realecho.test/mcp/vision/identify'
 v=cfg['VLLM'][cfg['selected_module']['VLLM']];v.update(model_name='qwen3-vl-plus',api_key='sk-'+('k'*32),base_url=os.environ['ISOLATED_VISION_GATEWAY']+'/v1',hardware_billing=True,hardware_account_id='99017001',hardware_operation='vision')
 os.environ['HW_BILLING_GATEWAY_ORIGIN']=os.environ['ISOLATED_VISION_GATEWAY'];os.environ['HW_BILLING_SERVICE_KEY']='s'*32
 cap=build_vision_capabilities(cfg,device_id='test-vision-device',account_id='99017001',session_id='vision-test-session');assert cap.ok
 handler=module.VisionHandler(cfg);app=web.Application();app.router.add_post('/mcp/vision/explain',handler.handle_post);runner=web.AppRunner(app);await runner.setup();site=web.TCPSite(runner,'127.0.0.1',0);await site.start();port=site._server.sockets[0].getsockname()[1]
 picture=base64.b64decode((stage/'synthetic-blue-jpeg.b64').read_text());headers={'Device-Id':'test-vision-device','Session-Id':'vision-test-session','Authorization':'Bearer '+cap.vision['token']};records=[]
 async def request(name,header=None,form_session='vision-test-session',with_image=True):
  budget.reserve('case','vision-http:'+name);form=FormData();form.add_field('question','图片主要是什么颜色？',content_type='text/plain');form.add_field('session_id',form_session,content_type='text/plain')
  if with_image:form.add_field('image',picture,filename='synthetic-blue.jpg',content_type='image/jpeg')
  async with ClientSession() as http:
   async with http.post(f'http://127.0.0.1:{port}/mcp/vision/explain',data=form,headers=headers if header is None else header) as r:data=await r.json();record={'name':name,'status':r.status,'body':data};records.append(record);return record
 try:
  assert (await request('unauthenticated',{}))['status']==401
  assert (await request('wrong_session',form_session='wrong'))['status']==403
  ticks=0
  async def ticker():
   nonlocal ticks
   for _ in range(20):await asyncio.sleep(.01);ticks+=1
  class Slow:
   def response(self,*a):time.sleep(.15);return '蓝色。'
  with patch.object(module,'create_instance',lambda *a:Slow()):
   t=asyncio.create_task(ticker());record=await request('slow_model_keeps_loop_responsive');observed=ticks;await t;assert record['status']==200 and observed>=8,(record,observed);record['heartbeat_ticks_during_request']=observed
  original=module.create_instance
  def real_factory(*a):
   provider=original(*a);provider.client.max_retries=0;respond=provider.response
   def paid(*args):
    charge=budget.reserve('vision','current-official-vlm');value=respond(*args);budget.finish(charge,{'success':isinstance(value,str) and bool(value),'text_length':len(value) if isinstance(value,str) else None});return value
   provider.response=paid;return provider
  with patch.object(module,'create_instance',real_factory):
   result=await request('real_vlm_upload');assert result['status']==200 and '蓝' in result['body']['response'],result

 finally:
  await runner.cleanup();(stage/'vision-http-plus-results.json').write_text(json.dumps(records,ensure_ascii=False,indent=2));print(json.dumps({'records':records,'budget':budget.report()},ensure_ascii=False),flush=True)
asyncio.run(main())
