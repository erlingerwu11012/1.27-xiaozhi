"""Read routing metadata only; never export keys or customer messages."""
from pathlib import Path
source=Path(__file__).with_name('inspect_default_route.py').read_text().split('cfg=json.loads')[0]
exec(compile(source,'<read-only-bootstrap>','exec'))
print(sql("SELECT JSON_OBJECT('id',id,'name',name,'type',type,'status',status,'base_url',base_url,'models',models,'model_mapping',model_mapping) FROM one_api.channels WHERE id IN (2,8);"))
print(sql("SELECT JSON_OBJECT('key',\u0060key\u0060,'value',value) FROM one_api.options WHERE \u0060key\u0060 IN ('ModelRatio','CompletionRatio','ModelFixedPrice','ModelPrice');"))
