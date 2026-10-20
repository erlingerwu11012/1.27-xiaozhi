"""Synthetic Ali reference receipts; verifies meters independently of legacy gateway.

This is NOT a customer billing or gateway end-to-end pass. Only two selected
hardware credential rows are read into memory; never output keys/config/body.
"""
import asyncio,base64,json,subprocess,struct,zlib
from pathlib import Path
import httpx
ROOT=Path('/root/prjs/tmp/hardware-billing70-20261001')
MYSQL=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def sql(q):return subprocess.run(MYSQL,input=q,text=True,capture_output=True,check=True).stdout.strip()
async def main():
    llmkey=sql('SELECT `key` FROM one_api.channels WHERE id=2 AND type=17 AND status=1;')
    vision=json.loads(sql("SELECT config_json FROM xiaozhi_esp32_server.ai_model_config WHERE id='VLLM_QwenVLVLLM' AND model_type='VLLM';"))
    assert llmkey and '\n' not in llmkey
    assert vision.get('base_url')=='https://dashscope.aliyuncs.com/compatible-mode/v1'
    def chunk(k,d):return struct.pack('!I',len(d))+k+d+struct.pack('!I',zlib.crc32(k+d)&0xffffffff)
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('!2I5B',128,128,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+b'\xff\0\0'*128)*128))+chunk(b'IEND',b'')
    cases=[('llm-native','qwen-plus',llmkey,'一加一等于几？'),('vision-native','qwen3-vl-flash',vision.get('api_key'),[{'type':'text','text':'这张合成图是什么颜色？只说颜色。'},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(png).decode()}}])]
    rows=[]
    async with httpx.AsyncClient(timeout=35) as client:
        for name,model,key,content in cases:
            response=await client.post('https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions',headers={'Authorization':'Bearer '+key},json={'model':model,'messages':[{'role':'user','content':content}],'max_tokens':64,'temperature':0,'enable_thinking':False})
            if response.status_code==200:
                data=response.json();answer=data.get('choices',[{}])[0].get('message',{}).get('content','');passed=bool(answer) if model=='qwen-plus' else '红' in answer
                row={'case':name,'passed':passed,'model':model,'usage':data.get('usage'),'upstream_request_id':data.get('id'),'gateway_end_to_end':False}
            else:row={'case':name,'passed':False,'status':response.status_code,'gateway_end_to_end':False}
            rows.append(row);print(json.dumps(row),flush=True)
    (ROOT/'tests/native-reference.json').write_text(json.dumps(rows,indent=2))
    return 0 if all(r['passed'] for r in rows) else 1
if __name__=='__main__':raise SystemExit(asyncio.run(main()))
