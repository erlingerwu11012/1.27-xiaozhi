from pathlib import Path
root=Path(__file__).parent/'candidate'
p=root/'core/utils/tool_harness/runtime.py';s=p.read_text(encoding='utf-8')
s=s.replace("low,high=schema.get('minimum'),schema.get('maximum')","from .domains import bounds\n                        low,high=bounds(name,tools[name])")
s=s.replace("if key=='brightness' and type(sub.get('brightness_level')) is int:","if key=='brightness' and (type(sub.get('brightness_level')) is int or (low,high)==(1,5)):")
s=s.replace("value=sub['brightness_level'];low,high=1,5","value=sub.get('brightness_level',value);low,high=1,5\n                                if not 1<=value<=5:raise ValueError('current_brightness_unit_unknown')")
s=s.replace("        Draft202012Validator(schema).validate(args)\n        if set(args)","        Draft202012Validator(schema).validate(args)\n        from .domains import validate_domain\n        validate_domain(name,args,current)\n        if set(args)")
p.write_text(s,encoding='utf-8')
p=root/'core/utils/recent_memory.py';s=p.read_text(encoding='utf-8')
start=s.index('    provider=getattr(conn,"memory",None)',s.index('async def override'))
s=s[:start]+'''    if action not in {'correct','forget'} or not isinstance(match,str) or not match or len(match)>1024:
        return {'status':'error','errorCode':'invalid_memory_match','message':'请先确认要修改的单条记忆。'}
    if action=='correct' and (not isinstance(replacement,str) or not replacement.strip() or len(replacement)>2048):
        return {'status':'error','message':'新的记忆内容无效。'}
    from config.manage_api_client import ManageApiClient
    result=await ManageApiClient(conn.config).request('POST','person-memory/internal/override',
        json={'actor':actor.payload(),'action':action,'match':match,'replacement':replacement},timeout=3)
    from core.utils.person_short_memory import invalidate
    invalidate(actor)
    conn.dialogue.invalidate_summary()
    # Invalidate only matching facts, not the ongoing conversation.
    kept=[]
    for message in conn.dialogue.dialogue:
        text=str(getattr(message,'content','') or '')
        if message.role=='system' or (match!='*' and match not in text):kept.append(message)
    conn.dialogue.dialogue[:]=kept
    provider=getattr(conn,'memory',None)
    if provider:
        provider.short_memory=''
        if hasattr(provider,'_portraits'):provider._portraits.pop(actor.key,None)
        if hasattr(provider,'_queries'):provider._queries.pop(actor.turn_id,None)
    if isinstance(result,dict) and result.get('local_applied') is True:
        return {**result,'ok':True,'operation':action}
    return {'status':'accepted','cloud_sync':'pending','operation':action}
'''
p.write_text(s,encoding='utf-8')
p=root/'core/utils/tool_harness/contracts.py';s=p.read_text(encoding='utf-8')
s=s.replace("return out('completed','记忆更正已保存。' if name.endswith('correct') else '指定记忆已删除。')","return out('completed',('本地记忆已更正。' if name.endswith('correct') else '指定记忆已从本地召回中移除。')+('云端仍在同步。' if body.get('cloud_sync')=='pending' else ''))")
p.write_text(s,encoding='utf-8')
print('presentation, domains and targeted memory candidate ready')
