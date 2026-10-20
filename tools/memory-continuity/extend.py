from pathlib import Path
import json
root=Path(__file__).resolve().parents[2]/'tmp/bailian-memory-product/server'
manifest=Path(__file__).with_name('changed.json');changed=json.loads(manifest.read_text())
def write(name,text):
    p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8');changed.append(name)
def edit(name,old,new):
    text=(root/name).read_text(encoding='utf-8');assert old in text,name+' missing '+old[:60];write(name,text.replace(old,new))
j='main/manager-api/src/main/java/xiaozhi/modules/personmemory/'
v='main/xiaozhi-server/'
edit('main/manager-api/src/main/resources/db/changelog/202609301900_memory_continuity.sql','token_version SMALLINT NOT NULL DEFAULT 1','token_version SMALLINT NOT NULL DEFAULT 0')
edit(j+'PersonMemoryService.java','kind,content,user_tokens) VALUES(?,?,?,?,?,?,?,?,?,?)','kind,content,user_tokens,token_version) VALUES(?,?,?,?,?,?,?,?,?,?,1)')
edit(j+'MemoryDailyWorker.java','long n=((Number)m.getOrDefault("user_tokens",0)).longValue();return n>0?n:MemoryMaterialPolicy.userTokens','long n=((Number)m.getOrDefault("user_tokens",0)).longValue();return ((Number)m.getOrDefault("token_version",0)).intValue()>0?n:MemoryMaterialPolicy.userTokens')
edit(j+'MemoryDailyWorker.java','            long tokens=materials.stream()', '''            // A turn submitted just before the boundary is not acknowledged until
            // its durable end marker is present. Never advance past an unfinished turn.
            Set<String> closed=new HashSet<>();for(var row:materials)if("dialogue_end".equals(row.get("kind")))closed.add(Objects.toString(row.get("turn_id"),""));
            long incomplete=materials.stream().filter(row->"dialogue".equals(row.get("kind")) && ((Number)row.getOrDefault("token_version",0)).intValue()>0 && !closed.contains(Objects.toString(row.get("turn_id"),""))).mapToLong(row->((Number)row.get("id")).longValue()).min().orElse(Long.MAX_VALUE);
            materials.removeIf(row->((Number)row.get("id")).longValue()>=incomplete);
            if(materials.isEmpty())return;
            long tokens=materials.stream()''')
edit(j+'MemoryDailyWorker.java','long watermark=until;','long watermark=((Number)materials.get(materials.size()-1).get("id")).longValue();')
write(j+'ArchiveRetentionWorker.java','''package xiaozhi.modules.personmemory;
import java.util.*;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.springframework.transaction.support.TransactionTemplate;
import xiaozhi.modules.useridentity.service.AccountIdentityStateService;

/** Independent retention: audio 72h/50, archive text 50 turns, no material deletion. */
@Slf4j @Component @RequiredArgsConstructor
public class ArchiveRetentionWorker {
    private final JdbcTemplate jdbc;
    private final TransactionTemplate transactions;
    private final AccountIdentityStateService identities;
    @Scheduled(fixedDelay=300000,initialDelay=90000)
    public void tick() {try{clean();}catch(Exception e){log.warn("archive retention deferred: {}",e.getClass().getSimpleName());}}
    public void clean() {
        long cutoff=System.currentTimeMillis()/1000-72*3600;
        var audio=jdbc.queryForList("SELECT id,audio_id FROM (SELECT h.id,h.audio_id,h.chat_type,UNIX_TIMESTAMP(h.created_at) AS stamp,ROW_NUMBER() OVER(PARTITION BY h.agent_id,h.chat_type ORDER BY h.created_at DESC,h.id DESC) AS rn FROM ai_agent_chat_history h WHERE h.audio_id IS NOT NULL) ranked WHERE chat_type<>1 OR stamp<=? OR rn>50 LIMIT 2000",cutoff);
        transactions.executeWithoutResult(tx->{for(var row:audio) {
            jdbc.update("UPDATE ai_agent_chat_history SET audio_id=NULL WHERE id=? AND audio_id=?",row.get("id"),row.get("audio_id"));
            jdbc.update("DELETE FROM ai_agent_chat_audio WHERE id=? AND NOT EXISTS(SELECT 1 FROM ai_agent_chat_history WHERE audio_id=?)",row.get("audio_id"),row.get("audio_id"));
        }});
        var scopes=jdbc.queryForList("SELECT DISTINCT COALESCE(h.account_id,a.user_id) AS account_id,h.agent_id,COALESCE(h.person_id,CONCAT('unknown:',h.mac_address)) AS person_scope,COALESCE(h.default_generation,0) AS generation FROM ai_agent_chat_history h JOIN ai_agent a ON a.id=h.agent_id WHERE h.content<>''");
        for(var scope:scopes)transactions.executeWithoutResult(tx->{
            identities.lock(((Number)scope.get("account_id")).longValue());
            String predicate="COALESCE(account_id,(SELECT user_id FROM ai_agent WHERE id=agent_id))=? AND agent_id=? AND COALESCE(person_id,CONCAT('unknown:',mac_address))=? AND COALESCE(default_generation,0)=?";
            Object[] args={scope.get("account_id"),scope.get("agent_id"),scope.get("person_scope"),scope.get("generation")};
            var keep=jdbc.queryForList("SELECT COALESCE(NULLIF(turn_id,''),id) AS turn_key FROM ai_agent_chat_history WHERE "+predicate+" AND content<>'' GROUP BY turn_key ORDER BY MAX(created_at) DESC,MAX(id) DESC LIMIT 50",args);
            if(keep.size()<50)return;
            List<Object> values=new ArrayList<>(Arrays.asList(args));for(var row:keep)values.add(row.get("turn_key"));
            var old=jdbc.queryForList("SELECT id,audio_id,event_id FROM ai_agent_chat_history WHERE "+predicate+" AND content<>'' AND COALESCE(NULLIF(turn_id,''),id) NOT IN ("+String.join(",",Collections.nCopies(keep.size(),"?"))+") LIMIT 2000",values.toArray());
            for(var row:old) {
                if(row.get("event_id")!=null)jdbc.update("INSERT IGNORE INTO ai_archive_retired_event(account_id,event_id) VALUES(?,?)",scope.get("account_id"),row.get("event_id"));
                if(row.get("audio_id")==null)jdbc.update("DELETE FROM ai_agent_chat_history WHERE id=?",row.get("id"));
                else jdbc.update("UPDATE ai_agent_chat_history SET content='',recall_allowed=FALSE WHERE id=?",row.get("id"));
            }
        });
        // Bytes without a history reference cannot be used for enrollment or playback.
        jdbc.update("DELETE a FROM ai_agent_chat_audio a LEFT JOIN ai_agent_chat_history h ON h.audio_id=a.id WHERE h.id IS NULL");
    }
}
''')
r=j+'RecentArchiveService.java'
edit(r,'return n!=null && n>0;\n    }\n    public boolean recallAllowed', '''if(n!=null && n>0)return true;
        Integer retired=jdbc.queryForObject("SELECT COUNT(*) FROM ai_archive_retired_event WHERE account_id=? AND event_id=?",Integer.class,account,event);
        return retired!=null && retired>0;
    }
    public boolean recallAllowed''')
pos=(root/r).read_text().index('    static Set<String> terms(')
text=(root/r).read_text();text=text[:pos]+'''    @Transactional
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
            for(var row:rows){String value=Objects.toString(row.get("content"),"");if(((Number)row.get("chat_type")).intValue()==1)user.append(value).append('\\n');else assistant.append(value).append('\\n');}
            if(!user.isEmpty() && !assistant.isEmpty()){result.add(Map.of("role","user","content",user.toString()));result.add(Map.of("role","assistant","content",assistant.toString()));}
        }
        return Map.of("messages",result,"turns",result.size()/2);
    }

    static boolean factualUser(String value) {
        String text=value.strip();
        if(text.isEmpty() || text.matches("(?s).*[？?]\\\\s*$"))return false;
        if(text.matches("(?s).*(叫什么|是什么|在哪里|放在哪|记得吗|有没有|是否|告诉我|请问|怎么|能不能|为什么).*"))return false;
        return text.matches("(?s).*(我叫|我的.*(叫|是|在)|我.*(喜欢|不喜欢|讨厌|偏好|住在|习惯)|改成|更正|改为|每天|周一|周二|工作日|放在|名字是|地址是|生日是).*" );
    }

'''+text[pos:];write(r,text)
# Attach pending cross-day original text, scoped and subject to durable suppression.
edit(r,'        // Existing behavior events have no agent column.', '''        var pending=jdbc.queryForList("SELECT id,turn_id,kind,content,created_at FROM ai_person_material WHERE account_id=? AND user_id=? AND agent_id=? AND generation=? AND kind IN('dialogue','dialogue_assistant','tool_result') ORDER BY id DESC LIMIT 2000",actor.getAccountId(),actor.getPersonId(),actor.getAgentId(),actor.getGeneration());
        for(var item:pending){var row=new HashMap<String,Object>(item);row.put("id","pending-"+item.get("id"));row.put("chat_type","dialogue".equals(item.get("kind"))?1:"tool_result".equals(item.get("kind"))?3:2);row.put("pending",true);rows.add(row);}
        // Existing behavior events have no agent column.''')
edit(r,'        StringBuilder text=new StringBuilder();int hits=0;', '        StringBuilder text=new StringBuilder();int hits=0;boolean reliable=false;')
edit(r,'            if(score(Objects.toString(row.get("content"),""),terms)==0 || hits>=5)break;', '''            if(score(Objects.toString(row.get("content"),""),terms)==0 || hits>=5)break;
            int rowKind=((Number)row.get("chat_type")).intValue();
            if(rowKind==1 && factualUser(Objects.toString(row.get("content"),"")) || rowKind==3)reliable=true;''')
edit(r,'List<Map<String,Object>> neighbors=turn.isBlank()?List.of(row):','List<Map<String,Object>> neighbors=turn.isBlank() || Boolean.TRUE.equals(row.get("pending"))?List.of(row):')
edit(r,'"reliable",!text.isEmpty()','"reliable",reliable && !text.isEmpty()')
c=j+'PersonMemoryController.java'
edit(c,'    @PostMapping("/internal/background")', '''    @PostMapping("/internal/continuation")
    public Result<Map<String,Object>> continuation(@Valid @RequestBody PersonTurnDTO actor) {
        return new Result<Map<String,Object>>().ok(recent.continuation(actor));
    }
    @PostMapping("/internal/background")''')
# Snapshot summaries include agent. Person retirement invalidates all its agent scopes.
s=v+'core/utils/person_short_memory.py'
edit(s,'[actor.account_id,actor.person_id,actor.generation]','[actor.account_id,actor.person_id,actor.generation,actor.agent_id]')
edit(s,'    db.execute("CREATE TABLE IF NOT EXISTS retired_short_scope(scope TEXT PRIMARY KEY)")','''    db.execute("CREATE TABLE IF NOT EXISTS retired_short_scope(scope TEXT PRIMARY KEY)")
    # Legacy summaries cannot be safely attributed to a specific agent.
    db.execute("DELETE FROM short_summary WHERE json_array_length(scope)=3")''')
edit(s,'        db.execute("DELETE FROM short_summary WHERE scope=?",(key,))','''        for table in ("short_summary","short_scope_revision"):
            db.execute(f"DELETE FROM {table} WHERE json_extract(scope,'$[0]')=? AND json_extract(scope,'$[1]')=? AND json_extract(scope,'$[2]')=?",(str(account),person,generation))''')
edit(s,'not db.execute("SELECT 1 FROM retired_short_scope WHERE scope=?",(scope(actor),)).fetchone()','not db.execute("SELECT 1 FROM retired_short_scope WHERE scope=?",(json.dumps([actor.account_id,actor.person_id,actor.generation],separators=(\",\",\":\")),)).fetchone()')
# Restore recent persisted turns only on first activation of this actor in the connection.
i=v+'core/utils/person_identity.py'
edit(i,'        histories[key]=dialogue','''        if actor.eligible:
            try:
                import asyncio
                from config.manage_api_client import ManageApiClient
                from core.utils.dialogue import Message
                data=asyncio.run_coroutine_threadsafe(ManageApiClient(conn.config).request(
                    "POST","person-memory/internal/continuation",json=actor.payload(),timeout=2),conn.loop).result(timeout=3)
                for message in (data or {}).get("messages",[]):
                    if message.get("role") in {"user","assistant"} and isinstance(message.get("content"),str):
                        dialogue.put(Message(role=message["role"],content=message["content"]))
            except Exception:
                pass  # Store outage leaves this new context empty; never reuse another actor.
        histories[key]=dialogue''')
edit(i,'and (not getattr(conn.memory,"personal",False) or actor.status == "default")):',') :')
# The preceding multiline condition still has its opening paren. Load scoped background for everyone eligible.
edit(v+'core/providers/memory/bailian/bailian.py','        material_outbox.enqueue(actor,"dialogue",str(text),actor.turn_id+":user")','''        self._enqueue_text(actor,"dialogue",str(text),actor.turn_id+":user")''')
b=v+'core/providers/memory/bailian/bailian.py'
pos=(root/b).read_text().index('    async def search(')
text=(root/b).read_text();text=text[:pos]+'''    def _enqueue_text(self,actor,kind,text,event):
        from core.utils.person_material_outbox import material_outbox
        # Outbox/API per-row limits do not truncate a full turn.
        for index,start in enumerate(range(0,len(text),60000)):
            material_outbox.enqueue(actor,kind,text[start:start+60000],event+":"+str(index))

    def record_response(self,conn,actor,messages):
        if not actor.cloud_eligible:return
        from core.utils.person_material_outbox import material_outbox
        current=[]
        for message in reversed(messages):
            if message.role=="user":break
            current.append(message)
        for index,message in enumerate(reversed(current)):
            value=getattr(message,"caption_text",None) or message.content
            if isinstance(value,str) and value:
                self._enqueue_text(actor,"tool_result" if message.role=="tool" else "dialogue_assistant",value,actor.turn_id+":response:"+str(index))
        material_outbox.enqueue(actor,"dialogue_end","completed",actor.turn_id+":end")
        asyncio.run_coroutine_threadsafe(material_outbox.pump(conn),conn.loop)

'''+text[pos:];write(b,text)
# Include short summary in long-term actor background without requiring a portrait call.
edit(b,'        if not actor.cloud_eligible:return ""','        if not actor.cloud_eligible:return ""\n        if not self.config.get("portraits_enabled",False):return self.short_memory or ""')
c=v+'core/connection.py'
edit(c,'                return self._chat_impl(query,depth,_tts_turn)','''                result=self._chat_impl(query,depth,_tts_turn)
                if depth==0 and result and getattr(getattr(self,"memory",None),"personal",False):
                    self.memory.record_response(self,actor,self.dialogue.dialogue)
                return result''')
# Do not run the old paid disconnect summary for the Bailian provider; preserve validated compact summary locally.
edit(c,'            if self.memory and getattr(self.memory,"person_context",False):','''            if self.memory and getattr(self.memory,"personal",False):
                from core.utils.person_short_memory import persist_compact
                for key,dialogue in getattr(self,"_person_dialogues",{}).items():
                    actor=getattr(self,"_person_dialogue_actors",{}).get(key)
                    if actor and actor.eligible:persist_compact(actor,dialogue)
            elif self.memory and getattr(self.memory,"person_context",False):''')
text=(root/s).read_text();write(s,text+'''
def persist_compact(actor,dialogue):
    """Persist only the already validated compression result; no new paid call."""
    if not actor.eligible or not dialogue.compact_summary:return
    source=getattr(dialogue,"source_revision",0)
    with material_outbox.lock,material_outbox.connect() as db:
        schema(db)
        row=db.execute("SELECT revision FROM short_scope_revision WHERE scope=?",(scope(actor),)).fetchone()
        retired=json.dumps([actor.account_id,actor.person_id,actor.generation],separators=(",",":"))
        if (row[0] if row else 0)==source and not db.execute("SELECT 1 FROM retired_short_scope WHERE scope=?",(retired,)).fetchone():
            db.execute("INSERT OR REPLACE INTO short_summary VALUES(?,?,?)",(scope(actor),dialogue.compact_summary,int(time.time())))
''')
# Local factual evidence first, never an unanswered question or assistant speculation.
rec=v+'core/utils/recent_memory.py'
start=(root/rec).read_text().index('    provider = getattr(conn, "memory", None)')
end=(root/rec).read_text().index('\n\nasync def override',start)
text=(root/rec).read_text();write(rec,text[:start]+'''    if local.get("reliable") and local.get("text"):
        return {**local,"text":str(local["text"])[:3000],"source":"local"}
    provider=getattr(conn,"memory",None)
    if getattr(provider,"personal",False) and actor.cloud_eligible:
        cloud=await provider.search(conn,query)
        return {**cloud,"text":str(cloud.get("text") or "")[:1500],"source":"cloud"}
    return {"status":"not_found","text":"","source":"local"}
'''+text[end:])
manifest.write_text(json.dumps(sorted(set(changed)),indent=2))
print('changed',len(set(changed)))
