from pathlib import Path
R=Path(__file__).parent
p=R/'candidate/core/providers/memory/bailian/bailian.py';s=p.read_text(encoding='utf-8-sig');s=s.replace('value={"text":str((result or {}).get("text") or "")[:1500],"status":"ok"}', 'value={**(result or {}),"text":str((result or {}).get("text") or ""),"status":(result or {}).get("status","ok")}');p.write_text(s,encoding='utf-8')
p=R/'package_candidate.py';s=p.read_text(encoding='utf-8-sig').replace("names=['core/handle/helloHandle.py'", "names=['core/providers/memory/bailian/bailian.py','core/handle/helloHandle.py'");p.write_text(s,encoding='utf-8')
p=R/'java/PersonMemoryService.java';s=p.read_text(encoding='utf-8-sig')
start=s.index('        Object nodes=response.get("memory_nodes");');end=s.index('\n    @Transactional\n    public Map<String,Object> override',start)
s=s[:start]+'''        Object nodes=response.get("memory_nodes");
        List<Map<String,Object>> items=new ArrayList<>();Set<String> seen=new HashSet<>();int chars=0;
        if(nodes instanceof List<?> list) for(Object node:list) {
            if(!(node instanceof Map<?,?> map))continue;
            String value=Objects.toString(map.get("content"),Objects.toString(map.get("custom_content"),"")).strip();
            if(value.isBlank() || value.length()>1024 || value.contains("[来源:") || value.contains("[来源：") || value.contains("[本轮可信") || value.contains("\\"tool_calls\\"") || !seen.add(value))continue;
            if(chars+value.length()>Math.clamp(factChars,128,8000))continue;
            Object id=map.get("id");if(id==null)id=map.get("memory_node_id");
            if(id==null)continue;
            items.add(Map.of("record_id","cloud:"+id,"text",value,"source","cloud_user_fact"));chars+=value.length();
        }
        for(Map<String,Object> override:overrides) if("correct".equals(override.get("action")) && override.get("replacement")!=null){
            String value=override.get("replacement").toString();
            if(value.length()<=1024 && seen.add(value))items.add(Map.of("record_id","override:"+MemoryGatewayClient.sha(value),"text",value,"source","local_override"));
        }
        String text=items.stream().map(i->i.get("text").toString()).collect(java.util.stream.Collectors.joining("\\n"));
        return Map.of("text",text,"items",items,"status",items.isEmpty()?(suppressed?"suppressed":"not_found"):"found","request_id",Objects.toString(response.get("request_id"),""));
    }
''' +s[end:]
# Prevent an old in-flight upload resurrecting a fact after a targeted correction.
s=s.replace('        int start=0,index=0;', '''        var affected=jdbc.queryForList("SELECT match_text,UNIX_TIMESTAMP(created_at)*1000 AS changed_at FROM ai_memory_override WHERE account_id=? AND user_id=? AND generation=? AND match_text<>'*'",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        if(affected.stream().anyMatch(change->content.contains(Objects.toString(change.get("match_text"),"")) && (actor.getCapturedAt()==null || actor.getCapturedAt()<=((Number)change.get("changed_at")).longValue()+1000)))return;
        int start=0,index=0;''')
p.write_text(s,encoding='utf-8')
