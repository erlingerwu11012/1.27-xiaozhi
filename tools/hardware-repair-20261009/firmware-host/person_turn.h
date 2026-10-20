#pragma once
#include <string>
#include <algorithm>
inline bool IsPersonId(const std::string& x){return x.rfind("usr_",0)==0 || x=="all";}
inline std::string Utf8Prefix(const std::string& s,size_t n){return s.substr(0,n);}
