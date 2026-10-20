from pathlib import Path
root=Path(__file__).parent/'candidate'
p=root/'main/xiaozhi-server/app.py';s=p.read_text(encoding='utf-8')
anchor='@broadcast_app.post("/api/v1/device/send")'
new='''@broadcast_app.post("/api/v1/habit/sync")
async def api_habit_sync(request: Request):
    cfg = getattr(request.app.state, "config", None) or {}
    expected, reason = service_auth.get_service_secret(cfg)
    presented = service_auth.extract_bearer_token(request.headers.get("authorization"))
    if service_auth.query_has_forbidden_auth_keys(request.query_params) or not expected or not presented or not service_auth.verify_bearer_service_secret(presented, expected):
        return _device_send_unauthorized("habit_sync_auth")
    try: body = await request.json()
    except Exception: return _device_send_bad_request("invalid_json", "Invalid JSON")
    if not isinstance(body, dict) or set(body) != {"habit_id"} or type(body.get("habit_id")) is not int or not 1 <= body["habit_id"] <= 2147483647:
        return _device_send_bad_request("invalid_habit_id", "Only a positive habit_id is allowed")
    from core.utils.habit_sync import synchronize_habit
    try:
        result = await synchronize_habit(cfg, getattr(request.app.state, "ws_server", None), body["habit_id"])
    except Exception as exc:
        logger.bind(tag=TAG).warning(f"[habit_sync] failed error_type={type(exc).__name__}")
        return JSONResponse(status_code=503, content={"ok":False,"error":"management_unavailable"})
    logger.bind(tag=TAG).info(f"[habit_sync] id={body['habit_id']} state={result.get('sync_state')} reason={result.get('error') or 'ok'}")
    return JSONResponse(content=result)


'''
assert anchor in s;p.write_text(s.replace(anchor,new+anchor),encoding='utf-8')
# Keep existing public MCP names, but do not permit untrusted MCP arguments to claim an account.
p=root/'gateway/tools/habit_tool.py';s=p.read_text(encoding='utf-8')
start=s.index('# ---------------------------------------------------------------------------\n# 辅助：读取副模型配置')
end=s.index('# ---------------------------------------------------------------------------\n# MCP 工具：habit_create',start)
s=s[:start]+'''async def _sync_habit_to_device(habit: dict) -> bool:
    secret = os.environ.get("HABIT_SERVICE_SECRET", "").strip()
    if not secret:
        logger.error("habit_tool: service_auth_unconfigured")
        return False
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(os.environ.get("HABIT_SYNC_URL", "http://127.0.0.1:8006/api/v1/habit/sync"),
                headers={"Authorization": "Bearer " + secret}, json={"habit_id": int(habit["id"])})
            body = r.json() if r.status_code == 200 else {}
            ok = body.get("ok") is True and body.get("sync_state") == "synced" and body.get("sync_id") == str(habit["id"]) and isinstance(body.get("content_hash"), str) and len(body["content_hash"]) == 64 and type(body.get("device_rule_id")) is int
            logger.info("habit_tool: sync id=%s state=%s reason=%s", habit["id"], body.get("sync_state", "pending"), body.get("error") or ("ok" if ok else "http_"+str(r.status_code)))
            return ok
    except Exception as exc:
        logger.warning("habit_tool: sync id=%s error_type=%s", habit["id"], type(exc).__name__)
        return False


'''+s[end:]
# Stop generating unattached records and cross-account list disclosures.
start=s.index('    if not description or not description.strip():',s.index('async def habit_create('))
end=s.index('# ---------------------------------------------------------------------------\n# MCP 工具：habit_list_manual',start)
s=s[:start]+'''    return mcp_error("该网页习惯入口需要账号授权，不能根据模型参数猜测账号。语音创建请使用当前设备的 habit.learn；网页创建请明确选择设备和接收人。")


'''+s[end:]
start=s.index('    pool = await _get_pool()',s.index('async def habit_list_manual('));end=s.index('# ---------------------------------------------------------------------------\n# 后台调度器',start)
s=s[:start]+'''    return mcp_error("请使用当前设备的 habit.list，或在网页查看当前账号的习惯；不支持跨账号查询。")


'''+s[end:]
start=s.index('async def habit_scheduler_loop()');end=s.index('# ---------------------------------------------------------------------------\n# 注册 MCP 工具',start)
s=s[:start]+'''async def habit_scheduler_loop() -> None:
    logger.info("habit_tool: authenticated background sync started; reminders are device-owned")
    while True:
        try:
            await _run_sync_task()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("habit_tool: cycle error_type=%s",type(exc).__name__)
        await asyncio.sleep(60)


async def _run_sync_task() -> None:
    pool = await _get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT id FROM sys_habits WHERE synced=0 AND sync_state<>'needs_binding' ORDER BY id")
            rows = await cur.fetchall()
    for row in rows:
        # Only the manager's version/hash-checked receipt handler changes synced.
        await _sync_habit_to_device(row)


'''+s[end:]
s=s.replace('目标设备ID（可选，不填则广播到所有设备）','目标设备ID；网页创建必须绑定当前账号所属设备')
s=s.replace('device_id: 目标设备ID（可选，空则广播）','device_id: 目标设备ID；禁止跨账号广播')
s=s.replace('创建后服务端会自动同步到设备端。','此网关入口无账号授权；语音使用设备 habit.learn，网页使用账号绑定入口。')
s=s.replace('2. habit_list_manual — MCP 工具，查询手动习惯列表（供 Web 界面使用）','2. 网页习惯由管理 API 负责账号授权')
s=s.replace('   - 将 synced=0 的习惯同步到设备端（调用 habit.learn）\n   - 检查到点习惯，调用 LLM 生成鼓励语，通过 TTS 广播 + UI 弹窗提醒','   - 将待同步记录 ID 提交到带 Bearer 认证的私有同步入口\n   - 不承担定时提醒、鼓励语、TTS 广播或 UI 弹窗')
p.write_text(s,encoding='utf-8')
