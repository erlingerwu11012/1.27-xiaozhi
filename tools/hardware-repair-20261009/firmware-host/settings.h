#pragma once
#include <string>
#include <map>
constexpr int ESP_OK=0;
class Settings { public:
 inline static std::map<std::string,std::string> disk;
 inline static bool fail=false;
 std::string ns; std::map<std::string,std::string> pending;
 Settings(const std::string& n,bool rw=false):ns(n){}
 std::string GetJson(const std::string& k,const std::string& f="") {auto i=disk.find(ns+k);return i==disk.end()?f:i->second;}
 int SetJson(const std::string& k,const std::string& v){if(fail)return -1;pending[ns+k]=v;return 0;}
 int Commit(){if(fail)return -1;for(auto& p:pending)disk[p.first]=p.second;return 0;}
};
