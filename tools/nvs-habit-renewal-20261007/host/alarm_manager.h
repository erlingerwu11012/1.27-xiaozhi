#pragma once
#include <string>
class AlarmManager {public:static AlarmManager& GetInstance(){static AlarmManager i;return i;}bool RetirePerson(const std::string&,bool=false){return true;}};
