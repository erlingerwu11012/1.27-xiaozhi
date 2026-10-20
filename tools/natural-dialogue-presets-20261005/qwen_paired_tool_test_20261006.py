"""Predeclared paired test: only the model name differs in initial API payloads.

840 model cases (140 fixed inputs x 3 repeats x 2 models). Frozen receipts are
shared to control time/randomness; live MCP verification is a separate phase.
Never changes production defaults, code, customer records, or hardware.
"""
import asyncio, copy, hashlib, json, os, re, sys, time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import qwen37_tool_retest_20261006 as old

OUT=old.OUT
PACK=OUT/'qwen-paired-tool-pack-20261006.json'
RESULT=OUT/'qwen-paired-tool-results-20261006.json'
MODELS=['qwen3.7-plus','qwen3.8-flash']
REPEATS=3
CLOCK='2026-10-06T10:17:43+08:00'
GUIDANCE=old.FINAL_TOOL_GUIDANCE.replace(
    '参数按 schema 检查类型和范围；超范围就说明并询问，不能擅自改成边界值。询问用户是否接受替代值时，不能同时调用工具。',
    '参数类型和范围以 schema 为准。音量、亮度超出范围时按当前工具的上下限限幅，不需要额外确认；执行程序也会按同一范围限幅。收到完成回执后说明实际设置值和边界，不能说设到了不支持的值。其他参数不得擅自替换或补全。')

def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def sha(value):return hashlib.sha256(canonical(value).encode()).hexdigest()

def install_guard():
    import core.utils.operation_control as control
    import core.providers.tools.unified_tool_manager as manager
    root=OUT/'qwen-paired-guard'
    for module,path in [(control,root/'core/utils/operation_control.py'),(manager,root/'core/providers/tools/unified_tool_manager.py')]:
        exec(compile(path.read_text(),str(path),'exec'),module.__dict__)

async def prepare():
    settings=json.loads((old.PROD/'data/.mcp_server_settings.json').read_text())['mcpServers']
    client=old.ServerMCPClient(next(c for c in settings.values() if not c.get('disabled',False)))
    try:await client.initialize();real=client.get_available_tools()
    finally:await client.cleanup()
    rows=old.dataset()+old.holdout_dataset()
    for row in rows:
        if row['id']==80:
            row.update(group='device_fixture',expected=[('self_screen_set_brightness',{'brightness':50})],clamped_from=20)
        if row['id']==139:
            row.update(group='device_fixture',expected=[('self_audio_speaker_set_volume',{'volume':100})],clamped_from=120)
        row['persona']='existing-playful' if row['id']%2 else 'natural'
        persona=old.PERSONA if row['id']%2 else '你随和、坦诚，有自己的看法。用熟人之间自然的方式交谈。'
        system=old.PromptManager({'system_base_prompt':old.base.get('system_base_prompt',''),'language':'中文'},logger=old.MagicMock()).build_enhanced_prompt_v2(persona,'paired-tool-test',device_name='小智',user_nickname='主人',official_enhanced=True)
        system+='\n\n'+GUIDANCE+'\n\n[本轮可信验收时钟]\n当前日期时间：2026-10-06 10:17:43，时区Asia/Shanghai。工具回执包含查询结果；回答严格保留其数值，不估算。'
        row['initial_messages']=[{'role':'system','content':system}]+copy.deepcopy(row.get('history',[]))+[{'role':'user','content':row['user']}]
        device=row['group'] in {'device_fixture','dependency','multi_action','failure_receipt','missing_capability','device_no_operation'}
        row['tools']=old.device_tools(real,row.get('limited_device',False)) if device else copy.deepcopy(real)
        row['input_sha256']=sha({'messages':row['initial_messages'],'tools':row['tools']})
    pack={'created_date':'2026-10-06','models':MODELS,'repeats':REPEATS,'temperature':.4,'max_tokens':600,
          'enable_thinking':False,'preserve_thinking':False,'endpoint':'https://dashscope.aliyuncs.com/compatible-mode/v1',
          'reference_clock':CLOCK,'tool_guidance':GUIDANCE,'real_catalog':real,'cases':rows,
          'selection_rule':'Rank by full native tool decision success (required calls, correct names and normalized arguments, dependency order, no unrelated writes or missed fresh queries). Exact tie -> lower official token price.',
          'grading_rule':'No call is correct for negation/quotes/hypotheticals/missing parameters/capability. One read-only device-status verification after a partial failure is allowed. Numeric device values may clamp to current schema bounds. Primary-model prose and receipt fidelity are scored separately. API errors count as failed in availability-inclusive totals; no retries.',
          'receipt_rule':'Deterministic isolated receipts; same reference clock, initial device state, random result, and failure payload for both models. No physical or customer writes.'}
    pack['content_sha256']=sha(pack)
    PACK.write_text(json.dumps(pack,ensure_ascii=False,indent=2))
    (OUT/'qwen-paired-prompt-20261006.txt').write_text(rows[0]['initial_messages'][0]['content'])
    print(json.dumps({'prepared':len(rows),'repeats':REPEATS,'pack_sha256':pack['content_sha256']}),flush=True)

def provider(model):
    p=old.LLMProvider({**old.llm,'model_name':model})
    p.client=p.client.with_options(max_retries=0)
    original=p.client.chat.completions.create
    cap={'request_hashes':[],'usage':[],'response_models':set(),'reasoning_chars':0,'api_errors':[],'finish_reasons':[]}
    def create(**params):
        params['extra_body']={'enable_thinking':False,'preserve_thinking':False}
        params['stream_options']={'include_usage':True}
        assert params['temperature']==.4 and params['max_tokens']==600 and params['stream'] is True
        # Everything in an initial API payload except the requested model is hashed.
        cap['request_hashes'].append(sha({k:v for k,v in params.items() if k!='model'}))
        try:
            response=original(**params)
            for chunk in response:
                if chunk.model:cap['response_models'].add(chunk.model)
                if chunk.usage:cap['usage'].append(chunk.usage.model_dump())
                for choice in chunk.choices or []:
                    cap['reasoning_chars']+=len(getattr(choice.delta,'reasoning_content',None) or '')
                    if choice.finish_reason:cap['finish_reasons'].append(choice.finish_reason)
                yield chunk
        except Exception as exc:
            cap['api_errors'].append({'type':type(exc).__name__,'status':getattr(exc,'status_code',None)})
            raise
    p._create_with_retry=create
    return p,cap

def normalized_call(call,tools):
    args=json.loads(call['arguments'])
    if not isinstance(args,dict):raise ValueError('arguments_not_object')
    name=call['name'];schema=next(t['function']['parameters'] for t in tools if t['function']['name']==name)
    key={'self_audio_speaker_set_volume':'volume','self_screen_set_brightness':'brightness'}.get(name)
    if key and type(args.get(key)) is int:
        spec=schema['properties'][key]
        args[key]=max(spec['minimum'],min(spec['maximum'],args[key]))
    from jsonschema import Draft202012Validator
    Draft202012Validator(schema).validate(args)
    return {**call,'arguments':json.dumps(args,ensure_ascii=False)},args

def receipt(row,name,args,state):
    fail=row.get('failure')
    failed=bool(fail and (fail!='partial' or name=='self_screen_set_brightness'))
    if fail=='queued':return {'ok':True,'status':'queued','message':'请求已接收，排队中，尚未完成。'}
    if fail=='empty':return {}
    if failed:return {'ok':False,'error':fail,'message':'本次操作未完成，不能确认成功。'}
    if name=='get_world_time':
        now=datetime.fromisoformat(CLOCK).astimezone(ZoneInfo(args['timezone']))
        offset=now.utcoffset().total_seconds()/3600
        sign='+' if offset>=0 else '-';offset=abs(offset)
        suffix=f'{int(offset)}'+(f':{round((offset%1)*60):02d}' if offset%1 else '')
        weekday=('Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday')[now.weekday()]
        return f"🌍 {args['timezone']} 当前时间：\n{now:%Y年%m月%d日 %H:%M:%S} ({weekday})\n时区：UTC{sign}{suffix}"
    if name=='random_decision':
        mode=args['mode']
        if mode=='coin':return '🪙 抛硬币结果：正面'
        if mode=='dice':return '🎲 掷骰子结果：4 点'
        if mode=='number':
            low,high=args.get('min_val',1),args.get('max_val',100)
            return f'🔢 随机数 ({low}-{high})：{(low+high)//2}'
        return '🤔 我帮你选：'+re.split('[,，、]',args['options'])[0].strip()
    if name=='self_get_device_status':return {'audio_speaker':{'volume':state['volume']},'screen':{'brightness':state['brightness']}}
    if name=='self_camera_take_photo':return {'ok':True,'description':'桌上有一个白色杯子。'}
    if name=='habit_list_manual':return {'ok':True,'habits':[]}
    if name=='self_audio_speaker_set_volume':state['volume']=args['volume']
    if name=='self_screen_set_brightness':state['brightness']=args['brightness']
    body={'ok':True,**args}
    if name=='camera_open':body['state']='open'
    if name=='camera_close':body['state']='closed'
    if name in {'add_reminder','habit_create'}:body.update(id='isolated-test-item',success=True,status='created')
    return body

async def model_case(model,row,trial):
    p,cap=provider(model);messages=copy.deepcopy(row['initial_messages']);tools=copy.deepcopy(row['tools'])
    expected=copy.deepcopy(row['expected']);steps=[];events=[];reasons=[];native=True;premature=False
    state={'volume':50,'brightness':80};extra_verification=0;final=''
    start=time.perf_counter()
    try:
        for turn in range(4):
            step=await asyncio.to_thread(old.stream,p,messages,tools);steps.append(step);final=step['text'];calls=step['calls']
            if cap['api_errors'] or '【服务暂时无法响应' in final:native=False;reasons.append('api_error');break
            if not calls:
                if expected:native=False;reasons.append('missing_native_call')
                break
            if re.search('已(?:经)?(?:调|设|打|完成|创建)|操作成功',step['text']):premature=True
            messages.append({'role':'assistant','content':step['text'] or None,'tool_calls':[{'id':c['id'],'type':'function','function':{'name':c['name'],'arguments':c['arguments']}} for c in calls]})
            for index,c in enumerate(calls):
                verification=not expected and row.get('failure')=='partial' and c['name']=='self_get_device_status' and extra_verification==0
                try:norm,args=normalized_call(c,tools)
                except Exception:native=False;reasons.append('unknown_tool_or_invalid_schema');break
                if verification:extra_verification+=1
                else:
                    idx=next((i for i,e in enumerate(expected) if old.matches(norm,e,row['user'])),None) if row.get('unordered') else (0 if expected and old.matches(norm,expected[0],row['user']) else None)
                    if idx is None:native=False;reasons.append('unrequested_call' if not expected else 'wrong_tool_or_arguments');break
                    if row['group']=='dependency' and turn==0 and index>0:native=False;reasons.append('dependency_before_receipt');break
                    expected.pop(idx)
                payload=receipt(row,c['name'],args,state)
                text=payload if isinstance(payload,str) else json.dumps(payload,ensure_ascii=False)
                from core.utils.tool_fact_reply import verified_tool_reply
                from plugins_func.register import Action,ActionResponse
                protected=verified_tool_reply(ActionResponse(Action.REQLLM,result=text),norm)
                events.append({'name':c['name'],'raw_arguments':c['arguments'],'arguments':args,'receipt':payload,'protected_reply':protected,'extra_readonly_verification':verification})
                messages.append({'role':'tool','tool_call_id':c['id'],'content':text})
            if not native:break
        else:native=False;reasons.append('turn_limit')
        if native and not final.strip():native=False;reasons.append('empty_reply')
        if 'length' in cap['finish_reasons']:native=False;reasons.append('output_truncated')
        if not native and not row['expected'] and expected:raise AssertionError('invalid_expected_state')
        return {k:v for k,v in dict(model=model,id=row['id'],trial=trial,group=row['group'],persona=row['persona'],user=row['user'],history=row.get('history',[]),expected=row['expected'],clamped_from=row.get('clamped_from'),steps=steps,events=events,final=final,native_pass=native,reasons=reasons,premature_claim=premature,elapsed_ms=round((time.perf_counter()-start)*1000),request_hashes=cap['request_hashes'],input_sha256=row['input_sha256'],usage=cap['usage'],response_models=sorted(cap['response_models']),reasoning_chars=cap['reasoning_chars'],api_errors=cap['api_errors']).items()}
    finally:p.client.close()

async def run():
    pack=json.loads(PACK.read_text());stamp=pack.pop('content_sha256');assert sha(pack)==stamp
    assert pack['models']==MODELS and pack['repeats']==REPEATS
    data={'date':'2026-10-06','pack_sha256':stamp,'models':MODELS,'repeats':REPEATS,'planned_cases_per_model':420,'hardware_writes':0,'customer_writes':0,'production_changed':False,'cases':[],'pairs':[],'complete':False}
    limiter=asyncio.Semaphore(3)
    async def pair(row,trial):
        async with limiter:
            order=MODELS if (row['id']+trial)%2 else list(reversed(MODELS))
            results=await asyncio.gather(*(model_case(m,row,trial) for m in order))
            left=next(r for r in results if r['model']==MODELS[0]);right=next(r for r in results if r['model']==MODELS[1])
            assert left['request_hashes'][0]==right['request_hashes'][0], 'initial_API_payload_mismatch'
            assert left['input_sha256']==right['input_sha256']
            data['cases'].extend(results);data['pairs'].append({'id':row['id'],'trial':trial,'identical_initial_payload':True,'request_sha256':left['request_hashes'][0],'plus_pass':left['native_pass'],'flash_pass':right['native_pass']})
            RESULT.write_text(json.dumps(data,ensure_ascii=False,indent=2))
            print(json.dumps({'pairs_completed':len(data['pairs']),'trial':trial,'id':row['id'],'plus':left['native_pass'],'flash':right['native_pass']},ensure_ascii=False),flush=True)
    for trial in range(1,REPEATS+1):
        await asyncio.gather(*(pair(row,trial) for row in pack['cases']))
    data['complete']=True
    data['summary']={m:{'total':len([r for r in data['cases'] if r['model']==m]),'native_pass':sum(r['native_pass'] for r in data['cases'] if r['model']==m),'reasoning_chars':sum(r['reasoning_chars'] for r in data['cases'] if r['model']==m)} for m in MODELS}
    RESULT.write_text(json.dumps(data,ensure_ascii=False,indent=2));print(json.dumps(data['summary']),flush=True)

def regression():
    import unittest
    install_guard();sys.path.insert(0,str(OUT/'qwen-paired-guard/test'))
    names=['test_operation_control','test_operation_pipeline','test_verified_tool_facts','test_natural_tool_failure_regression','test_explicit_setting_targets']
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromNames(names))
    (OUT/'qwen-paired-guard-regression-20261006.json').write_text(json.dumps({'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'passed':result.wasSuccessful()}))
    raise SystemExit(0 if result.wasSuccessful() else 1)

if __name__=='__main__':
    mode=os.environ.get('PAIRED_MODE','prepare')
    if mode=='prepare':asyncio.run(prepare())
    elif mode=='run':asyncio.run(run())
    elif mode=='regression':regression()
    else:raise ValueError('unknown_mode')
