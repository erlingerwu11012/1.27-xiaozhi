from pathlib import Path
text=Path(__file__).with_name('deploy_release.py').read_text().split('try:\n cfg=')[0]
exec(compile(text,'<release-preflight>','exec'))
cfg=(spring.get('data')or{}).get('redis') or spring.get('redis') or {}
print(json.dumps({'redis_host':cfg.get('host'),'redis_port':cfg.get('port'),'redis_db':cfg.get('database'),'redis_password_configured':bool(cfg.get('password')),'model':json.loads(sql("SELECT config_json FROM ai_model_config WHERE id='LLM_QwenPlusOfficial';"))['model_name'],'new_channel_present':sql("SELECT COUNT(*) FROM one_api.channels WHERE name='official-qwen38-compatible';")}))
try:clear_model_cache();print('model_cache_refreshed')
except Exception as e:print(json.dumps({'cache_error_type':type(e).__name__}))
print(command(['docker','inspect','one-api','--format','{{.State.Status}} {{.Config.Image}}']))
