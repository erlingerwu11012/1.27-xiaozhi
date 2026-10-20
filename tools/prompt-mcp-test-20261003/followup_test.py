"""Bounded follow-up; real model, read-only live MCP, synthetic device transport.

Reuses setup from run_test.py but preserves the initial report separately.
No production configuration changes or physical device actions.
"""
from pathlib import Path

test_dir = Path('/root/prjs/tmp/prompt-mcp-test-20261003')
setup = (test_dir / 'run_test.py').read_text().split('messages_by_case={}')[0]
setup = setup.replace("'report.json'", "'followup-report.json'")
setup = setup.replace("'max_model_calls': 48", "'max_model_calls': 10")
setup = setup.replace("< 48, 'model_call_guard'", "< 10, 'model_call_guard'")
setup = setup.replace('200000', '70000')
exec(compile(setup, str(test_dir / 'run_test.py'), 'exec'))

initial = json.loads((OUT / 'initial-report.json').read_text())
execution_rule = ('操作请求必须发出实际工具调用，正文中写工具名或说“已操作”不能代替调用。'
                  '能力缺失时不得调用功能不同的工具代替。否定、假设、引用和介绍不视为执行请求。')
camera_module = ('[摄像头能力]\n实时预览：camera_open打开，camera_close关闭；'
                 '静态拍照识别：self_camera_take_photo。名称仅在本轮工具列表实际提供时有效。'
                 '只在用户明确请求对应操作时调用。预览请求不能调用拍照工具；'
                 '拍照请求不能调用预览工具。能力缺失时说明不支持，不借助其他工具代替。')
revised = slim.replace('[工具与结果]\n', '[工具与结果]\n' + execution_rule + '\n')
revised += '\n\n' + camera_module
report['revision'] = {'label': 'slim_with_execution_guard_and_camera_module',
                      'execution_rule': execution_rule, 'camera_module': camera_module,
                      'system_characters': len(revised), 'deployed': False}
(OUT / 'revised-system.txt').write_text(revised)
save()

def request_bounded(label, messages, tool_defs):
    try:
        return completion(label, messages, tool_defs)
    except Exception as exc:
        report.setdefault('request_errors', []).append({
            'label': label, 'type': type(exc).__name__,
            'reason': str(exc) if isinstance(exc, AssertionError) else 'model_request_failed'})
        save()
        return None

for case_id in ['camera_open', 'camera_close', 'photo', 'camera_unavailable',
                'multiple', 'camera_close', 'camera_unavailable']:
    case = next(x for x in cases if x['id'] == case_id)
    offered = [t for t in normal_tools if t['function']['name'] not in case.get('without', [])]
    messages = [{'role': 'system', 'content': revised},
                {'role': 'user', 'content': context + '\n' + case['text']}]
    response = request_bounded('revised:' + case_id, messages, offered)
    if response is None:
        continue
    msg, usage, elapsed = response
    calls = calls_of(msg)
    errors = validate_case(case, calls)
    report['cases'].append({'variant': 'revised', 'case': case_id,
                            'input': case['text'], 'expected': case['expected'],
                            'calls': calls, 'text': msg.content, 'passed': not errors,
                            'errors': errors, 'usage': usage, 'seconds': elapsed})
    save()
    print('RETEST', case_id, 'PASS' if not errors else 'FAIL', flush=True)

async def live_selected_time(call):
    configs = json.loads((ROOT / 'data/.mcp_server_settings.json').read_text())['mcpServers']
    cfg = next(c for c in configs.values() if not c.get('disabled', False))
    client = ServerMCPClient(cfg)
    try:
        await asyncio.wait_for(client.initialize(), 20)
        result = await asyncio.wait_for(client.call_tool(call['name'], call['arguments']), 15)
        body = result.model_dump(mode='json')
        assert body.get('isError') is False, 'live_tool_error'
        report['live_mcp']['model_selected_execution'] = {
            'selection_from': 'initial slim world_time case',
            'name': call['name'], 'arguments': call['arguments'], 'result': body}
        save()
        return body
    finally:
        await client.cleanup()

# Receipts follow initial slim native calls and initial slim system, unchanged.
for case_id, outcome in [('volume', 'success'), ('reminder', 'failure'), ('world_time', 'success')]:
    row = next(x for x in initial['cases'] if x['variant'] == 'slim' and x['case'] == case_id)
    native_calls = row['calls']
    assert native_calls
    messages = [{'role': 'system', 'content': slim},
                {'role': 'user', 'content': context + '\n' + row['input']},
                {'role': 'assistant', 'content': row.get('text') or None,
                 'tool_calls': [{'id': c['id'], 'type': 'function', 'function': {
                     'name': c['name'], 'arguments': json.dumps(c['arguments'], ensure_ascii=False)}}
                     for c in native_calls]}]
    for call in native_calls:
        if case_id == 'world_time':
            body = asyncio.run(live_selected_time(call))
        elif outcome == 'failure':
            body = {'status': 'error', 'errorCode': 'connection_closed',
                    'message': '设备已离线，本次提醒未创建。'}
        else:
            body = {'status': 'success', 'volume': 30}
        messages.append({'role': 'tool', 'tool_call_id': call['id'],
                         'content': json.dumps(body, ensure_ascii=False)})
    response = request_bounded('receipt:' + case_id, messages, normal_tools)
    if response is None:
        continue
    msg, usage, elapsed = response
    text = msg.content or ''
    calls = calls_of(msg)
    if outcome == 'failure':
        passed = not calls and any(w in text for w in ['未', '没', '失败', '无法', '离线', '不能'])
    elif case_id == 'volume':
        passed = not calls and '30' in text
    else:
        returned_text = '\n'.join(x.get('text', '') for x in body.get('content', [])
                                   if x.get('type') == 'text')
        match_time = re.search(r'(\d{2}:\d{2}:\d{2})', returned_text)
        passed = not calls and bool(match_time) and match_time[1][:5] in text
    report['continuations'].append({'case': case_id, 'outcome': outcome,
                                    'transport': 'live MCP' if case_id == 'world_time' else 'synthetic receipt',
                                    'passed': passed, 'text': text, 'calls': calls,
                                    'usage': usage, 'seconds': elapsed})
    save()
    print('RECEIPT', case_id, 'PASS' if passed else 'FAIL', flush=True)

class SyntheticSocket:
    closed = False
    def __init__(self, client):
        self.client = client
        self.messages = []
        self.response = {'content': [{'type': 'text', 'text': '{"status":"success"}'}]}
    async def send(self, text):
        data = json.loads(text)
        self.messages.append(data)
        frame = data.get('payload', {})
        if frame.get('method') == 'tools/call':
            await self.client.resolve_call_result(frame['id'], copy.deepcopy(self.response))

async def protocol_tests():
    sys.path.insert(0, str(ROOT / 'test'))
    from local_active_test_util import bind_local_active_registry
    client, _ = await get_device_functions(device_fixture)
    ws = SyntheticSocket(client)
    conn = SimpleNamespace(mcp_client=client, websocket=ws, features={'mcp': True},
                           device_id='synthetic-prompt-test', session_id='test-session',
                           headers={}, logger=MagicMock(), last_activity_time=0.0)
    bind_local_active_registry(conn)
    for row in initial['cases'] + report['cases']:
        if row['variant'] not in {'slim', 'revised'}:
            continue
        for call in row.get('calls', []):
            if call['name'] not in client.tools:
                continue
            before = len(ws.messages)
            try:
                result = await call_mcp_tool(conn, client, call['name'],
                                            json.dumps(call['arguments']), timeout=2)
                actual = [x['payload']['params']['name'] for x in ws.messages[before:]
                          if x.get('payload', {}).get('method') == 'tools/call']
                expected = client.name_mapping[call['name']]
                passed = actual == [expected] and 'success' in str(result)
                report['protocol'].append({'variant': row['variant'], 'case': row['case'],
                                           'model_name': call['name'], 'raw_mcp_name': expected,
                                           'emitted_names': actual, 'passed': passed,
                                           'transport': 'synthetic websocket'})
            except Exception as exc:
                report['protocol'].append({'case': row['case'], 'passed': False,
                                           'error_type': type(exc).__name__})
    before = len(ws.messages)
    try:
        await call_mcp_tool(conn, client, 'invented_missing_tool', '{}', timeout=2)
        blocked = False
    except Exception:
        blocked = True
    report['protocol'].append({'case': 'reject_missing_name',
                               'passed': blocked and len(ws.messages) == before})
    ws.response = {'isError': True, 'content': [{'type': 'text', 'text':
        '{"status":"error","errorCode":"camera_busy","message":"synthetic_device_error"}'}]}
    try:
        result = await call_mcp_tool(conn, client, 'self_audio_speaker_set_volume',
                                    '{"volume":30}', timeout=2)
        preserved = 'synthetic_device_error' in str(result)
    except Exception as exc:
        from core.utils.tool_result import DeviceToolError
        preserved = (isinstance(exc, DeviceToolError) and exc.code == 'camera_busy'
                     and exc.device_message == 'synthetic_device_error')
    report['protocol'].append({'case': 'error_receipt_not_silent_success', 'passed': preserved})
    # A known tool from a different capability set must also be rejected.
    unavailable_client, _ = await get_device_functions([
        t for t in device_fixture if t['name'] not in {'camera.open', 'camera.close'}])
    unavailable_ws = SyntheticSocket(unavailable_client)
    unavailable_conn = SimpleNamespace(mcp_client=unavailable_client, websocket=unavailable_ws,
        features={'mcp': True}, device_id='synthetic-no-preview', session_id='test-session',
        headers={}, logger=MagicMock(), last_activity_time=0.0)
    bind_local_active_registry(unavailable_conn)
    try:
        await call_mcp_tool(unavailable_conn, unavailable_client, 'camera_open', '{}', timeout=2)
        rejected = False
    except ValueError:
        rejected = True
    report['protocol'].append({'case': 'reject_preview_absent_from_current_device_catalog',
                               'passed': rejected and not unavailable_ws.messages})
    await unavailable_client.close()
    await client.set_ready(False)
    before = len(ws.messages)
    try:
        await call_mcp_tool(conn, client, 'self_audio_speaker_set_volume', '{"volume":30}', timeout=2)
        rejected = False
    except Exception as exc:
        from core.utils.tool_result import DeviceToolError
        rejected = isinstance(exc, DeviceToolError) and exc.code == 'mcp_not_ready'
    report['protocol'].append({'case': 'reject_unsynchronized_catalog',
                               'passed': rejected and len(ws.messages) == before})
    await client.close()
    save()

asyncio.run(protocol_tests())
report['summary'] = {
    'revised_selection': {'passed': sum(x['passed'] for x in report['cases']), 'total': len(report['cases'])},
    'receipt_continuation': {'passed': sum(x['passed'] for x in report['continuations']), 'total': len(report['continuations'])},
    'synthetic_device_dispatch': {'passed': sum(x['passed'] for x in report['protocol']), 'total': len(report['protocol'])}}
report['usage_totals'] = {k: sum((x.get('usage') or {}).get(k, 0)
                                for x in report['cases'] + report['continuations'])
                          for k in ['prompt_tokens', 'completion_tokens', 'total_tokens']}
report['finished_at_utc'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
save()
provider.client.close()
print('SUMMARY', json.dumps(report['summary']), flush=True)
