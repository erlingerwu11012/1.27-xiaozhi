#include "nvs_flash.h"
#include "reminder_coordinator.h"
#include <map>
#include <string>
#include <cstring>
#include <mutex>

bool fail_nvs = false;
bool fail_reminder_cleanup = false;
namespace {
struct Data { std::map<std::string,std::string> strings,blobs; std::map<std::string,int32_t> integers; std::map<std::string,uint8_t> bytes; };
struct Handle {std::string ns;Data staged;bool rw;};
std::map<std::string,Data> values;
std::map<nvs_handle_t,Handle> handles;
nvs_handle_t next_handle=1;
std::mutex mu;
}
esp_err_t nvs_open(const char* ns,nvs_open_mode_t mode,nvs_handle_t* output) {
    std::lock_guard<std::mutex> lock(mu);
    if (mode==NVS_READONLY && !values.count(ns)) return ESP_ERR_NVS_NOT_FOUND;
    *output=next_handle++;handles[*output]={ns,values[ns],mode==NVS_READWRITE};return ESP_OK;
}
void nvs_close(nvs_handle_t handle){std::lock_guard<std::mutex> lock(mu);handles.erase(handle);}
esp_err_t nvs_commit(nvs_handle_t handle){std::lock_guard<std::mutex> lock(mu);if(fail_nvs)return ESP_FAIL;values[handles.at(handle).ns]=handles.at(handle).staged;return ESP_OK;}
esp_err_t nvs_get_str(nvs_handle_t handle,const char* key,char* output,size_t* length){
    std::lock_guard<std::mutex> lock(mu);auto& data=handles.at(handle).staged.strings;
    if(handles.at(handle).staged.blobs.count(key))return ESP_FAIL;
    if(!data.count(key))return ESP_ERR_NVS_NOT_FOUND;
    auto& text=data.at(key);if(!output){*length=text.size()+1;return ESP_OK;}
    if(*length<text.size()+1)return ESP_ERR_NVS_INVALID_LENGTH;
    std::memcpy(output,text.c_str(),text.size()+1);*length=text.size()+1;return ESP_OK;
}
esp_err_t nvs_set_str(nvs_handle_t handle,const char* key,const char* value){std::lock_guard<std::mutex> lock(mu);if(fail_nvs)return ESP_FAIL;handles.at(handle).staged.strings[key]=value;handles.at(handle).staged.blobs.erase(key);return ESP_OK;}
esp_err_t nvs_get_blob(nvs_handle_t handle,const char* key,void* output,size_t* length){std::lock_guard<std::mutex> lock(mu);auto& data=handles.at(handle).staged.blobs;if(!data.count(key))return ESP_ERR_NVS_NOT_FOUND;auto& blob=data[key];if(!output){*length=blob.size();return ESP_OK;}if(*length<blob.size())return ESP_ERR_NVS_INVALID_LENGTH;memcpy(output,blob.data(),blob.size());*length=blob.size();return ESP_OK;}
esp_err_t nvs_set_blob(nvs_handle_t handle,const char* key,const void* value,size_t length){std::lock_guard<std::mutex> lock(mu);if(fail_nvs)return ESP_FAIL;handles.at(handle).staged.blobs[key]=std::string(static_cast<const char*>(value),length);handles.at(handle).staged.strings.erase(key);return ESP_OK;}
esp_err_t nvs_get_i32(nvs_handle_t handle,const char* key,int32_t* output){std::lock_guard<std::mutex> lock(mu);auto& data=handles.at(handle).staged.integers;if(!data.count(key))return ESP_ERR_NVS_NOT_FOUND;*output=data[key];return ESP_OK;}
esp_err_t nvs_set_i32(nvs_handle_t handle,const char* key,int32_t value){std::lock_guard<std::mutex> lock(mu);if(fail_nvs)return ESP_FAIL;handles.at(handle).staged.integers[key]=value;return ESP_OK;}
esp_err_t nvs_get_u8(nvs_handle_t handle,const char* key,uint8_t* output){std::lock_guard<std::mutex> lock(mu);auto& data=handles.at(handle).staged.bytes;if(!data.count(key))return ESP_ERR_NVS_NOT_FOUND;*output=data[key];return ESP_OK;}
esp_err_t nvs_set_u8(nvs_handle_t handle,const char* key,uint8_t value){std::lock_guard<std::mutex> lock(mu);if(fail_nvs)return ESP_FAIL;handles.at(handle).staged.bytes[key]=value;return ESP_OK;}
esp_err_t nvs_erase_key(nvs_handle_t handle,const char* key){std::lock_guard<std::mutex> lock(mu);auto& data=handles.at(handle).staged;data.strings.erase(key);data.integers.erase(key);data.bytes.erase(key);return ESP_OK;}
esp_err_t nvs_erase_all(nvs_handle_t handle){std::lock_guard<std::mutex> lock(mu);handles.at(handle).staged={};return ESP_OK;}
ReminderCoordinator& ReminderCoordinator::GetInstance(){static ReminderCoordinator instance;return instance;}
// Presentation and actual sound are hardware acceptance items. Directory tests
// exercise retry behavior by injecting this one cleanup dependency.
bool ReminderCoordinator::RetirePerson(const std::string&,bool){return !fail_reminder_cleanup;}
