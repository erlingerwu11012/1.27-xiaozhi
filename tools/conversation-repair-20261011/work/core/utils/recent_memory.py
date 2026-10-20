"""Actor-bound local archive lookup, then optional paid cloud fallback."""
import asyncio
from core.utils.person_identity import current_turn


async def search(conn, query):
    actor = current_turn(conn)
    if not actor or not actor.eligible:
        return {"status": "identity_unknown", "text": ""}
    if not isinstance(query, str) or not query.strip() or len(query) > 2048:
        return {"status": "invalid_query", "text": ""}
    from config.manage_api_client import ManageApiClient
    try:
        local = await ManageApiClient(conn.config).request("POST", "person-memory/internal/recent",
                    json={"actor": actor.payload(), "query": query}, timeout=1)
    except Exception:
        local = {"text": "", "status": "temporarily_unavailable"}
    # Explicit suppression or stale authority must not fall through to cloud.
    if local.get("status") in {"suppressed", "identity_stale"}:
        return {**local, "text": str(local.get("text") or "")[:3000], "source": "local"}
    if local.get("reliable") and local.get("text"):
        return {**local,"text":str(local["text"])[:3000],"source":"local"}
    provider=getattr(conn,"memory",None)
    if getattr(provider,"personal",False) and actor.cloud_eligible:
        cloud=await provider.search(conn,query)
        return {**cloud,"text":str(cloud.get("text") or "")[:1500],"source":"cloud"}
    return {"status":"not_found","text":"","source":"local"}


async def add(conn,fact):
    actor=current_turn(conn)
    if not actor or not actor.eligible:return {'status':'identity_unknown'}
    from core.utils.tool_harness.memory_policy import normalize_fact
    if not isinstance(fact,str) or not fact.strip() or len(fact)>1024 or normalize_fact(fact)!=fact.strip():
        return {'status':'error','errorCode':'invalid_fact','message':'没有获得可保存的明确事实。'}
    from config.manage_api_client import ManageApiClient
    result=await ManageApiClient(conn.config).request('POST','person-memory/internal/add',
        json={'actor':actor.payload(),'fact':fact.strip()},timeout=3)
    if not isinstance(result,dict) or result.get('local_applied') is not True:
        return {'status':'error','message':'没有确认这条事实保存成功。'}
    from core.utils.person_short_memory import invalidate,revision
    invalidate(actor)
    if hasattr(conn,'dialogue'):
        conn.dialogue.invalidate_summary()
        conn.dialogue.source_revision=revision(actor)
    return {**result,'ok':True,'operation':'add'}


async def override(conn, action, match="", replacement=None, record_id="", expected_version=""):
    actor=current_turn(conn)
    if not actor or not actor.eligible:return {"status":"identity_unknown"}
    if action not in {'correct','forget'} or not isinstance(match,str) or (not match and not record_id) or len(match)>1024:
        return {'status':'error','errorCode':'invalid_memory_match','message':'请先确认要修改的单条记忆。'}
    if action=='correct' and (not isinstance(replacement,str) or not replacement.strip() or len(replacement)>2048):
        return {'status':'error','message':'新的记忆内容无效。'}
    from config.manage_api_client import ManageApiClient
    result=await ManageApiClient(conn.config).request('POST','person-memory/internal/override',
        json={'actor':actor.payload(),'action':action,'match':match,'replacement':replacement,'recordId':record_id,'expectedVersion':expected_version},timeout=3)
    match=result.get('resolved_match',match) if isinstance(result,dict) else match
    if not isinstance(result,dict) or (result.get('local_applied') is not True and result.get('status') not in {'accepted','queued'}):
        return {'status':'error','message':'这次没有确认记忆修改成功。'}
    from core.utils.person_material_outbox import material_outbox
    material_outbox.suppress(actor,match)
    from core.utils.person_short_memory import invalidate,revision
    invalidate(actor)
    conn.dialogue.invalidate_summary()
    # Invalidate only matching facts, not the ongoing conversation.
    kept=[]
    for message in conn.dialogue.dialogue:
        text=str(getattr(message,'content','') or '')
        if message.role=='system':
            kept.append(message)
        elif match!='*':
            variants=[match]
            if action=='forget' and match.startswith('我的') and len(match)>6:variants.append(match[2:])
            for value in variants:
                if value in text:text=text.replace(value,replacement if action=='correct' else '（该个人信息已按要求移除）')
            message.content=text
            kept.append(message)
        elif not getattr(message,'memory_retrieval',False):
            # Keep conversational scaffolding; removed facts must not be recalled.
            if message.role in {'user','assistant'} and not getattr(message,'tool_calls',None):
                message.content='（此前个人内容已按要求从本地对话召回中移除）'
            kept.append(message)
    conn.dialogue.dialogue[:]=kept
    conn.dialogue.source_revision=revision(actor)
    provider=getattr(conn,'memory',None)
    if provider:
        provider.short_memory=''
        if hasattr(provider,'_portraits'):provider._portraits.pop(actor.key,None)
        if hasattr(provider,'_queries'):provider._queries.pop(actor.turn_id,None)
    if isinstance(result,dict) and result.get('local_applied') is True:
        return {**result,'ok':True,'operation':action}
    return {'status':'accepted','cloud_sync':'pending','operation':action}
