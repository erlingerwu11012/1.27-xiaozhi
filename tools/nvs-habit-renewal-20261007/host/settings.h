#pragma once
#include <map>
#include <string>
#include <cstdint>
using esp_err_t=int;
constexpr int ESP_OK=0,ESP_FAIL=-1,ESP_ERR_NVS_NOT_ENOUGH_SPACE=0x1105,ESP_ERR_NVS_NO_FREE_PAGES=0x110d;
struct nvs_stats_t {size_t used_entries=0,free_entries=0,total_entries=0;};
inline int nvs_get_stats(const char*,nvs_stats_t* s){s->free_entries=50;s->total_entries=100;return ESP_OK;}
inline int fail_write=0,fail_commit=0,write_count=0;
inline std::map<std::string,std::map<std::string,std::string>> strings;
inline std::map<std::string,std::map<std::string,int>> integers;
class Settings {
 std::string ns;
 public:
 enum class ReadStatus {Ok,NotFound,Error};
 Settings(std::string n,bool=false):ns(n){}
 std::string GetJson(std::string key,std::string fallback=""){auto i=strings[ns].find(key);return i==strings[ns].end()?fallback:i->second;}
 ReadStatus TryGetJson(std::string key,std::string* out){auto i=strings[ns].find(key);if(i==strings[ns].end())return ReadStatus::NotFound;*out=i->second;return ReadStatus::Ok;}
 int GetInt(std::string key,int fallback=0){auto i=integers[ns].find(key);return i==integers[ns].end()?fallback:i->second;}
 int SetJson(std::string key,std::string value){++write_count;if(fail_write)return fail_write;strings[ns][key]=value;return 0;}
 int SetInt(std::string key,int value){if(fail_write)return fail_write;integers[ns][key]=value;return 0;}
 int Commit(){return fail_commit;}
};
