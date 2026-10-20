import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,'/root/prjs/xiaozhi_mcp_gateway')
from tools import habit_tool
import httpx
observed=[]
original=httpx.AsyncClient.post
async def traced(client,*args,**kwargs):
    response=await original(client,*args,**kwargs)
    observed.append({'status':response.status_code,'error':response.json().get('error')});return response
async def main():
    httpx.AsyncClient.post=traced
    okay=await habit_tool._sync_habit_to_device({'id':2147483647})
    assert not okay and observed==[{'status':200,'error':'not_found'}]
    result={'gateway_bearer_authenticated':True,'missing_record_not_claimed_success':True,'hardware_writes':0}
    (Path(__file__).parent/'gateway-auth-result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
asyncio.run(main())
