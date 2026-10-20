from pathlib import Path
import json,os,subprocess,sys,re,shutil
S=Path(__file__).parent;sys.path.insert(0,str(S));from budget import Budget
b=Budget(S/'budget.sqlite3');J=S/'manager-api';T=J/'src/test/java/xiaozhi/modules/personmemory'
p=T/'MemoryContinuityDatabaseTest.java';s=p.read_text();s=s.replace('var result=recent.search(a,"我的测试台灯叫什么");','a.setTurnId("query-cross-day");var result=recent.search(a,"我的测试台灯叫什么");')
insert='''
 @Test void targetedCorrectionPreservesOtherFactsAndRawEvidence(){transaction.executeWithoutResult(tx->{
  var a=member();long now=System.currentTimeMillis()/1000;
  history(a,"coffee",1,"我喜欢咖啡",null,now-10);assertTrue(new RecentArchiveService(jdbc,memory,identities).search(a,"我喝咖啡吗").get("text").toString().contains("我喜欢咖啡"));history(a,"lamp",1,"我的台灯叫银杏灯",null,now-9);
  memory.material(a,"coffee-material","dialogue","我喜欢咖啡");
  a.setTurnId("correct");var changed=memory.override(a,"correct","我喜欢咖啡","我现在不喝咖啡了");
  assertEquals(true,changed.get("local_applied"));assertEquals("pending",changed.get("cloud_sync"));
  assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_material WHERE recall_allowed=FALSE",Integer.class));
  assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM ai_agent_chat_history WHERE content='我的台灯叫银杏灯' AND recall_allowed=TRUE",Integer.class));
  a.setTurnId("query");var recent=new RecentArchiveService(jdbc,memory,identities);var coffee=recent.search(a,"我喝咖啡吗");
  assertTrue(coffee.get("text").toString().contains("我现在不喝咖啡了"));assertFalse(coffee.get("text").toString().contains("我喜欢咖啡"));
  assertTrue(recent.search(a,"我的台灯叫什么").get("text").toString().contains("银杏灯"));
  memory.override(a,"forget","我的台灯叫银杏灯",null);
  assertFalse(new RecentArchiveService(jdbc,memory,identities).search(a,"台灯").get("text").toString().contains("银杏灯"));
  assertEquals(2,jdbc.queryForObject("SELECT COUNT(*) FROM ai_agent_chat_history",Integer.class));
 });}
 @Test void currentQueryAndAssistantRetrievalAreNeverPersonalFacts(){transaction.executeWithoutResult(tx->{
  var a=member();long now=System.currentTimeMillis()/1000;
  history(a,a.getTurnId(),1,"我的测试台灯叫银杏灯",null,now);history(a,"assistant",2,"我的测试台灯叫虚构灯",null,now-1);
  history(a,"wrapped",1,"[来源:旧检索]我的测试台灯叫污染灯",null,now-2);
  var recent=new RecentArchiveService(jdbc,memory,identities);assertEquals("",recent.search(a,"测试台灯").get("text"));
  a.setTurnId("next-query");var result=recent.search(a,"测试台灯");assertTrue(result.get("text").toString().contains("银杏灯"));
  assertFalse(result.get("text").toString().contains("虚构灯"));assertFalse(result.get("text").toString().contains("污染灯"));
  assertTrue(((List<?>)result.get("items")).stream().allMatch(i->((Map<?,?>)i).get("record_id").toString().startsWith("archive:")));
 });}
 @Test void delayedOldUploadCannotUndoForget(){transaction.executeWithoutResult(tx->{
  var a=member();a.setCapturedAt(System.currentTimeMillis()-10000);memory.material(a,"before","dialogue","我喜欢咖啡");
  memory.override(a,"forget","我喜欢咖啡",null);memory.material(a,"late-old","dialogue","我喜欢咖啡");
  assertEquals(1,jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_material",Integer.class));
  assertEquals(0,jdbc.queryForObject("SELECT COUNT(*) FROM ai_person_material WHERE recall_allowed=TRUE",Integer.class));
 });}
'''
if 'targetedCorrectionPreservesOtherFactsAndRawEvidence' not in s:s=s.rstrip()[:-1]+insert+'\n}\n'
extra='''
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
if 'correctionKeepsOldTopicAliasWithoutReturningOldFact' not in s:s=s.rstrip()[:-1]+extra+'\n}\n'
p.write_text(s)
classes=['PersonMemoryDatabaseTest','MemoryContinuityDatabaseTest','MemoryDailyWorkerTest','MemoryMaterialPolicyTest','PersonBehaviorServiceTest','MemoryBillingServiceTest']
for cls in classes:
 text=(T/(cls+'.java')).read_text();n=len(re.findall(r'@Test\b',text))
 if 'extends PersonMemoryDatabaseTest' in text:n+=len(re.findall(r'@Test\b',(T/'PersonMemoryDatabaseTest.java').read_text()))
 for i in range(n):b.reserve('case','java:'+cls+':'+str(i))
env=dict(os.environ,**json.loads((S/'private-test-env.json').read_text()))
with (S/'java-tests.log').open('w') as f:r=subprocess.run(['mvn','-q','-Dtest='+','.join(classes),'-DfailIfNoTests=true','test','package','-DskipTests=false'],cwd=J,env=env,stdout=f,stderr=subprocess.STDOUT)
print('java_exit',r.returncode,'budget',b.report())
