from pathlib import Path
import json
root=Path(__file__).resolve().parents[2]/'tmp/bailian-memory-product/server';manifest=Path(__file__).with_name('changed.json');changed=json.loads(manifest.read_text())
def write(n,t):(root/n).write_text(t,encoding='utf-8');changed.append(n)
s='main/xiaozhi-server/core/utils/person_short_memory.py';text=(root/s).read_text()
text=text.replace('def revision(actor):','def revision_scope(actor):\n    return json.dumps([actor.account_id,actor.person_id,actor.generation],separators=(",",":"))\n\n\ndef revision(actor):')
text=text.replace('SELECT revision FROM short_scope_revision WHERE scope=?",(scope(actor),)','SELECT revision FROM short_scope_revision WHERE scope=?",(revision_scope(actor),)')
text=text.replace('db.execute("DELETE FROM short_summary WHERE scope=?",(scope(actor),))','db.execute("DELETE FROM short_summary WHERE json_extract(scope,\'$[0]\')=? AND json_extract(scope,\'$[1]\')=? AND json_extract(scope,\'$[2]\')=?",(actor.account_id,actor.person_id,actor.generation))')
text=text.replace('ON CONFLICT(scope) DO UPDATE SET revision=revision+1",(scope(actor),)','ON CONFLICT(scope) DO UPDATE SET revision=revision+1",(revision_scope(actor),)');write(s,text)
r='main/manager-api/src/main/java/xiaozhi/modules/personmemory/RecentArchiveService.java';text=(root/r).read_text()
text=text.replace('int rowKind=((Number)row.get("chat_type")).intValue();\n            if(rowKind==1 && factualUser(Objects.toString(row.get("content"),"")) || rowKind==3)reliable=true;','int rowKind=((Number)row.get("chat_type")).intValue();\n            if(score(Objects.toString(row.get("content"),""),terms)<2 || !(rowKind==1 && factualUser(Objects.toString(row.get("content"),"")) || rowKind==3))continue;\n            reliable=true;')
text=text.replace('turn.isBlank() || Boolean.TRUE.equals(row.get("pending"))?List.of(row):','turn.isBlank()?List.of(row):Boolean.TRUE.equals(row.get("pending"))?rows.stream().filter(n->Boolean.TRUE.equals(n.get("pending")) && turn.equals(Objects.toString(n.get("turn_id"),""))).sorted(Comparator.comparingLong(n->sourceTime(n.get("created_at")))).toList():');write(r,text)
s='main/manager-api/src/main/java/xiaozhi/modules/personmemory/PersonMemoryService.java';text=(root/s).read_text()
text=text.replace('        int start=0,index=0;','''        Long suppression=jdbc.queryForObject("SELECT MAX(UNIX_TIMESTAMP(created_at)*1000) FROM ai_memory_override WHERE account_id=? AND user_id=? AND generation=?",Long.class,actor.getAccountId(),actor.getPersonId(),actor.getGeneration());
        if(suppression!=null && (actor.getCapturedAt()==null || actor.getCapturedAt()<=suppression+1000))return;
        int start=0,index=0;''')
old='else jdbc.update("DELETE FROM ai_person_material WHERE account_id=? AND user_id=? AND generation=? AND kind IN(\'dialogue\',\'dialogue_assistant\',\'dialogue_end\',\'tool_result\',\'habit_analysis\') AND LOCATE(?,content)>0",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),match);'
new='''else {
            var turns=jdbc.queryForList("SELECT DISTINCT turn_id FROM ai_person_material WHERE account_id=? AND user_id=? AND generation=? AND LOCATE(?,content)>0",String.class,actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),match);
            for(String turn:turns)jdbc.update("DELETE FROM ai_person_material WHERE account_id=? AND user_id=? AND generation=? AND turn_id=? AND kind IN('dialogue','dialogue_assistant','dialogue_end','tool_result','habit_analysis')",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),turn);
        }'''
assert old in text;text=text.replace(old,new);write(s,text)
# Failed/aborted turns still end durably, with no invented assistant success.
s='main/xiaozhi-server/core/connection.py';text=(root/s).read_text();text=text.replace('                if depth==0 and result and getattr(getattr(self,"memory",None),"personal",False):','                if depth==0 and getattr(getattr(self,"memory",None),"personal",False):');write(s,text)
manifest.write_text(json.dumps(sorted(set(changed)),indent=2))
