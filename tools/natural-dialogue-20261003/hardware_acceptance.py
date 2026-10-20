"""Authorized, reversible acceptance of only ac:a7:04:fd:20:2c."""
import json, socket, sys, time, re
from pathlib import Path
OUT=Path('/root/prjs/tmp/natural-dialogue-20261003')
def probe(payload):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as sock:
        sock.settimeout(80);sock.connect(str(OUT/'probe.sock'));sock.sendall((json.dumps(payload,ensure_ascii=False)+'\n').encode())
        chunks=[]
        while True:
            part=sock.recv(65536)
            if not part:break
            chunks.append(part)
            if b'\n' in part:break
    return json.loads(b''.join(chunks))
report={'device_mac':'ac:a7:04:fd:20:2c','calls':[],'restoration':{},'temporary_record':None}
def call(name,args=None,query=''):
    start=time.perf_counter();result=probe({'op':'call','name':name,'arguments':args or {},'query':query})
    report['calls'].append({'name':name,'arguments':args or {},'query':query,'receipt':result,'elapsed_ms':round((time.perf_counter()-start)*1000)})
    (OUT/'hardware-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    assert result.get('online'),result
    return result
def body(result):
    value=result.get('result')
    if isinstance(value,dict):return value
    try:return json.loads(value)
    except (TypeError,ValueError):return {}
catalog=probe({'op':'catalog'})
if '--wait' in sys.argv:
    deadline=time.monotonic()+180
    while not (catalog.get('online') and catalog.get('ready')) and time.monotonic()<deadline:
        time.sleep(1);catalog=probe({'op':'catalog'})
assert catalog.get('online') and catalog.get('ready'),catalog
(OUT/'device-live-catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2))
report['persona_before']=catalog['persona_sha256']
names={t['function']['name'] for t in catalog['device_tools']}
status=call('self_get_device_status')
initial=body(status)
print(json.dumps({'online':True,'tool_count':len(names),'preview_available':bool({'camera_open','camera_close'}<=names),'initial_status':initial,'persona_sha256':catalog['persona_sha256'],'identity_mode':catalog.get('identity_mode')},ensure_ascii=False),flush=True)
if '--inspect' in sys.argv:sys.exit(0)
volume=initial.get('audio_speaker',{}).get('volume',initial.get('audio_speaker',{}).get('output_volume'))
brightness=initial.get('screen',{}).get('brightness')
assert type(volume)is int and type(brightness)is int,'missing_current_values'
try:
    target=volume-5 if volume>=10 else volume+5
    reply=call('self_audio_speaker_set_volume',{'volume':target},f'把音量调到{target}')
    current=body(call('self_get_device_status'))
    actual=current.get('audio_speaker',{}).get('volume',current.get('audio_speaker',{}).get('output_volume'))
    assert actual==target,'volume_readback_mismatch'
    target_b=brightness-5 if brightness>=55 else brightness+5
    call('self_screen_set_brightness',{'brightness':target_b},f'把亮度调到{target_b}')
    assert body(call('self_get_device_status')).get('screen',{}).get('brightness')==target_b,'brightness_readback_mismatch'
    label='自然对话验收-'+time.strftime('%H%M%S')
    before=call('note_list');report['notes_before_sha256']=before.get('list_sha256')
    reminder=call('add_reminder',{'text':'十分钟后提醒我'+label},'十分钟后提醒我'+label)
    created='提醒已设好' in str(reminder.get('response'))
    report['temporary_record']={'label':label,'created':created,'cleaned':False}
    assert created,'reminder_not_confirmed'
    listed=call('note_list');entries=listed.get('test_entries',[])
    entry=next((line for line in entries if label in line),None)
    assert entry,'created_note_not_listed'
    index=int(re.match(r'^(\d+)\.',entry)[1])
    # Fresh read and unchanged-list check before deleting by the firmware index.
    check=call('note_list')
    assert check.get('list_sha256')==listed.get('list_sha256'),'note_list_changed_no_cleanup'
    deleted=call('note_delete',{'index':index},'删除测试便签'+label)
    after=call('note_list')
    assert not any(label in line for line in after.get('test_entries',[])),'test_note_still_present'
    assert '[NOTE_DELETED]' in str(deleted.get('result') or deleted.get('response')),'cleanup_not_confirmed'
    report['temporary_record']['cleaned']=True
    report['success']=True
except Exception as exc:
    report.update(success=False,error_type=type(exc).__name__,error_code=str(exc) if re.fullmatch('[a-z_]+',str(exc)) else 'see_receipts')
finally:
    call('self_audio_speaker_set_volume',{'volume':volume},f'把音量调到{volume}')
    call('self_screen_set_brightness',{'brightness':brightness},f'把亮度调到{brightness}')
    restored=body(call('self_get_device_status'))
    report['restoration']={'volume':restored.get('audio_speaker',{}).get('volume',restored.get('audio_speaker',{}).get('output_volume'))==volume,'brightness':restored.get('screen',{}).get('brightness')==brightness}
    report['persona_after']=probe({'op':'catalog'})['persona_sha256']
    report['persona_unchanged']=report['persona_before']==report['persona_after']
    if report.get('success') and all(report['restoration'].values()):
        question='描述实际画面，不推测人的身份'
        photo=call('self_camera_take_photo',{'question':question},'拍一张照片，'+question)
        # Existing VLM intentionally replies directly with the real image result.
        report['photo_success']=photo.get('action') in ('REQLLM','RESPONSE') and bool(photo.get('result') or photo.get('response'))
        report['success']=report['success'] and report['photo_success']
    (OUT/'hardware-acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:report[k] for k in ('success','restoration','temporary_record','persona_unchanged')},ensure_ascii=False))
