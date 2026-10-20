package xiaozhi.modules.personmemory;

import java.util.*;
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
        Integer n=jdbc.queryForObject("SELECT COUNT(*) FROM ai_agent_chat_history WHERE account_id=? AND event_id=?",Integer.class,account,event);
        if(n!=null && n>0)return true;
        Integer retired=jdbc.queryForObject("SELECT COUNT(*) FROM ai_archive_retired_event WHERE account_id=? AND event_id=?",Integer.class,account,event);
        return retired!=null && retired>0;
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

    static boolean factualUser(String value) {
        String text=value.strip();
        if(text.contains("[来源:") || text.contains("[来源：") || text.contains("[本轮可信") || text.contains("\"tool_calls\"") || text.contains("[工具 Harness"))return false;
        if(text.matches("(?s).*(忘掉|忘记|删掉.*记忆|更正.*记忆|纠正.*记忆).*"))return false;
        if(text.isEmpty() || text.matches("(?s).*[？?]\\s*$"))return false;
        if(text.matches("(?s).*(叫什么|是什么|在哪里|放在哪|记得吗|有没有|是否|告诉我|请问|怎么|能不能|为什么|你觉得|猜猜|假如|如果|也许|可能|是不是).*"))return false;
        return text.codePointCount(0,text.length())>=4;
    }

    static Set<String> terms(String query) {
        Set<String> result=new LinkedHashSet<>();
        Matcher english=Pattern.compile("[a-z0-9_]{2,}",Pattern.CASE_INSENSITIVE).matcher(query);
        while(english.find())result.add(english.group().toLowerCase(Locale.ROOT));
        Matcher chinese=Pattern.compile("[\\p{IsHan}]{2,}").matcher(query);
        Set<String> stop=Set.of("我的","你的","我喝","你喝","现在","记忆","说过","提过","知道","还有","什么","记得","告诉","昨天","今天","之前","曾经","一下","那个","这个","我们","你说","我说","过的","的是","请问");
        while(chinese.find()) {String word=chinese.group();for(int i=0;i+1<word.length();i++) {String term=word.substring(i,i+2);if(!stop.contains(term))result.add(term);}}
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
        identities.lock(actor.getAccountId());memory.validateActor(actor,false);
        if(query==null || query.isBlank() || query.length()>2048)throw new RenException("检索内容无效");
        Set<String> terms=terms(query);
        Date cutoff=new Date(System.currentTimeMillis()-86400000L);
        var rows=jdbc.queryForList("SELECT id,turn_id,content,created_at FROM ai_agent_chat_history WHERE account_id=? AND person_id=? AND agent_id=? AND default_generation=? AND recall_allowed=TRUE AND chat_type=1 AND created_at>=? AND (turn_id IS NULL OR turn_id<>?) ORDER BY created_at DESC,id DESC LIMIT 1000",actor.getAccountId(),actor.getPersonId(),actor.getAgentId(),actor.getGeneration(),cutoff,actor.getTurnId());
        for(var row:rows)row.put("record_id","archive:"+row.get("id"));
        var pending=jdbc.queryForList("SELECT id,turn_id,content,created_at FROM ai_person_material WHERE account_id=? AND user_id=? AND agent_id=? AND generation=? AND recall_allowed=TRUE AND kind='dialogue' AND turn_id<>? ORDER BY id DESC LIMIT 1000",actor.getAccountId(),actor.getPersonId(),actor.getAgentId(),actor.getGeneration(),actor.getTurnId());
        for(var row:pending){row.put("record_id","material:"+row.get("id"));rows.add(row);}
        var changes=jdbc.queryForList("SELECT id,action,match_text,replacement,state,created_at FROM ai_memory_override WHERE account_id=? AND user_id=? AND generation=?",actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        for(var change:changes)if("correct".equals(change.get("action")) && !"superseded".equals(change.get("state")) && change.get("replacement")!=null){
            var row=new HashMap<String,Object>();row.put("content",change.get("replacement"));row.put("created_at",change.get("created_at"));row.put("record_id","override:"+change.get("id"));row.put("authoritative",true);row.put("search_text",change.get("match_text")+" "+change.get("replacement"));rows.add(row);
        }
        rows.sort(Comparator.<Map<String,Object>>comparingLong(r->sourceTime(r.get("created_at"))).reversed());
        rows.sort(Comparator.<Map<String,Object>>comparingInt(r->score(Objects.toString(r.getOrDefault("search_text",r.get("content")),""),terms)).reversed());
        List<Map<String,Object>> items=new ArrayList<>();Set<String> seen=new HashSet<>();
        for(var row:rows){
            String value=Objects.toString(row.get("content"),"").strip();
            if(items.size()>=5)break;
            if(!factualUser(value) || value.length()>1024 || score(Objects.toString(row.getOrDefault("search_text",value),""),terms)<1 || terms.isEmpty())continue;
            if(!Boolean.TRUE.equals(row.get("authoritative")) && changes.stream().anyMatch(c->sourceTime(c.get("created_at"))>=sourceTime(row.get("created_at")) && ("*".equals(c.get("match_text")) || value.contains(Objects.toString(c.get("match_text"),"")))))continue;
            if(!seen.add(value))continue;
            var item=new LinkedHashMap<String,Object>();item.put("record_id",row.get("record_id"));item.put("text",value);item.put("source","local_user_fact");item.put("created_at",sourceTime(row.get("created_at")));items.add(item);
        }
        boolean blocked=changes.stream().anyMatch(c->!"complete".equals(c.get("state")));
        String text=String.join("；",items.stream().map(i->Objects.toString(i.get("text"),"")).toList());
        return Map.of("text",text,"items",items,"reliable",!items.isEmpty(),"status",items.isEmpty()?(blocked?"suppressed":"not_found"):"ok","source","local");
    }
}
