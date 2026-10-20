#include <string>
#include <vector>
#include <functional>
#include <mutex>
#include <map>
#include <cstdint>
#include <cassert>
#include <iostream>
#define private public
#include "alarm_manager.h"
#undef private
#include "settings.h"
#include "minute_scheduler.h"
int main(){
 MinuteScheduler s;assert(s.Advance(0).last<0);
 const time_t t=1791529200;
 auto one=s.Advance(t);assert(one.first==t/60 && one.last==t/60);
 for(int i=0;i<59;i++)assert(s.Advance(t+i).last<0); // listening state switches don't reset scheduler
 auto next=s.Advance(t+60);assert(next.first==t/60+1);
 auto delayed=s.Advance(t+180);assert(delayed.last-delayed.first==1);
 auto offline=s.Advance(t+3600);assert(offline.first==offline.last);
 auto backward=s.Advance(t+60);assert(backward.first==backward.last);
 Settings::disk.clear();Settings::fail=false;AlarmManager a;
 assert(a.Add(17,40,"drink",127,"usr_a","usr_a")>0);
 int fired=0; a.CheckAndFire(17,39,5,2026281,[&](const Alarm&){fired++;});assert(fired==0);
 a.CheckAndFire(17,40,5,2026281,[&](const Alarm& x){fired++;assert(a.GetAll().size()==1);assert(x.last_triggered_at>0);});assert(fired==1);
 a.CheckAndFire(17,40,5,2026281,[&](const Alarm&){fired++;});assert(fired==1);
 AlarmManager restarted;restarted.CheckAndFire(17,40,5,2026281,[&](const Alarm&){fired++;});assert(fired==1);
 restarted.CheckAndFire(17,40,6,2026282,[&](const Alarm&){fired++;});assert(fired==2);
 assert(a.Add(18,0,"one",0,"usr_a","usr_a")>0);
 a.CheckAndFire(18,0,5,2026281,[&](const Alarm&){fired++;});assert(fired==3);
 AlarmManager r2;r2.CheckAndFire(18,0,5,2026281,[&](const Alarm&){fired++;});assert(fired==3);
 auto before=r2.GetAll().size();Settings::fail=true;assert(r2.Add(19,0,"fail",0,"usr_a","usr_a")==-1);assert(r2.GetAll().size()==before);
 r2.CheckAndFire(17,40,0,2026283,[&](const Alarm&){fired++;});assert(fired==3);
 Settings::fail=false;r2.CheckAndFire(17,40,0,2026283,[&](const Alarm&){fired++;});assert(fired==4);
 std::cout<<"PASS alarm scheduling, persisted occurrence, reboot, reentrant callback, storage rollback"<<std::endl;
}
