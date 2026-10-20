#include "person_directory.h"
#include "habit_manager.h"
#include <cassert>
#include <iostream>
int main(){
 auto& dir=PersonDirectory::GetInstance();int calls=0;
 auto apply=[&](){++calls;return "ok";};
 assert(dir.WithManagement("42",1,"all",apply)!="ok"&&calls==0);
 auto state=cJSON_Parse(R"({"account_id":"42","directory_version":1,"mode":"default","default_generation":1,"default_user_id":"usr_abc","members":[{"user_id":"usr_abc","display_name":"张"}],"voice_profiles":[],"cleanup_tasks":[]})");
 auto result=dir.Apply(state);cJSON_Delete(state);assert(result.find("\"ok\":true")!=std::string::npos);
 assert(dir.WithManagement("42",1,"all",apply)=="ok");assert(dir.WithManagement("42",1,"usr_abc",apply)=="ok");
 assert(dir.WithManagement("43",1,"usr_abc",apply)!="ok");assert(dir.WithManagement("42",2,"usr_abc",apply)!="ok");assert(dir.WithManagement("42",1,"usr_foreign",apply)!="ok");assert(calls==2);
 dir.Invalidate();assert(dir.WithManagement("42",1,"usr_abc",apply)!="ok");assert(calls==2);
 std::cout<<"PASS: actual PersonDirectory management validates ready connection directory, account, version, registered or public recipient without speaker identity\n";
}
