"""Readiness and unauthenticated rejection; no authenticated device writes."""
import asyncio,json,time
from pathlib import Path
import aiohttp
stage=Path(__file__).parent
async def main():
    results={'timestamp':time.time(),'hardware':False,'production_proxy_changed':False,'checks':[]}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
        for name,url,method,expected in [
            ('candidate_http','http://127.0.0.1:8023/','GET',404),
            ('candidate_device_auth','http://127.0.0.1:8026/api/v1/device/send','POST',401),
            ('candidate_habit_auth','http://127.0.0.1:8026/api/v1/habit/sync','POST',401),
            ('formal_home','https://www.realecho.cn/','GET',200),
            ('production_device_auth','http://127.0.0.1:8006/api/v1/device/send','POST',401)]:
            try:
                async with session.request(method,url,json={} if method=='POST' else None) as response:
                    await response.read();results['checks'].append({'name':name,'status':response.status,'expected':expected,'passed':response.status==expected})
            except Exception as exc:results['checks'].append({'name':name,'passed':False,'error_type':type(exc).__name__})
        try:
            async with session.ws_connect('http://127.0.0.1:8020/xiaozhi/v1/',headers={'Device-Id':'00:00:00:00:00:00','Client-Id':'harness-unauthenticated-health'}) as ws:
                msg=await ws.receive(timeout=5)
                body=json.loads(msg.data) if msg.type==aiohttp.WSMsgType.TEXT else None
                error=body.get('type')=='error' or bool(body.get('error')) if isinstance(body,dict) else False
                results['checks'].append({'name':'candidate_ws_auth','passed':error,'message_type':str(msg.type),'error_code':body.get('code') if isinstance(body,dict) else None})
        except aiohttp.WSServerHandshakeError as exc:results['checks'].append({'name':'candidate_ws_auth','passed':exc.status in {401,403},'http_status':exc.status})
        except Exception as exc:results['checks'].append({'name':'candidate_ws_auth','passed':False,'error_type':type(exc).__name__})
    (stage/'readiness-evidence.json').write_text(json.dumps(results,indent=2));print(json.dumps(results))
asyncio.run(main())