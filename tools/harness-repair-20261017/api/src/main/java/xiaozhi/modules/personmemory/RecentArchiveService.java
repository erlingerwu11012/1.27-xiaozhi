package xiaozhi.modules.personmemory;

import java.util.*;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.*;
import java.util.regex.*;
import lombok.RequiredArgsConstructor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import xiaozhi.common.exception.RenException;
import xiaozhi.modules.agent.dto.AgentChatHistoryReportDTO;
import xiaozhi.modules.agent.entity.AgentEntity;
import xiaozhi.modules.useridentity.service.AccountIdentityStateService;

/** Shared text archive: owner validation, suppression and bounded local recall. */
@Service
@RequiredArgsConstructor
public class RecentArchiveService {
    private final JdbcTemplate jdbc;
    private final PersonMemoryService memory;
    private final AccountIdentityStateService identities;

    public boolean audioOwned(String audio,Long account) {
        Integer n=jdbc.queryForObject("SELECT COUNT(*) FROM ai_agent_chat_history h JOIN ai_agent a ON a.id=h.agent_id WHERE h.audio_id=? AND a.user_id=?",Integer.class,audio,account);
        return n!=null && n>0;
    }

    public boolean duplicate(Long account,String event) {
        if(event==null || event.isBlank())return false;
        identities.lock(account);
        // A current read is required after waiting for the account lock:
        // the earlier agent lookup may already have opened a repeatable-read snapshot.
        if(!jdbc.queryForList("SELECT id FROM ai_agent_chat_history WHERE account_id=? AND event_id=? LIMIT 1 FOR UPDATE",account,event).isEmpty())return true;
        return !jdbc.queryForList("SELECT event_id FROM ai_archive_retired_event WHERE account_id=? AND event_id=? LIMIT 1 FOR UPDATE",account,event).isEmpty();
    }
    public boolean recallAllowed(PersonTurnDTO actor) {
        List<Date> dates=jdbc.queryForList("SELECT MAX(created_at) FROM ai_memory_override WHERE account_id=? AND user_id=? AND generation=? AND match_text='*'",Date.class,actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        Date cutoff=dates.isEmpty()?null:dates.get(0);
        return cutoff==null || actor.getCapturedAt()!=null && actor.getCapturedAt()>cutoff.getTime()+1000;
    }

    @Transactional
    public boolean validateReport(AgentChatHistoryReportDTO report,AgentEntity agent) {
        var actor=report.getIdentity();
        if(actor==null)return false; // Legacy input remains available for enrollment.
        if(actor.getAccountId()==null || actor.getAccountId()<=0 || !Objects.equals(actor.getAccountId(),agent.getUserId())
                || !Objects.equals(actor.getDeviceId(),report.getMacAddress()) || !Objects.equals(actor.getAgentId(),agent.getId())
                || actor.getTurnId()==null || !actor.getTurnId().matches("[A-Za-z0-9_-]{1,64}"))throw new RenException("存档归属无效");
        identities.lock(actor.getAccountId());
        if(Set.of("default","matched").contains(Objects.toString(actor.getStatus(),""))) {
            memory.validateArchiveActor(actor);return true;
        }
        if(actor.getPersonId()!=null && !actor.getPersonId().isBlank())throw new RenException("未知身份不可指定人物");
        // This guard also rejects late reports after device/account reassignment.
        Integer owned=jdbc.queryForObject("SELECT COUNT(*) FROM ai_device WHERE mac_address=? AND user_id=? AND agent_id=?",Integer.class,actor.getDeviceId(),actor.getAccountId(),actor.getAgentId());
        if(owned==null || owned!=1)throw new RenException("设备归属已变更");
        return false;
    }

    @Transactional
    public Map<String,Object> continuation(PersonTurnDTO actor) {
        identities.lock(actor.getAccountId());memory.validateActor(actor,false);
        String scope="account_id=? AND person_id=? AND agent_id=? AND default_generation=? AND recall_allowed=TRUE AND content<>''";
        Object[] args={actor.getAccountId(),actor.getPersonId(),actor.getAgentId(),actor.getGeneration()};
        var turns=jdbc.queryForList("SELECT turn_id FROM ai_agent_chat_history WHERE "+scope+" AND turn_id IS NOT NULL GROUP BY turn_id HAVING SUM(chat_type=1)>0 AND SUM(chat_type=2)>0 ORDER BY MAX(created_at) DESC,MAX(id) DESC LIMIT 50",args);
        List<Map<String,String>> result=new ArrayList<>();Collections.reverse(turns);
        for(var turn:turns) {
            var params=new ArrayList<>(Arrays.asList(args));params.add(turn.get("turn_id"));
            var rows=jdbc.queryForList("SELECT chat_type,content FROM ai_agent_chat_history WHERE "+scope+" AND turn_id=? ORDER BY created_at,id",params.toArray());
            StringBuilder user=new StringBuilder(),assistant=new StringBuilder();
            for(var row:rows){String value=Objects.toString(row.get("content"),"");if(((Number)row.get("chat_type")).intValue()==1)user.append(value).append('\n');else assistant.append(value).append('\n');}
            if(!user.isEmpty() && !assistant.isEmpty()){result.add(Map.of("role","user","content",user.toString()));result.add(Map.of("role","assistant","content",assistant.toString()));}
        }
        return Map.of("messages",result,"turns",result.size()/2);
    }

    private static void validateReplacement(String action,String previous,String replacement) {
        if(!"correct".equals(action))return;
        if(replacement==null || !replacement.equals(normalizeFact(replacement)) || !factualUser(replacement,1))throw new RenException("更正需要完整事实");
        List<String> relationships=List.of("老婆","妻子","配偶","丈夫","老公","妈妈","母亲","爸爸","父亲","女儿","儿子","朋友","同事");
        if(relationships.stream().anyMatch(previous::contains) && relationships.stream().noneMatch(replacement::contains))throw new RenException("更正需要保留人物关系");
    }

    static String normalizeFact(String value) {
        if(value==null)return "";
        String text=value.strip();
        for(int i=0;i<3 && text.startsWith("{");i++) {
            try {
                var row=new ObjectMapper().readTree(text);
                if(!row.isObject() || !row.path("content").isTextual() || row.has("role") && !"user".equals(row.path("role").asText()))return "";
                text=row.path("content").asText().strip();
            } catch(Exception e) { return ""; }
        }
        text=text.replaceFirst("^(?:(?:那|好|嗯|呃)[，, ]*)?(?:(?:请|你|帮我|给我|替我|现在|这次)\\s*)*(?:记一下|记住|保存(?:一下)?|记录(?:一下)?)[，,：: ]*", "").strip();
        text=text.replaceFirst("[，,。 ]*(?:请|你|帮我|给我)?(?:存到记忆库(?:里)?|存进去|保存到记忆库)(?:吧|啊|呀)?[。！! ]*$", "").strip();
        return text;
    }

    @Transactional
    public Map<String,Object> overrideRecord(PersonTurnDTO actor,String action,String recordId,String expectedVersion,String match,String replacement) {
        identities.lock(actor.getAccountId());memory.validateActor(actor,false);
        String resolved;
        if(recordId!=null && !recordId.isBlank()) {
            String[] parts=recordId.split(":",2);
            if(parts.length!=2 || !Set.of("archive","material","override","cloud").contains(parts[0]) || !parts[1].matches("[A-Za-z0-9_-]{1,128}"))throw new RenException("记忆记录无效");
            if("cloud".equals(parts[0])) {
                if(match==null || match.isBlank())throw new RenException("请先查询要修改的记忆");
                @SuppressWarnings("unchecked") var facts=(List<Map<String,Object>>)memory.search(actor,match).get("items");
                var selected=facts.stream().filter(item->Objects.equals(item.get("record_id"),recordId)).toList();
                if(selected.size()!=1 || !Objects.equals(selected.get(0).get("version"),expectedVersion))throw new RenException("记忆版本已变化，请重新查询");
                resolved=Objects.toString(selected.get(0).get("text"),"");
                validateReplacement(action,resolved,replacement);
                var result=new LinkedHashMap<String,Object>(memory.override(actor,action,resolved,replacement));
                result.put("resolved_match",resolved);return result;
            }
            String sql=switch(parts[0]) {
                case "archive" -> "SELECT content FROM ai_agent_chat_history WHERE id=? AND account_id=? AND person_id=? AND default_generation=? AND agent_id=? AND recall_allowed=TRUE AND chat_type=1";
                case "material" -> "SELECT content FROM ai_person_material WHERE id=? AND account_id=? AND user_id=? AND generation=? AND agent_id=? AND recall_allowed=TRUE AND kind IN('dialogue','explicit_fact')";
                default -> "SELECT replacement AS content FROM ai_memory_override WHERE id=? AND account_id=? AND user_id=? AND generation=? AND state<>'superseded'";
            };
            Object[] params=parts[0].equals("override")?new Object[]{parts[1],actor.getAccountId(),actor.getPersonId(),actor.getGeneration()}:new Object[]{parts[1],actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),actor.getAgentId()};
            var rows=jdbc.queryForList(sql,params);
            if(rows.size()!=1)throw new RenException("记忆已变化或当前身份无权访问");
            resolved=normalizeFact(Objects.toString(rows.get(0).get("content"),""));
            if(!factualUser(resolved,parts[0].equals("override")?1:4) || expectedVersion==null || !MemoryGatewayClient.sha(resolved).equals(expectedVersion))throw new RenException("记忆版本已变化，请重新查询");
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
        validateReplacement(action,resolved,replacement);
        var result=new LinkedHashMap<String,Object>(memory.override(actor,action,resolved,replacement));
        if(recordId!=null && recordId.startsWith("archive:"))jdbc.update("UPDATE ai_agent_chat_history SET recall_allowed=FALSE WHERE id=? AND account_id=? AND person_id=? AND default_generation=? AND agent_id=?",recordId.substring(8),actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),actor.getAgentId());
        if(recordId!=null && recordId.startsWith("material:"))jdbc.update("UPDATE ai_person_material SET recall_allowed=FALSE WHERE id=? AND account_id=? AND user_id=? AND generation=? AND agent_id=?",recordId.substring(9),actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),actor.getAgentId());
        result.put("resolved_match",resolved);return result;
    }

    static boolean factualUser(String value) { return factualUser(value,4); }

    static boolean factualUser(String value,int minimumLength) {
        String text=normalizeFact(value);
        if(text.contains("[来源:") || text.contains("[来源：") || text.contains("[本轮可信") || text.contains("\"tool_calls\"") || text.contains("[工具 Harness"))return false;
        if(text.matches("(?s).*(忘掉|忘记|删掉.*记忆|更正.*记忆|纠正.*记忆).*"))return false;
        if(text.matches("(?s).*(我|你).*(喜欢|爱喝|爱吃).*(什么|啥).*"))return false;
        if(text.matches("(?s).*(?:记忆|记录).{0,12}(?:删除|删掉|忘掉|清空).*"))return false;
        if(text.matches("(?s).*(改一下|改成|改为|更正|纠正).*"))return false;
        if(text.matches("(?s)^(?:请|你|帮我|给我|把|将|这条|这些|这个|全部|所有|刚才|那|好|行|记忆|记录|了|吧|啊|呀|[，,。！! ])*(?:存|保存|删除|删掉|忘掉|修改|待机|取消|不用了|记一下|记好|记住).{0,20}$"))return false;
        if(text.isEmpty() || text.matches("(?s).*[？?]\\s*$"))return false;
        if(text.matches("(?s).*(叫什么|是什么|在哪里|放在哪|记得吗|有没有|是否|告诉我|请问|怎么|能不能|为什么|你觉得|猜猜|假如|如果|也许|可能|是不是).*"))return false;
        return text.codePointCount(0,text.length())>=minimumLength;
    }

    static Set<String> terms(String query) {
        Set<String> result=new LinkedHashSet<>();
        if(query.contains("咖啡"))result.addAll(List.of("咖啡","美式","拿铁","浓缩"));
        if(query.contains("茶"))result.addAll(List.of("茶","普洱","龙井"));
        if(query.contains("早餐"))result.addAll(List.of("早餐","豆浆","牛奶"));
        if(query.contains("水果"))result.addAll(List.of("水果","苹果","梨"));
        if(query.contains("运动"))result.addAll(List.of("运动","慢跑","游泳"));
        if(query.contains("颜色"))result.addAll(List.of("颜色","蓝色","绿色"));
        if(query.matches("(?s).*(老婆|妻子|配偶).*"))result.addAll(List.of("老婆","妻子","配偶"));
        if(query.matches("(?s).*(爱喝|喝什么|喝啥|喝哪|饮料|饮品|喜欢喝).*"))result.addAll(List.of("喝","咖啡","茶","牛奶","豆浆","果汁","可乐","饮料"));
        Matcher english=Pattern.compile("[a-z0-9_]{2,}",Pattern.CASE_INSENSITIVE).matcher(query);
        while(english.find())result.add(english.group().toLowerCase(Locale.ROOT));
        Matcher chinese=Pattern.compile("[\\p{IsHan}]{2,}").matcher(query);
        Set<String> stop=Set.of("我的","你的","我喝","你喝","我爱","我喜","我更","更喜","喜欢","好什","的偏","偏好","现在","记忆","说过","提过","知道","还有","什么","记得","告诉","昨天","今天","之前","曾经","一下","那个","这个","我们","你说","我说","过的","的是","请问");
        while(chinese.find()) {String word=chinese.group();for(int i=0;i+1<word.length();i++) {String term=word.substring(i,i+2);if(!stop.contains(term))result.add(term);}}
        if(query.matches("(?s).*(爱喝|喝什么|喝啥|饮料|饮品|喜欢喝).*"))result.add("喝");
        if(query.matches("(?s).*(爱吃|吃什么|吃啥|喜欢吃|食物).*"))result.add("吃");
        if(query.matches("(?s).*(喜好|偏好|喜欢什么|喜欢啥).*"))result.add("喜欢");
        return result.stream().limit(24).collect(java.util.stream.Collectors.toCollection(LinkedHashSet::new));
    }
    static int score(String text,Set<String> terms) {
        String lower=text.toLowerCase(Locale.ROOT);
        return (int)terms.stream().filter(lower::contains).count();
    }
    static long sourceTime(Object value) {
        if(value instanceof Date date)return date.getTime();
        if(value instanceof LocalDateTime date)return date.atZone(ZoneId.of("Asia/Shanghai")).toInstant().toEpochMilli();
        return 0;
    }
    static boolean suppressedBy(Map<String,Object> row,Map<String,Object> change,String value) {
        if(!"*".equals(change.get("match_text")) && !value.equals(normalizeFact(Objects.toString(change.get("match_text"),""))))return false;
        String record=Objects.toString(row.get("record_id"),"");
        Object boundary=change.get(record.startsWith("material:")?"material_cutoff_id":"archive_cutoff_id");
        if((record.startsWith("material:") || record.startsWith("archive:")) && boundary instanceof Number cutoff && row.get("id") instanceof Number id)return id.longValue()<=cutoff.longValue();
        // Pre-migration markers retain their original suppression behaviour.
        return sourceTime(change.get("created_at"))>=sourceTime(row.get("created_at"));
    }
    static String excerpt(String text,Set<String> terms,int max) {
        if(text.length()<=max)return text;
        String lower=text.toLowerCase(Locale.ROOT);
        int pos=terms.stream().mapToInt(lower::indexOf).filter(i->i>=0).min().orElse(0);
        int start=Math.max(0,pos-120),end=Math.min(text.length(),start+max);
        if(start>0 && Character.isLowSurrogate(text.charAt(start)))start--;
        if(end<text.length() && Character.isHighSurrogate(text.charAt(end-1)))end--;
        return (start>0?"…":"")+text.substring(start,end)+(end<text.length()?"…":"");
    }

    @Transactional
    public Map<String,Object> search(PersonTurnDTO actor,String query) {
        return search(actor,query,"related",1,List.of());
    }

    @Transactional
    public Map<String,Object> search(PersonTurnDTO actor,String query,String scope,int page,List<String> records) {
        identities.lock(actor.getAccountId());memory.validateActor(actor,false);
        if(query==null || query.isBlank() || query.length()>2048)throw new RenException("检索内容无效");
        if(!Set.of("related","facts").contains(scope) || page<1 || page>1000 || records==null || records.size()>8)throw new RenException("查询范围无效");
        if(!records.isEmpty())return readRecords(actor,records);
        Set<String> terms=terms(query);
        Date cutoff=new Date(System.currentTimeMillis()-86400000L);
        var rows=jdbc.queryForList("SELECT id,turn_id,content,created_at FROM ai_agent_chat_history WHERE account_id=? AND person_id=? AND agent_id=? AND default_generation=? AND recall_allowed=TRUE AND chat_type=1 AND created_at>=? AND (turn_id IS NULL OR turn_id<>?) ORDER BY created_at DESC,id DESC LIMIT 1000",actor.getAccountId(),actor.getPersonId(),actor.getAgentId(),actor.getGeneration(),cutoff,actor.getTurnId());
        for(var row:rows)row.put("record_id","archive:"+row.get("id"));
        var pending=jdbc.queryForList("SELECT id,turn_id,kind,content,created_at FROM ai_person_material WHERE account_id=? AND user_id=? AND agent_id=? AND generation=? AND recall_allowed=TRUE AND (kind='explicit_fact' OR kind='dialogue' AND turn_id<>?) ORDER BY id DESC LIMIT 1000",actor.getAccountId(),actor.getPersonId(),actor.getAgentId(),actor.getGeneration(),actor.getTurnId());
        for(var row:pending){row.put("record_id","material:"+row.get("id"));rows.add(row);}
        var changes=jdbc.queryForList("SELECT id,action,match_text,replacement,state,created_at,material_cutoff_id,archive_cutoff_id FROM ai_memory_override WHERE account_id=? AND user_id=? AND generation=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        for(var change:changes)if("correct".equals(change.get("action")) && !"superseded".equals(change.get("state")) && change.get("replacement")!=null){
            var row=new HashMap<String,Object>();row.put("content",change.get("replacement"));row.put("created_at",change.get("created_at"));row.put("record_id","override:"+change.get("id"));row.put("authoritative",true);row.put("search_text",change.get("match_text")+" "+change.get("replacement"));rows.add(row);
        }
        rows.sort(Comparator.<Map<String,Object>>comparingLong(r->sourceTime(r.get("created_at"))).reversed());
        rows.sort(Comparator.<Map<String,Object>>comparingInt(r->score(Objects.toString(r.getOrDefault("search_text",r.get("content")),""),terms)).reversed());
        // A generic personal-memory question may use different vocabulary from
        // the stored fact. Supply a bounded recent context for the main LLM to select.
        boolean broad=query.matches("(?s).*(上下文|记忆库|说过什么).* ".strip());
        List<Map<String,Object>> items=new ArrayList<>();Set<String> seen=new HashSet<>();
        for(var row:rows){
            String value=normalizeFact(Objects.toString(row.get("content"),""));
            if("facts".equals(scope) && !Boolean.TRUE.equals(row.get("authoritative")) && !"explicit_fact".equals(row.get("kind")))continue;
            if(!factualUser(value,Boolean.TRUE.equals(row.get("authoritative"))?1:4) || value.length()>1024 || (score(Objects.toString(row.getOrDefault("search_text",value),""),terms)<1 || terms.isEmpty()) && !broad && !"facts".equals(scope))continue;
            if(!Boolean.TRUE.equals(row.get("authoritative")) && changes.stream().anyMatch(c->suppressedBy(row,c,value)))continue;
            if(!seen.add(value))continue;
            var item=new LinkedHashMap<String,Object>();item.put("record_id",row.get("record_id"));item.put("text",value);item.put("version",MemoryGatewayClient.sha(value));item.put("owner",actor.getPersonId());item.put("source",Boolean.TRUE.equals(row.get("authoritative"))?"local_override":"explicit_fact".equals(row.get("kind"))?"explicit_fact":"user_archive_statement");item.put("created_at",sourceTime(row.get("created_at")));items.add(item);
        }
        boolean blocked=changes.stream().anyMatch(c->!"complete".equals(c.get("state")));
        int count=items.size(), offset=Math.min(count,(page-1)*8);
        boolean scanTruncated=rows.size()>=1000;
        var pageItems=items.subList(offset,Math.min(count,offset+8));
        String text=String.join("；",pageItems.stream().map(i->Objects.toString(i.get("text"),"")).toList());
        var result=new LinkedHashMap<String,Object>();
        result.put("text",text);result.put("items",pageItems);result.put("reliable",!pageItems.isEmpty());
        result.put("status",pageItems.isEmpty()?(blocked?"suppressed":"not_found"):"ok");result.put("source","local");result.put("scope",scope);result.put("page",page);
        result.put("truncated",scanTruncated || offset+8<count);result.put("total_complete",false);
        result.put("returned_count",pageItems.size());result.put("has_more",offset+8<count);result.put("local_matched_count",count);
        return result;
    }
    private Map<String,Object> readRecords(PersonTurnDTO actor,List<String> records) {
        List<Map<String,Object>> items=new ArrayList<>(), checked=new ArrayList<>();
        for(String record:records) {
            if(record==null || !record.matches("(?:material|archive|override):[A-Za-z0-9_-]{1,128}"))throw new RenException("记录编号无效");
            String[] parts=record.split(":",2);
            String sql=switch(parts[0]) {
                case "material" -> "SELECT content,created_at,recall_allowed FROM ai_person_material WHERE id=? AND account_id=? AND user_id=? AND generation=? AND agent_id=?";
                case "archive" -> "SELECT content,created_at,recall_allowed FROM ai_agent_chat_history WHERE id=? AND account_id=? AND person_id=? AND default_generation=? AND agent_id=? AND chat_type=1";
                default -> "SELECT replacement AS content,created_at,(state<>'superseded' AND action='correct') AS recall_allowed FROM ai_memory_override WHERE id=? AND account_id=? AND user_id=? AND generation=?";
            };
            Object[] args=parts[0].equals("override")?new Object[]{parts[1],actor.getAccountId(),actor.getPersonId(),actor.getGeneration()}:new Object[]{parts[1],actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),actor.getAgentId()};
            var rows=jdbc.queryForList(sql,args);
            boolean visible=false;
            if(rows.size()==1) {
                var row=rows.get(0);String fact=normalizeFact(Objects.toString(row.get("content"),""));
                Object allowed=row.get("recall_allowed");visible=(Boolean.TRUE.equals(allowed) || allowed instanceof Number n && n.intValue()==1) && factualUser(fact,1);
                if(visible)items.add(Map.of("record_id",record,"text",fact,"version",MemoryGatewayClient.sha(fact),"source","record_readback","created_at",sourceTime(row.get("created_at"))));
            }
            checked.add(Map.of("record_id",record,"visible",visible));
        }
        return Map.of("items",items,"text",String.join("；",items.stream().map(i->Objects.toString(i.get("text"),"")).toList()),"status",items.isEmpty()?"not_found":"ok","reliable",true,"source","local","scope","records","checked_records",checked,"total_complete",false);
    }

}
