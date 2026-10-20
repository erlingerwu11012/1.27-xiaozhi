import bootstrap,json
from bootstrap import stage,budget,production_provider
from core.providers.vllm.openai import VLLMProvider
p,c=production_provider();p.client.close();m=json.loads((stage/'live-config-private.json').read_text());v=m['VLLM'][m['selected_module']['VLLM']]
p=VLLMProvider(v);p.client.max_retries=0
budget.reserve('case','readonly-vision-model-directory')
try:
 from core.utils.hardware_billing import request_headers
 names=[x.id for x in p.client.models.list(extra_headers=request_headers(p.hardware_context['account_id'],'vision')).data if 'qwen' in x.id.lower()]
 print('QWEN_MODELS',names);(stage/'vision-model-directory.json').write_text(json.dumps(names))
finally:p.client.close()
