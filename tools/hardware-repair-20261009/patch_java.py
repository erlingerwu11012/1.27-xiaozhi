from pathlib import Path
B=Path('tools/hardware-repair-20261009/java')
p=B/'RecentArchiveService.java';s=p.read_text();s=s.replace('import java.util.*;','import java.util.*;\nimport com.fasterxml.jackson.databind.ObjectMapper;')
marker='    static boolean factualUser(String value) {'
addition='''    static String normalizeFact(String value) {
        if(value==null)return "";
        String text=value.strip();
        for(int i=0;i<3 && text.startsWith("{");i++) {
            try {
                var row=new ObjectMapper().readTree(text);
                if(!row.isObject() || !row.path("content").isTextual() || row.has("role") && !"user".equals(row.path("role").asText()))return "";
                text=row.path("content").asText().strip();
            } catch(Exception e) { return ""; }
        }
        return text;
    }

    @Transactional
    public Map<String,Object> overrideRecord(PersonTurnDTO actor,String action,String recordId,String expectedVersion,String match,String replacement) {
        identities.lock(actor.getAccountId());memory.validateActor(actor,false);
        String resolved;
        if(recordId!=null && !recordId.isBlank()) {
            String[] parts=recordId.split(":",2);
            if(parts.length!=2 || !Set.of("archive","material","override").contains(parts[0]) || !parts[1].matches("[A-Za-z0-9_-]{1,128}"))throw new RenException("记忆记录无效");
            String sql=switch(parts[0]) {
                case "archive" -> "SELECT content FROM ai_agent_chat_history WHERE id=? AND account_id=? AND person_id=? AND default_generation=? AND agent_id=? AND recall_allowed=TRUE AND chat_type=1";
                case "material" -> "SELECT content FROM ai_person_material WHERE id=? AND account_id=? AND user_id=? AND generation=? AND agent_id=? AND recall_allowed=TRUE AND kind='dialogue'";
                default -> "SELECT replacement AS content FROM ai_memory_override WHERE id=? AND account_id=? AND user_id=? AND generation=? AND state<>'superseded'";
            };
            Object[] params=parts[0].equals("override")?new Object[]{parts[1],actor.getAccountId(),actor.getPersonId(),actor.getGeneration()}:new Object[]{parts[1],actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),actor.getAgentId()};
            var rows=jdbc.queryForList(sql,params);
            if(rows.size()!=1)throw new RenException("记忆已变化或当前身份无权访问");
            resolved=normalizeFact(Objects.toString(rows.get(0).get("content"),""));
            if(!factualUser(resolved) || expectedVersion==null || !MemoryGatewayClient.sha(resolved).equals(expectedVersion))throw new RenException("记忆版本已变化，请重新查询");
        } else {
            if("*".equals(match))resolved=match;
            else {
                var found=search(actor,match);
                @SuppressWarnings("unchecked") var items=(List<Map<String,Object>>)found.get("items");
                var selected=items.stream().filter(item->Objects.equals(item.get("text"),match)).toList();
                if(selected.size()!=1)throw new RenException("没有唯一定位到要修改的旧记忆");
                resolved=match;
            }
        }
        var result=new LinkedHashMap<String,Object>(memory.override(actor,action,resolved,replacement));
        result.put("resolved_match",resolved);return result;
    }

'''
assert marker in s;s=s.replace(marker,addition+marker)
s=s.replace('String text=value.strip();\n        if(text.contains', 'String text=normalizeFact(value);\n        if(text.contains')
s=s.replace('if(text.isEmpty() || text.matches', 'if(text.matches("(?s).*(我|你).*(喜欢|爱喝|爱吃).*(什么|啥).*"))return false;\n        if(text.matches("(?s).*(改一下|改成|改为|更正|纠正).*"))return false;\n        if(text.isEmpty() || text.matches')
s=s.replace('String value=Objects.toString(row.get("content"),"").strip();','String value=normalizeFact(Objects.toString(row.get("content"),""));')
s=s.replace('item.put("text",value);item.put("source"', 'item.put("text",value);item.put("version",MemoryGatewayClient.sha(value));item.put("owner",actor.getPersonId());item.put("source"')
p.write_text(s)
p=B/'PersonMemoryController.java';s=p.read_text();s=s.replace('@NotBlank @Size(max=1024) private String match;', '@Size(max=1024) private String match;\n        @Size(max=160) private String recordId;\n        @Size(max=64) private String expectedVersion;')
s=s.replace('service.override(request.getActor(),request.getAction(),request.getMatch(),request.getReplacement())','recent.overrideRecord(request.getActor(),request.getAction(),request.getRecordId(),request.getExpectedVersion(),request.getMatch(),request.getReplacement())');p.write_text(s)
print('record-based memory API patched')
