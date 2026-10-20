from pathlib import Path
R=Path(r'E:/github/github_code/all/4.30');W=R/'tools/hardware-repair-20261009/work'
def edit(p,old,new):
 s=p.read_text();assert old in s,str(p);p.write_text(s.replace(old,new))
edit(R/'main/mcp_tools/mcp_tools_alarm.cc','            AlarmManager::GetInstance().Delete(id);','''            if (!AlarmManager::GetInstance().Delete(id)) return McpError{"闹钟删除保存失败", "storage_failed"};
            ReminderCoordinator::GetInstance().InvalidateInformation("闹钟列表", owner);''')
p=R/'main/mcp_server.cc';s=p.read_text();s=s.replace('\\"habitSync\\":1','\\"habitSync\\":1,\\"visionStatus\\":1')
pos=s.index('    } else if (m == "identity/sync")')
s=s[:pos]+'''    } else if (m == "vision/status" || m == "vision/refresh") {
        auto& store = VisionCredentialStore::GetInstance();
        auto params = cJSON_GetObjectItem(json, "params");
        auto sid = cJSON_GetObjectItem(params, "session_id");
        const auto session = Application::GetInstance().GetAudioSessionId();
        if (!store.IsGenerationAccepting(connection_generation) || session.empty() ||
            !cJSON_IsString(sid) || session != sid->valuestring) {
            ReplyError(id, "vision_session_mismatch"); return;
        }
        if (m == "vision/refresh") {
            auto cap = cJSON_GetObjectItem(params, "vision");
            auto url = cJSON_GetObjectItem(cap, "url");
            auto identity = cJSON_GetObjectItem(cap, "identity_url");
            auto token = cJSON_GetObjectItem(cap, "token");
            auto expires = cJSON_GetObjectItem(cap, "expires_at");
            auto cap_session = cJSON_GetObjectItem(cap, "session_id");
            if (!cJSON_IsString(url) || !cJSON_IsString(identity) || !cJSON_IsString(token) ||
                !cJSON_IsString(cap_session) || session != cap_session->valuestring || !cJSON_IsNumber(expires)) {
                ReplyError(id, "invalid_vision_capability"); return;
            }
            store.ApplyInitializeVision(connection_generation, url->valuestring, identity->valuestring,
                token->valuestring, session, static_cast<int64_t>(expires->valuedouble));
        }
        cJSON* result = cJSON_CreateObject();
        cJSON_AddStringToObject(result, "session_id", session.c_str());
        cJSON_AddNumberToObject(result, "generation", connection_generation);
        cJSON_AddBoolToObject(result, "explain_ready", store.IsExplainReady());
        cJSON_AddBoolToObject(result, "identity_ready", store.IsIdentityReady());
        cJSON_AddStringToObject(result, "explain_reason", store.ExplainNotReadyReason().c_str());
        cJSON_AddStringToObject(result, "identity_reason", store.IdentityNotReadyReason().c_str());
        char* encoded = cJSON_PrintUnformatted(result);
        ReplyResult(id, encoded ? encoded : "{}");
        cJSON_free(encoded); cJSON_Delete(result);
'''+s[pos:];p.write_text(s)
# New card tool contract and enforcement.
p=W/'core/utils/tool_harness/contracts.py';s=p.read_text().replace("'reminder_next','reminder_stop_broadcast','reminder_action'", "'reminder_next','reminder_stop_broadcast','reminder_action','reminder_close_current'")
s=s.replace("PREREQUISITES={", "LABELS['reminder_close_current']='关闭当前卡片'\nPREREQUISITES={'reminder_close_current':['reminder_get_current'],")
s=s.replace("    elif name=='reminder_action':",'''    elif name=='reminder_close_current':
        if isinstance(body,dict) and body.get('ok') is True and body.get('closed') is True and body.get('business_unchanged') is True and all(body.get(k)==args.get(k) for k in ('instance_id','revision')):
            return out('completed','卡片已关闭，事项仍保留。')
    elif name=='reminder_action':''');p.write_text(s)
p=W/'core/utils/tool_harness/runtime.py';s=p.read_text().replace("if name=='reminder_action':", "if name in {'reminder_action','reminder_close_current'}:")
s=s.replace("'reminder_get_current','reminder_list_pending','reminder_action'", "'reminder_get_current','reminder_list_pending','reminder_action','reminder_close_current'")
s=s.replace("contextual=['reminder_get_current','reminder_action']", "contextual=['reminder_get_current','reminder_action','reminder_close_current']")
s=s.replace('当前卡片“先别响”', '明确说关闭当前卡片/把这个卡片关了只关闭展示，用reminder_close_current，先reminder_get_current读取ID和revision；不得替代成primary完成或永久删除。当前卡片“先别响”')
s=s.replace("        if card_reference and card_instruction:targets.add('reminder_action')", "        if card_reference and card_instruction:targets.add('reminder_action')\n        if re.search(r'卡片.{0,8}(?:关|关闭|收起)|(?:关|关闭|收起).{0,8}卡片',q) and not re.search(r'别关|不要关|不用关|怎么|如何',q):targets.discard('reminder_action');targets.add('reminder_close_current')")
s=s.replace("else not any(arguments.get('match','') in text for text in texts)", "else (not texts if arguments.get('match')=='*' else not any(arguments.get('match','') in text for text in texts))")
p.write_text(s)
# management-only vision readiness; capability-gated for old firmware.
p=W/'core/utils/vision_readiness.py';p.write_text('''import asyncio,time
from concurrent.futures import Future

async def ensure_vision(conn,identity=False):
    client=getattr(conn,'mcp_client',None)
    if not client or client.capabilities.get('experimental',{}).get('visionStatus',0)<1:return None
    session=getattr(conn,'session_id','')
    async def request(method,params):
        from core.providers.tools.device_mcp.mcp_handler import send_mcp_message
        call_id=await client.get_next_id();future=Future()
        await client.register_call_result_future(call_id,future)
        try:
            await send_mcp_message(conn,{'jsonrpc':'2.0','id':call_id,'method':method,'params':params})
            result=await asyncio.wait_for(asyncio.wrap_future(future),3)
            if not isinstance(result,dict) or result.get('session_id')!=session or getattr(conn,'session_id','')!=session:raise ValueError('vision_session_mismatch')
            return result
        finally:
            client.call_results.pop(call_id,None)
    state=await request('vision/status',{'session_id':session})
    key='identity_ready' if identity else 'explain_ready'
    if state.get(key) is True:return state
    reason=state.get('identity_reason' if identity else 'explain_reason','unknown')
    if time.monotonic()-getattr(conn,'_vision_refresh_at',0)<60:return state
    if reason in {'connection_closed','vision_session_mismatch'}:return state
    from core.utils.vision_capability import build_vision_capabilities
    from core.utils.account_identity import resolve_face_account_id
    cap=build_vision_capabilities(conn.config,device_id=conn.device_id,account_id=resolve_face_account_id(conn=conn) or '',session_id=session)
    if not cap.ok:return state
    conn._vision_refresh_at=time.monotonic()
    return await request('vision/refresh',{'session_id':session,'vision':cap.vision})
''')
# invoke before dispatch (same current connection), no identity permission relaxation.
p=W/'core/utils/tool_harness/runtime.py';s=p.read_text();needle='                    result=await self.dispatch(name,arguments,scope,turn,epoch,tools,deadline)';assert needle in s;s=s.replace(needle,'''                    if name in {'self_camera_take_photo','self_camera_identify_person'}:
                        from core.utils.vision_readiness import ensure_vision
                        try:
                            ready=await ensure_vision(self.conn,name=='self_camera_identify_person')
                            if ready is not None:self.observe('vision_readiness',explain_ready=ready.get('explain_ready'),identity_ready=ready.get('identity_ready'),reason=ready.get('identity_reason' if name=='self_camera_identify_person' else 'explain_reason'))
                        except Exception as exc:self.observe('vision_readiness',reason=type(exc).__name__)
'''+needle);p.write_text(s)
print('management vision and harness card patches applied')
