import live_auth as auth
import json
cfg=json.loads(auth.sql("SELECT config_json FROM xiaozhi_esp32_server.ai_model_config WHERE id='LLM_QwenPlusOfficial';"))
print(json.dumps({k:cfg.get(k) for k in ['model_name','base_url','aimi_device_gateway']}))
print(auth.sql('SELECT models FROM one_api.tokens WHERE user_id='+str(auth.owner)+';'))
print(auth.sql("SELECT name,models,model_mapping FROM one_api.channels WHERE status=1 AND FIND_IN_SET('aimi-chat',models);"))
print(auth.sql("SELECT `key`,value FROM one_api.options WHERE `key` IN('ModelRatio','CompletionRatio','GroupRatio');"))
print(auth.sql('SELECT quota,used_quota FROM one_api.users WHERE id='+str(auth.owner)+';'))
key=cfg.get('api_key','').removeprefix('sk-');assert key.isalnum()
print('configured_provider_wallet',auth.sql("SELECT u.id,u.quota,u.used_quota,t.models FROM one_api.tokens t JOIN one_api.users u ON u.id=t.user_id WHERE t.`key`='"+key+"';"))
print('official_route',auth.sql("SELECT name,model_mapping FROM one_api.channels WHERE status=1 AND FIND_IN_SET('qwen-plus',models);"))
