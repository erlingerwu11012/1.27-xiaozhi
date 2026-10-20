from pathlib import Path
R=Path(__file__).parent/'java'
p=R/'RecentArchiveService.java';s=p.read_text(encoding='utf-8-sig')
s=s.replace("WHERE account_id=? AND user_id=? AND generation=?\",Date.class", "WHERE account_id=? AND user_id=? AND generation=? AND match_text='*'\",Date.class")
s=s.replace('if(text.isEmpty() || text.matches', 'if(text.contains("[来源:") || text.contains("[来源：") || text.contains("[本轮可信") || text.contains("\\\"tool_calls\\\"") || text.contains("[工具 Harness"))return false;\n        if(text.matches("(?s).*(忘掉|忘记|删掉.*记忆|更正.*记忆|纠正.*记忆).*"))return false;\n        if(text.isEmpty() || text.matches')
start=s.index('    @Transactional\n    public Map<String,Object> search(')
s=s[:start]+'''    @Transactional
    public Map<String,Object> search(PersonTurnDTO actor,String query) {
        identities.lock(actor.getAccountId());memory.validateActor(actor,false);
        if(query==null || query.isBlank() || query.length()>2048)throw new RenException("检索内容无效");
        Set<String> terms=terms(query);
        Date cutoff=new Date(System.currentTimeMillis()-86400000L);
        var rows=jdbc.queryForList("SELECT id,turn_id,content,created_at FROM ai_agent_chat_history WHERE account_id=? AND person_id=? AND agent_id=? AND default_generation=? AND recall_allowed=TRUE AND chat_type=1 AND created_at>=? AND (turn_id IS NULL OR turn_id<>?) ORDER BY created_at DESC,id DESC LIMIT 1000",actor.getAccountId(),actor.getPersonId(),actor.getAgentId(),actor.getGeneration(),cutoff,actor.getTurnId());
        for(var row:rows)row.put("record_id","archive:"+row.get("id"));
        var pending=jdbc.queryForList("SELECT id,turn_id,content,created_at FROM ai_person_material WHERE account_id=? AND user_id=? AND agent_id=? AND generation=? AND recall_allowed=TRUE AND kind='dialogue' AND created_at>=? AND turn_id<>? ORDER BY id DESC LIMIT 1000",actor.getAccountId(),actor.getPersonId(),actor.getAgentId(),actor.getGeneration(),cutoff,actor.getTurnId());
        for(var row:pending){row.put("record_id","material:"+row.get("id"));rows.add(row);}
        var changes=jdbc.queryForList("SELECT id,action,match_text,replacement,state,created_at FROM ai_memory_override WHERE account_id=? AND user_id=? AND generation=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        for(var change:changes)if("correct".equals(change.get("action")) && change.get("replacement")!=null){
            var row=new HashMap<String,Object>();row.put("content",change.get("replacement"));row.put("created_at",change.get("created_at"));row.put("record_id","override:"+change.get("id"));row.put("authoritative",true);rows.add(row);
        }
        rows.sort(Comparator.<Map<String,Object>>comparingLong(r->sourceTime(r.get("created_at"))).reversed());
        rows.sort(Comparator.<Map<String,Object>>comparingInt(r->score(Objects.toString(r.get("content"),""),terms)).reversed());
        List<Map<String,Object>> items=new ArrayList<>();Set<String> seen=new HashSet<>();
        for(var row:rows){
            String value=Objects.toString(row.get("content"),"").strip();
            if(items.size()>=5)break;
            if(!factualUser(value) || value.length()>1024 || score(value,terms)<Math.min(2,terms.size()) || terms.isEmpty())continue;
            if(!Boolean.TRUE.equals(row.get("authoritative")) && changes.stream().anyMatch(c->sourceTime(c.get("created_at"))>=sourceTime(row.get("created_at")) && ("*".equals(c.get("match_text")) || value.contains(Objects.toString(c.get("match_text"),"")))))continue;
            if(!seen.add(value))continue;
            var item=new LinkedHashMap<String,Object>();item.put("record_id",row.get("record_id"));item.put("text",value);item.put("source","local_user_fact");item.put("created_at",sourceTime(row.get("created_at")));items.add(item);
        }
        boolean blocked=changes.stream().anyMatch(c->!"complete".equals(c.get("state")));
        String text=String.join("；",items.stream().map(i->Objects.toString(i.get("text"),"")).toList());
        return Map.of("text",text,"items",items,"reliable",!items.isEmpty(),"status",items.isEmpty()?(blocked?"suppressed":"not_found"):"ok","source","local");
    }
}
'''
p.write_text(s,encoding='utf-8')
p=R/'PersonMemoryService.java';s=p.read_text(encoding='utf-8-sig')
s=s.replace('MAX(UNIX_TIMESTAMP(created_at)*1000) FROM ai_memory_override WHERE account_id=? AND user_id=? AND generation=?"','MAX(UNIX_TIMESTAMP(created_at)*1000) FROM ai_memory_override WHERE account_id=? AND user_id=? AND generation=? AND match_text=\'*\'"')
s=s.replace('public void override(PersonTurnDTO actor,String action,String match,String replacement)', 'public Map<String,Object> override(PersonTurnDTO actor,String action,String match,String replacement)')
s=s.replace('if(!Set.of("forget","correct").contains(action)', 'if("correct".equals(action) && (replacement==null || replacement.isBlank()))throw new RenException("新的记忆内容不能为空");\n        if(!Set.of("forget","correct").contains(action)')
s=s.replace('''        // Invalidate all old turn sources, including adjacent replies, before cloud cleanup.
        jdbc.update("UPDATE ai_agent_chat_history SET recall_allowed=FALSE WHERE account_id=? AND person_id=? AND default_generation=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());''','''        // Suppress only affected facts. Keep raw material as an auditable record.
        if("*".equals(match))jdbc.update("UPDATE ai_agent_chat_history SET recall_allowed=FALSE WHERE account_id=? AND person_id=? AND default_generation=? AND agent_id=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),actor.getAgentId());
        else jdbc.update("UPDATE ai_agent_chat_history SET recall_allowed=FALSE WHERE account_id=? AND person_id=? AND default_generation=? AND agent_id=? AND LOCATE(?,content)>0",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),actor.getAgentId(),match);''')
start=s.index('        if("*".equals(match)) jdbc.update("DELETE FROM ai_person_material')
end=s.index('        jdbc.update("UPDATE ai_memory_task',start)
s=s[:start]+'''        if("*".equals(match))jdbc.update("UPDATE ai_person_material SET recall_allowed=FALSE WHERE account_id=? AND user_id=? AND generation=? AND agent_id=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),actor.getAgentId());
        else jdbc.update("UPDATE ai_person_material SET recall_allowed=FALSE WHERE account_id=? AND user_id=? AND generation=? AND agent_id=? AND LOCATE(?,content)>0",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),actor.getAgentId(),match);
'''+s[end:]
needle='''        jdbc.update("UPDATE ai_memory_task SET state='cancelled',payload=NULL WHERE account_id=? AND user_id=? AND generation=? AND state IN('pending','retry')",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());'''
assert needle in s
s=s.replace(needle,needle+'''
        Integer stored=jdbc.queryForObject("SELECT COUNT(*) FROM ai_memory_override WHERE id=? AND account_id=? AND user_id=? AND action=? AND match_text=?",Integer.class,overrideId,actor.getAccountId(),actor.getPersonId(),action,match);
        if(stored==null || stored!=1)throw new RenException("记忆修改保存未确认");
        return Map.of("local_applied",true,"operation",action,"operation_id",overrideId,"cloud_sync",longTerm?"pending":"disabled","status","completed");''')
p.write_text(s,encoding='utf-8')
p=R/'PersonMemoryController.java';s=p.read_text(encoding='utf-8-sig')
s=s.replace('public Result<Void> override(@Valid @RequestBody OverrideRequest request)', 'public Result<Map<String,Object>> override(@Valid @RequestBody OverrideRequest request)')
s=s.replace('service.override(request.getActor(),request.getAction(),request.getMatch(),request.getReplacement());return new Result<>();','return new Result<Map<String,Object>>().ok(service.override(request.getActor(),request.getAction(),request.getMatch(),request.getReplacement()));')
p.write_text(s,encoding='utf-8')
p=R/'MemoryDailyWorker.java';s=p.read_text(encoding='utf-8-sig')
s=s.replace("AND m.kind IN('dialogue','dialogue_assistant','dialogue_end','tool_result','habit_analysis')", "AND m.recall_allowed=TRUE AND m.kind IN('dialogue','dialogue_end','habit_analysis')")
p.write_text(s,encoding='utf-8')
p=R/'MemoryMaterialPolicy.java';s=p.read_text(encoding='utf-8-sig')
s=s.replace('if("dialogue_end".equals(row.get("kind")))continue;', 'if(!"dialogue".equals(row.get("kind")))continue;\n            String content=Objects.toString(row.get("content"),"");\n            if(!RecentArchiveService.factualUser(content))continue;')
p.write_text(s,encoding='utf-8')
print('memory API candidate updated without deleting archive data')
