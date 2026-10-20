from pathlib import Path
R=Path(__file__).parent/'java'
p=R/'MemoryDailyWorker.java';s=p.read_text(encoding='utf-8').replace("m.recall_allowed=TRUE AND m.kind IN('dialogue','dialogue_end','habit_analysis')","m.recall_allowed=TRUE AND m.kind IN('dialogue','dialogue_assistant','dialogue_end','tool_result','habit_analysis')");p.write_text(s,encoding='utf-8')
p=R/'MemoryMaterialPolicy.java';s=p.read_text(encoding='utf-8');s=s.replace('''if(!"dialogue".equals(row.get("kind")))continue;
            String content=Objects.toString(row.get("content"),"");
            if(!RecentArchiveService.factualUser(content))continue;''','''if("dialogue_end".equals(row.get("kind")))continue;
            String content=Objects.toString(row.get("content"),"");
            if(content.contains("[来源:") || content.contains("[来源：") || content.contains("[本轮可信") || content.contains("\\\"tool_calls\\\"") || ("tool_result".equals(row.get("kind")) && (content.contains("\\\"source\\\":\\\"local\\\"") || content.contains("\\\"source\\\": \\\"local\\\""))))continue;''');p.write_text(s,encoding='utf-8')
# Hello must reach the device before vision initialize; preserve auth guards.
p=Path(__file__).parent/'candidate/core/handle/helloHandle.py';s=p.read_text(encoding='utf-8')
start=s.index('            track_outbound_task(\n                conn, asyncio.create_task(send_mcp_initialize_message(conn))')
end=s.index('\n\n    trace.mark',start)
s=s[:start]+s[end:]
s=s.replace('    await guarded_ws_send(\n        conn,\n        json.dumps(conn.welcome_msg),','    hello_sent=await guarded_ws_send(\n        conn,\n        json.dumps(conn.welcome_msg),',1)
needle='''        msg_type="hello",
    )'''
s=s.replace(needle,needle+'''
    if hello_sent and features and features.get('mcp'):
        track_outbound_task(conn,asyncio.create_task(send_mcp_initialize_message(conn)))
        track_outbound_task(conn,asyncio.create_task(send_mcp_tools_list_request(conn)))''',1)
p.write_text(s,encoding='utf-8')
p=Path(__file__).parent/'candidate/core/utils/vision_capability.py';s=p.read_text(encoding='utf-8').replace('''        "expires_at": expires_at,''','''        "expires_at": expires_at,
        "session_id": session_id or "",''');p.write_text(s,encoding='utf-8')
print('compatible transcript filtering and initialization ordering ready')
