from pathlib import Path
S=Path('tools/experience-repair-20261009')
p=S/'java/PersonMemoryService.java';s=p.read_text(encoding='utf-8-sig');s=s.replace('"correct".equals(override.get("action")) && override.get("replacement")!=null','"correct".equals(override.get("action")) && !"superseded".equals(override.get("state")) && override.get("replacement")!=null');needle='        String overrideId=AccountIdentityStateService.newId();';s=s.replace(needle,'        jdbc.update("UPDATE ai_memory_override SET state=\'superseded\' WHERE account_id=? AND user_id=? AND generation=? AND replacement IS NOT NULL AND LOCATE(?,replacement)>0",actor.getAccountId(),actor.getPersonId(),actor.getGeneration(),match);\n'+needle);p.write_text(s,encoding='utf-8')
p=S/'run_java_tests.py';s=p.read_text(encoding='utf-8-sig');needle="p.write_text(s)";s=s.replace(needle,"""extra='''
 @Test void correctionKeepsOldTopicAliasWithoutReturningOldFact(){transaction.executeWithoutResult(tx->{
  var a=member();long now=System.currentTimeMillis()/1000;history(a,"coffee",1,"我喜欢咖啡",null,now-10);
  memory.override(a,"correct","我喜欢咖啡","喜欢绿茶");a.setTurnId("query-new");
  var value=new RecentArchiveService(jdbc,memory,identities).search(a,"咖啡").get("text").toString();assertEquals("喜欢绿茶",value);
 });}
 @Test void forgettingCorrectedFactDoesNotResurrectEarlierCorrection(){transaction.executeWithoutResult(tx->{
  var a=member();long now=System.currentTimeMillis()/1000;history(a,"coffee",1,"我喜欢咖啡",null,now-10);
  memory.override(a,"correct","我喜欢咖啡","我喜欢绿茶");memory.override(a,"forget","我喜欢绿茶",null);a.setTurnId("query-new");
  assertEquals("",new RecentArchiveService(jdbc,memory,identities).search(a,"喜欢的饮料").get("text"));
 });}
'''
if 'correctionKeepsOldTopicAliasWithoutReturningOldFact' not in s:s=s.rstrip()[:-1]+extra+'\\n}\\n'
p.write_text(s)""");p.write_text(s,encoding='utf-8')
