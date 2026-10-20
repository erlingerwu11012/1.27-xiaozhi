#include "habit_manager.h"
#include "note_manager.h"
#include "settings.h"
#include <mbedtls/sha256.h>
#include <cassert>
#include <cstdio>
#include <memory>
#include <iostream>
#include <fstream>
using Json=std::unique_ptr<cJSON,decltype(&cJSON_Delete)>;
Json config(int source=9,bool enabled=true,int hour=8,std::string recipient="usr_abc") {
 Json p(cJSON_CreateObject(),cJSON_Delete);
 const std::string account="42",key=std::to_string(source),name="张",intent="drink",desc="喝水";
 cJSON_AddStringToObject(p.get(),"account_id",account.c_str());cJSON_AddStringToObject(p.get(),"sync_id",key.c_str());
 cJSON_AddStringToObject(p.get(),"recipient_person_id",recipient.c_str());cJSON_AddStringToObject(p.get(),"recipient_display_name",name.c_str());cJSON_AddStringToObject(p.get(),"intent",intent.c_str());cJSON_AddStringToObject(p.get(),"description",desc.c_str());
 cJSON_AddNumberToObject(p.get(),"hour",hour);cJSON_AddNumberToObject(p.get(),"minute",0);cJSON_AddNumberToObject(p.get(),"advance_minutes",2);cJSON_AddNumberToObject(p.get(),"repeat_days",127);cJSON_AddBoolToObject(p.get(),"enabled",enabled);
 std::string canonical;for(const auto& value:{account,key,recipient,name,intent,desc,std::to_string(hour),std::string("0"),std::string("2"),std::string("127"),std::string(enabled?"1":"0")})canonical+=std::to_string(value.size())+":"+value;
 unsigned char digest[32];mbedtls_sha256((const unsigned char*)canonical.data(),canonical.size(),digest,0);char hex[65];for(int i=0;i<32;++i)snprintf(hex+i*2,3,"%02x",digest[i]);cJSON_AddStringToObject(p.get(),"content_hash",hex);return p;
}
Json sync(HabitManager& h,const cJSON* p){const auto out=h.Sync(p);return Json(cJSON_Parse(out.c_str()),cJSON_Delete);}
bool okay(const Json& r){return cJSON_IsTrue(cJSON_GetObjectItem(r.get(),"ok"));}
std::string error(const Json& r){auto v=cJSON_GetObjectItem(r.get(),"error");return cJSON_IsString(v)?v->valuestring:"";}
int main(int argc,char**argv){
 if(argc>1 && std::string(argv[1])=="--ambiguous") {
    strings["habits"]["list"]=R"([{"id":1,"h":8,"m":0,"adv":2,"en":1,"intent":"drink","desc":"喝水","src":"manual","uid":"usr_legacy","cid":"usr_legacy","rid":"usr_legacy","rdn":"张","repeat_days":127},{"id":2,"h":8,"m":0,"adv":2,"en":1,"intent":"drink","desc":"喝水","src":"manual","uid":"usr_legacy","cid":"usr_legacy","rid":"usr_legacy","rdn":"张","repeat_days":127}])";
    auto& store=HabitManager::GetInstance();auto p=config(12,true,8,"usr_legacy");assert(error(sync(store,p.get()))=="legacy_ambiguous");assert(store.GetAll().size()==2&&write_count==0);
    std::cout<<"PASS: ambiguous legacy rules are not adopted or modified\n";return 0;
 }
 if(argc>1 && std::string(argv[1])=="--reload") {
    std::ifstream file("host/habits-persisted.json");strings["habits"]["list"]=std::string(std::istreambuf_iterator<char>(file),{});
    auto& store=HabitManager::GetInstance();assert(store.GetAll().size()==20);auto p=config(9,false,9);assert(okay(sync(store,p.get()))&&write_count==0);
    auto public_rule=store.GetAll()[1];assert(public_rule.recipient_person_id=="all"&&!public_rule.delivery_unbound&&public_rule.sync_account=="42");
    std::cout<<"PASS: persisted source IDs, hashes, disabled state and public recipient survive actual Load after restart\n";return 0;
 }
 auto& h=HabitManager::GetInstance();auto p=config();auto result=sync(h,p.get());assert(okay(result));assert(h.GetAll().size()==1);
 const int id=h.GetAll()[0].id,writes=write_count;
 assert(okay(sync(h,p.get())));assert(h.GetAll().size()==1&&write_count==writes); // replay does not wear NVS
 auto updated=config(9,true,9);assert(okay(sync(h,updated.get())));assert(h.GetAll()[0].id==id&&h.GetAll()[0].hour==9);
 fail_write=ESP_ERR_NVS_NOT_ENOUGH_SPACE;auto changed=config(9,true,10);assert(error(sync(h,changed.get()))=="storage_full");assert(h.GetAll()[0].hour==9);
 fail_write=ESP_FAIL;assert(error(sync(h,changed.get()))=="storage_error");assert(h.GetAll()[0].hour==9);fail_write=0;
 fail_commit=ESP_FAIL;assert(error(sync(h,changed.get()))=="storage_error");assert(h.GetAll()[0].hour==9);fail_commit=0;
 auto disabled=config(9,false,9);assert(okay(sync(h,disabled.get())));assert(!h.GetAll()[0].enabled);
 int fired=0;h.CheckAndFire(8,58,1,[&](const Habit&){++fired;return true;},1700000000);assert(fired==0);
 auto public_rule=config(10,true,8,"all");assert(okay(sync(h,public_rule.get())));assert(h.GetAll().back().recipient_person_id=="all"&&!h.GetAll().back().delivery_unbound);
 auto bad=config(11);cJSON_ReplaceItemInObject(bad.get(),"content_hash",cJSON_CreateString(std::string(64,'0').c_str()));assert(error(sync(h,bad.get()))=="hash_mismatch");assert(h.GetAll().size()==2);
 assert(h.Add(8,0,2,"drink","喝水","manual","usr_legacy","usr_legacy","张",127)>0);
 auto legacy=config(12,true,8,"usr_legacy");assert(okay(sync(h,legacy.get())));assert(h.GetAll().size()==3);assert(h.GetAll().back().sync_id=="12");
 for(int i=20;i<37;++i){auto next=config(i);assert(okay(sync(h,next.get())));}assert(h.GetAll().size()==20);auto full=config(38);assert(error(sync(h,full.get()))=="quota_exceeded");
 auto& n=NoteManager::GetInstance();std::string code;fail_write=ESP_ERR_NVS_NOT_ENOUGH_SPACE;
 assert(n.Add("喝水",0,"usr_abc","normal","general",0,"usr_abc","张",0,&code)==-1&&code=="storage_full"&&n.GetAll().empty());
 fail_write=ESP_ERR_NVS_NO_FREE_PAGES;assert(n.Add("喝水",0,"usr_abc","normal","general",0,"usr_abc","张",0,&code)==-1&&code=="storage_full");
 fail_write=ESP_FAIL;assert(n.Add("喝水",0,"usr_abc","normal","general",0,"usr_abc","张",0,&code)==-1&&code=="storage_write_failed");fail_write=0;
 for(int i=0;i<20;++i)assert(n.Add("喝水",0,"usr_abc")>0);
 assert(n.Add("喝水",0,"usr_abc","normal","general",0,"usr_abc","张",0,&code)==-1&&code=="note_limit_reached");
 std::ofstream("host/habits-persisted.json")<<strings["habits"]["list"];
 std::cout<<"PASS: production HabitManager/NoteManager replay, update, delete, public recipient, legacy adoption, hash, capacity and failure rollback\n";
}
