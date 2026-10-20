"""Real configured OpenAI provider, a temporary wallet, synthetic dialogue only."""
import json
import secrets
import subprocess
import time
from pathlib import Path

mysql=['docker','exec','-i','xiaozhi-esp32-server-db','sh','-c','exec env MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql --user=root --batch --raw --skip-column-names']
def sql(text):return subprocess.run(mysql,input=text,text=True,capture_output=True,check=True).stdout.strip()
config=json.loads(sql("SELECT config_json FROM xiaozhi_esp32_server.ai_model_config WHERE id='LLM_QwenPlusOfficial';"))
assert config['type']=='openai' and config['base_url']=='http://127.0.0.1:3000/v1'
username='codex-memory-test-'+secrets.token_hex(6)
key=secrets.token_hex(24)
sql("INSERT INTO one_api.users(username,password,display_name,role,status,quota,used_quota,request_count,`group`,access_token,aff_code) VALUES('"+username+"','"+secrets.token_hex(32)+"','synthetic-memory-test',1,1,10000,0,0,'default','"+secrets.token_hex(16)+"','"+secrets.token_hex(4)+"');")
owner=int(sql("SELECT id FROM one_api.users WHERE username='"+username+"';"))
assert owner>0
sql("INSERT INTO one_api.tokens(user_id,`key`,status,name,created_time,accessed_time,expired_time,remain_quota,unlimited_quota,used_quota,models,subnet) VALUES("+str(owner)+",'"+key+"',1,'synthetic-memory-test',"+str(int(time.time()))+","+str(int(time.time()))+",-1,10000,0,0,'qwen-plus','');")
config.update(api_key='sk-'+key,temperature=0,max_tokens=256,timeout=25)
try:
    # Only the logger's application config is synthetic. The provider below
    # uses the real configured model endpoint with the temporary wallet token.
    import config.logger as test_logging
    test_logging.check_config_file=lambda:None
    test_logging.load_config=lambda:{'log':{'log_level':'WARNING','log_dir':'/tmp/bailian-model-test-logs','data_dir':'/tmp/bailian-model-test-data'}}
    from core.providers.llm.openai.openai import LLMProvider
    from plugins_func.functions import person_memory
    from plugins_func.register import all_function_registry
    provider=LLMProvider(config)
    tools=[all_function_registry['memory_search'].description,
        {'type':'function','function':{'name':'device_set_volume','description':'设置设备音量','parameters':{'type':'object','properties':{'volume':{'type':'integer'}},'required':['volume']}}}]
    cases=[('greeting','你好',None),('device','把音量设置到30%', 'device_set_volume'),('history','请查询我以前告诉过你的饮食偏好。当前对话没有这条信息。','memory_search')]
    results=[]
    for name,text,expected in cases:
        called=[]
        for content,calls in provider.response_with_functions('synthetic-'+name,[{'role':'system','content':'你是语音设备助手。需要以前的信息时按工具说明检索长期记忆；普通闲聊、设备控制和常识不要检索。不要猜测未提供的个人历史。'},{'role':'user','content':text}],tools):
            if calls:
                for call in calls:
                    function=getattr(call,'function',None)
                    tool=getattr(function,'name',None)
                    if tool:called.append(tool)
        assert (not called if expected is None else expected in called),(name,called)
        assert name=='history' or 'memory_search' not in called
        results.append({'case':name,'tools':called,'passed':True})
    provider.client.close()
    used=int(sql('SELECT used_quota FROM one_api.users WHERE id='+str(owner)+';'))
    report={'passed':True,'provider':'openai','model':config['model_name'],'synthetic_wallet_used_quota':used,'cases':results}
    Path('/tmp/bailian-memory-model-tool-result.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
finally:
    # Remove only rows created by this test and its own logs. Never customer rows.
    sql("DELETE FROM one_api.logs WHERE user_id="+str(owner)+"; DELETE FROM one_api.tokens WHERE user_id="+str(owner)+" AND name='synthetic-memory-test'; DELETE FROM one_api.users WHERE id="+str(owner)+" AND username='"+username+"';")
