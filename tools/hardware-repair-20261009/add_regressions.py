from pathlib import Path
S=Path('tools/hardware-repair-20261009');J=S/'java'
p=J/'MemoryContinuityDatabaseTest.java';s=p.read_text();addition='''
 @Test void wrappedFactsNormalizeDeduplicateAndQuestionsAreExcluded(){transaction.executeWithoutResult(tx->{
  var a=member();long now=System.currentTimeMillis()/1000;
  history(a,"plain",1,"我喜欢喝绿茶",null,now-10);
  history(a,"wrapped",1,"{\\"speaker\\":\\"爸爸\\",\\"content\\":\\"我喜欢喝绿茶\\"}",null,now-9);
  history(a,"question",1,"我爱喝什么",null,now-8);
  history(a,"assistant",2,"我爱喝奶茶",null,now-7);a.setTurnId("next");
  var found=new RecentArchiveService(jdbc,memory,identities).search(a,"我喜欢喝什么");
  var items=(List<?>)found.get("items");assertEquals(1,items.size());
  var item=(Map<?,?>)items.get(0);assertEquals("我喜欢喝绿茶",item.get("text"));assertEquals(MemoryGatewayClient.sha("我喜欢喝绿茶"),item.get("version"));
 });}
 @Test void recordVersionCorrectionAndForgetVerifyRealState(){transaction.executeWithoutResult(tx->{
  var a=member();long now=System.currentTimeMillis()/1000;history(a,"before",1,"我喜欢喝咖啡",null,now-10);history(a,"unrelated",1,"我的台灯叫银杏灯",null,now-9);a.setTurnId("query");
  var recent=new RecentArchiveService(jdbc,memory,identities);
  var found=(List<?>)recent.search(a,"咖啡").get("items");var item=(Map<?,?>)found.get(0);
  assertThrows(RuntimeException.class,()->recent.overrideRecord(a,"correct",item.get("record_id").toString(),"wrong",null,"我现在喝绿茶"));
  assertTrue(recent.search(a,"咖啡").get("text").toString().contains("咖啡"));
  assertEquals(true,recent.overrideRecord(a,"correct",item.get("record_id").toString(),item.get("version").toString(),null,"我现在喝绿茶").get("local_applied"));
  var updated=(Map<?,?>)((List<?>)recent.search(a,"喝绿茶").get("items")).get(0);
  assertTrue(updated.get("record_id").toString().startsWith("override:"));
  recent.overrideRecord(a,"forget",updated.get("record_id").toString(),updated.get("version").toString(),null,null);
  assertEquals("",recent.search(a,"绿茶").get("text"));assertTrue(recent.search(a,"台灯").get("text").toString().contains("银杏灯"));
  assertEquals(2,jdbc.queryForObject("SELECT COUNT(*) FROM ai_agent_chat_history",Integer.class));
 });}
 @Test void anotherPersonCannotSelectRecordId(){transaction.executeWithoutResult(tx->{
  var a=member();long now=System.currentTimeMillis()/1000;history(a,"before",1,"我喜欢喝咖啡",null,now-10);a.setTurnId("query");
  var recent=new RecentArchiveService(jdbc,memory,identities);var item=(Map<?,?>)((List<?>)recent.search(a,"咖啡").get("items")).get(0);
  a.setPersonId("usr_foreign");assertThrows(RuntimeException.class,()->recent.overrideRecord(a,"forget",item.get("record_id").toString(),item.get("version").toString(),null,null));
 });}
'''
s=s.rstrip()[:-1]+addition+'\n}\n';p.write_text(s)
# Shared clock scheduler is independent of device-state counters.
R=Path('.');p=R/'main/minute_scheduler.h';p.write_text('''#pragma once
#include <ctime>
struct MinuteWindow { time_t first=0, last=-1; };
class MinuteScheduler {
public:
    MinuteWindow Advance(time_t now) {
        if (now <= 1000000000L) return {};
        const time_t minute=now/60;
        if (minute==last_) return {};
        const time_t first=last_>0 && minute>last_ && minute-last_<=3 ? last_+1 : minute;
        last_=minute; return {first,minute};
    }
private: time_t last_=0;
};
''')
p=R/'main/application.cc';s=p.read_text();start=s.index('            static time_t last_schedule_minute = 0;');end=s.index('                    time_t now = tick_minute * 60;',start)
s=s[:start]+'''            static MinuteScheduler minute_scheduler;
            const auto due_minutes = minute_scheduler.Advance(time(nullptr));
            if (due_minutes.first <= due_minutes.last) {
                for (time_t tick_minute = due_minutes.first; tick_minute <= due_minutes.last; ++tick_minute) {
'''+s[end:];s='#include "minute_scheduler.h"\n'+s;p.write_text(s)
print('new DB regressions and independent clock helper ready')
