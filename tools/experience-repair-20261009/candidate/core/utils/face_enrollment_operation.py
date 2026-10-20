"""Track device capture acceptance separately from draft/web commitment."""
import asyncio
import json
import time
import uuid
from core.utils.tool_result import DeviceToolError, parse_payload, require_enrollment_accepted

TERMINAL = {'draft_ready','cancelled','failed','expired','idle','unconfirmed','timeout'}


async def start_operation(conn, client, invoke, tool_name, args, timeout):
    lock = getattr(conn,'_face_enrollment_start_lock',None)
    if lock is None:
        lock = conn._face_enrollment_start_lock = asyncio.Lock()
    async with lock:
        previous = getattr(conn,'face_enrollment_operation',None)
        if isinstance(previous,dict) and previous.get('state') not in TERMINAL:
            raise DeviceToolError('already_active','人脸采集正在进行。')
        if not await client.wait_ready() or client.resolve_tool_name(tool_name) is None:
            raise DeviceToolError('tool_unavailable')
        # Explicit user enrollment owns this dialogue transition; do not close the device WS.
        from core.handle.sendAudioHandle import send_tts_message
        from core.handle.abortHandle import handleAbortMessage
        if getattr(conn,'client_is_speaking',False) and callable(getattr(conn,'clear_queues',None)):
            await handleAbortMessage(conn)
        asr = getattr(conn,'asr',None)
        if callable(getattr(asr,'stop_listening',None)):
            await asr.stop_listening(conn)
        if getattr(conn,'tts',None) is not None:
            await send_tts_message(conn,'stop')
        operation = {'operation_id':uuid.uuid4().hex,'session_id':getattr(conn,'session_id',''),
                     'state':'requesting','started_at':time.monotonic(),
                     'front_only': bool(getattr(conn,'face_enrollment_front_only', False))}
        conn.face_enrollment_operation = operation
        try:
            result = await invoke(conn,client,tool_name,args,timeout)
            ack = require_enrollment_accepted(result)
        except BaseException:
            # The device may have accepted a timed-out request. Never retry automatically.
            operation['state'] = 'unconfirmed'
            raise
        operation['state'] = 'accepted'
        operation['device_operation_id'] = ack.get('operation_id')
        operation['legacy_ack'] = bool(ack.get('legacy_ack'))
        if client.resolve_tool_name('camera.face.enroll.status'):
            old = getattr(conn,'_face_enrollment_monitor',None)
            if old and not old.done():
                old.cancel()
            conn._face_enrollment_monitor = asyncio.create_task(monitor(conn,client,invoke,operation))
        return json.dumps({'accepted':True,'state':'accepted','operation_id':operation['operation_id'],
                           'message':'设备已接受采集请求，尚未确认拍摄或入库。'},ensure_ascii=False)


async def monitor(conn, client, invoke, operation):
    try:
        limit = 240 if operation.get('front_only') else 180
        loops = int(limit / 2) + 5
        for _ in range(loops):
            await asyncio.sleep(2)
            if time.monotonic() - operation['started_at'] > limit:
                break
            if conn.face_enrollment_operation is not operation or operation['session_id'] != getattr(conn,'session_id','') or client.closed:
                return
            if operation['state'] in TERMINAL:
                return
            value = parse_payload(await invoke(conn,client,'camera.face.enroll.status','{}',10))
            if not isinstance(value,dict) or not isinstance(value.get('state'),str):
                operation.update(state='unconfirmed', errorCode='invalid_tool_result')
                return
            expected = operation.get('device_operation_id')
            if expected and value.get('operation_id') != expected:
                continue
            state = value['state']
            if state != operation['state']:
                conn.logger.bind(tag='face_enrollment').info(f'[FACE_ENROLL phase] operation={operation["operation_id"]} state={state} accepted_count={value.get("accepted_count")}')
            operation.update(state=state, accepted_count=value.get('accepted_count'),
                             errorCode=value.get('errorCode') or value.get('last_error_code'))
            if state in TERMINAL:
                return
        operation.update(state='timeout', errorCode='request_timeout')
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        operation.update(state='unconfirmed',errorCode=getattr(exc,'code','status_unavailable'))


def cancelled_operation(conn):
    operation = getattr(conn,'face_enrollment_operation',None)
    if isinstance(operation,dict):
        operation['state'] = 'cancelled'
    task = getattr(conn,'_face_enrollment_monitor',None)
    if task and not task.done():
        task.cancel()
