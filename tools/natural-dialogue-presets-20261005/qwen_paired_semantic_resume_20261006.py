"""Transparent continuation of two semantically valid calls stopped by scoring.

The original benchmark and initial calls are immutable. Both models receive
their own previously produced call and the same frozen receipt policy. No
prompt, parameter, tool definition, or proposed argument is edited here.
"""
import asyncio,copy,json,time
import qwen_paired_tool_test_20261006 as paired

async def resume(model,case_id):
    data=json.loads(paired.RESULT.read_text())
    pack=json.loads(paired.PACK.read_text())
    original=next(r for r in data['cases'] if r['model']==model and r['id']==case_id and r['trial']==1)
    row=next(r for r in pack['cases'] if r['id']==case_id)
    messages=copy.deepcopy(row['initial_messages']);tools=copy.deepcopy(row['tools'])
    first=original['steps'][0]
    assert len(first['calls'])==1 and first['calls'][0]['name']=='add_reminder'
    messages.append({'role':'assistant','content':first['text'] or None,'tool_calls':[{'id':c['id'],'type':'function','function':{'name':c['name'],'arguments':c['arguments']}} for c in first['calls']]})
    call=first['calls'][0]
    norm,args=paired.normalized_call(call,tools)
    # These are the only reviewer corrections: content synonyms. The intended
    # event and natural-language time are both present in the original args.
    assert args['remind_time_str'] in {'半小时后','五分钟后'}
    accepted={'31':{'取快递','拿快递'},'35':{'站起来走走','起来活动一下'}}
    assert args['content'] in accepted[str(case_id)]
    payload=paired.receipt(row,call['name'],args,{'volume':50,'brightness':80})
    messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(payload,ensure_ascii=False)})
    p,cap=paired.provider(model);started=time.perf_counter()
    try:
        answer=await asyncio.to_thread(paired.old.stream,p,messages,tools)
        passed=bool(answer['text'].strip() and not answer['calls'] and not cap['api_errors'] and 'length' not in cap['finish_reasons'])
        return {'model':model,'id':case_id,'trial':1,'review_reason':'content_synonym','original_initial_request_sha256':original['request_hashes'][0],'unchanged_initial_call':call,'receipt':payload,'continuation':answer,'continuation_pass':passed,'request_hashes':cap['request_hashes'],'response_models':sorted(cap['response_models']),'reasoning_chars':cap['reasoning_chars'],'api_errors':cap['api_errors'],'elapsed_ms':round((time.perf_counter()-started)*1000)}
    finally:p.client.close()

async def run():
    rows=await asyncio.gather(*(resume(model,i) for i in [31,35] for model in paired.MODELS))
    result={'original_pack_sha256':json.loads(paired.PACK.read_text())['content_sha256'],'method':'Resume saved original native call; no rerun or replacement of first decision; symmetric continuation for both models. Original benchmark JSON remains intact.','cases':rows}
    (paired.OUT/'qwen-paired-semantic-resume-20261006.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(rows,ensure_ascii=False),flush=True)

asyncio.run(run())
