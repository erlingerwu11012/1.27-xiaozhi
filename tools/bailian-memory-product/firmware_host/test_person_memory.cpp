#include "person_turn.h"
#include "weekly_schedule.h"
#include "person_directory.h"
#include "behavior_logger.h"
#include "habit_manager.h"
#include "note_manager.h"
#include "alarm_manager.h"
#include "identity_manager.h"
#include "settings.h"
#include <cassert>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <thread>
extern bool fail_nvs;
extern bool fail_reminder_cleanup;

std::string apply(const char* json){auto state=cJSON_Parse(json);auto result=PersonDirectory::GetInstance().Apply(state);cJSON_Delete(state);return result;}
int main(){
    {Settings settings("long_json",true);assert(settings.SetJson("value",std::string(5000,'x'))==ESP_OK);assert(settings.Commit()==ESP_OK);}
    {Settings settings("long_json");assert(settings.GetJson("value")==std::string(5000,'x'));}
    // Monday Jan 5, 2026, 00:05 Asia/Shanghai; Sunday 23:55 pre-alert.
    const time_t monday=1767542700;
    assert(ScheduleWeekday(ScheduleDay(monday))==1);
    assert(HabitOccurrenceAt(monday-10*60,0,5,10,62)==monday);
    const auto friday=WeeklyDueOnDay(ScheduleDay(monday)+4,8,0);
    assert(NextWeeklyDue(friday,8,0,62)==WeeklyDueOnDay(ScheduleDay(monday)+7,8,0));
    assert(HabitOccurrenceAt(friday+86400,8,0,0,62)==0);
    assert(Utf8Prefix("中文测试",4)=="中");
    PersonTurn a;a.account_id="10";a.person_id="usr_a";a.turn_id="turn_a";a.status="matched";a.directory_version=2;a.voiceprint_id="voice_a";a.template_version=1;
    PersonTurn b=a;b.person_id="usr_b";b.turn_id="turn_b";
    {PersonTurnScope scope(a);assert(bound_person_turn->person_id=="usr_a");std::thread other([]{assert(!bound_person_turn);});other.join();{PersonTurnScope inner(b);assert(bound_person_turn->person_id=="usr_b");}assert(bound_person_turn->person_id=="usr_a");}
    assert(!bound_person_turn);
    auto& habits=HabitManager::GetInstance();auto& notes=NoteManager::GetInstance();auto& alarms=AlarmManager::GetInstance();
    int ha=habits.Add(8,0,0,"drink","爸爸喝水","auto","usr_a","usr_a","爸爸",62);
    int hb=habits.Add(8,0,0,"drink","孩子喝水","auto","usr_b","usr_b","孩子",62);
    assert(ha>0 && hb>0 && ha!=hb);
    for(int i=0;i<3;i++)habits.Reject(ha);
    assert(!habits.GetAll("usr_a")[0].enabled);
    assert(habits.Add(8,0,0,"drink","再次分析","auto","usr_a","usr_a","爸爸",62)==ha);
    assert(!habits.GetAll("usr_a")[0].enabled);
    int note=notes.Add("工作日",friday,"usr_b","normal","general",0,"usr_b","孩子",62);
    int fires=0;notes.CheckAndRemind(friday,[&](const Note&){fires++;return true;});notes.CheckAndRemind(friday,[&](const Note&){fires++;return true;});assert(fires==1);
    assert(notes.CompleteOccurrence(note));assert(notes.GetAll("usr_b").size()==1);
    auto due=notes.GetAll("usr_b")[0].remind_at;assert(ScheduleWeekday(ScheduleDay(due))==1);
    assert(alarms.Add(25,0,"无效",62,"usr_b")==-1);
    fail_nvs=true;
    assert(habits.Add(9,0,0,"fail","不能假成功","auto","usr_a")==-1);
    assert(notes.Add("失败",0,"usr_a")==-1);
    assert(alarms.Add(9,0,"失败",62,"usr_a")==-1);
    assert(!habits.RetirePerson("usr_a"));assert(habits.GetAll("usr_a").size()==1);
    fail_nvs=false;assert(habits.RetirePerson("usr_a"));assert(habits.GetAll("usr_b").size()==1);
    auto& logger=BehaviorLogger::GetInstance();assert(BehaviorLogger::Init());
    {PersonTurnScope scope(a);std::string row;assert(logger.Log("drink","中文",8,0,"failed",&row));assert(row.find("failed")!=std::string::npos);}
    {PersonTurnScope scope(b);assert(logger.Log("drink","孩子",8,0));}
    assert(!logger.Log("unknown","不记",8,0));
    {std::ofstream out(BehaviorLogger::kLogPath,std::ios::app);out<<std::string(10000,'x')<<'\n';}
    auto page=logger.Export("usr_a",0);auto json=cJSON_Parse(page.c_str());assert(cJSON_GetArraySize(cJSON_GetObjectItem(json,"records"))==1);cJSON_Delete(json);
    assert(logger.Acknowledge("usr_a",1));assert(logger.ReadAll().find("孩子")!=std::string::npos);assert(logger.ReadAll().find("中文")==std::string::npos);
    assert(apply(R"({"account_id":"10","directory_version":2,"mode":"personal","default_generation":1,"default_user_id":"","members":[{"user_id":"usr_a","display_name":"爸爸"},{"user_id":"usr_b","display_name":"孩子"}],"voice_profiles":[{"voiceprint_id":"voice_a","user_id":"usr_a","template_version":1}],"cleanup_tasks":[]})").find("\"ok\":true")!=std::string::npos);
    assert(PersonDirectory::GetInstance().Accepts(a));assert(!PersonDirectory::GetInstance().Accepts(b));
    assert(apply(R"({"account_id":"10","directory_version":1,"mode":"personal","members":[],"voice_profiles":[],"cleanup_tasks":[]})").find("stale_directory")!=std::string::npos);
    assert(PersonDirectory::GetInstance().Accepts(a));
    a.directory_version=1;assert(!PersonDirectory::GetInstance().Accepts(a));a.directory_version=2;
    fail_reminder_cleanup=true;
    const char* retired=R"({"account_id":"10","directory_version":3,"mode":"personal","default_generation":1,"default_user_id":"","members":[{"user_id":"usr_a","display_name":"爸爸"}],"voice_profiles":[{"voiceprint_id":"voice_a","user_id":"usr_a","template_version":1}],"cleanup_tasks":[{"id":"clean_b","user_id":"usr_b","generation":0,"directory_version":3}]})";
    assert(apply(retired).find("\"ok\":false")!=std::string::npos);assert(!PersonDirectory::GetInstance().Ready());
    fail_reminder_cleanup=false;assert(apply(retired).find("clean_b")!=std::string::npos);assert(PersonDirectory::GetInstance().Ready());
    assert(notes.GetAll("usr_b").empty());assert(habits.GetAll("usr_b").empty());assert(IdentityManager::GetInstance().GetAll().size()==1);
    std::cout<<"Firmware person, directory, ownership, log recovery, weekday and persistence tests passed\n";
}
