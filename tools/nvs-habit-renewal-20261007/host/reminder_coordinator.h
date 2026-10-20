#pragma once
#include <string>
class ReminderCoordinator {public:static ReminderCoordinator& GetInstance(){static ReminderCoordinator i;return i;}bool RetirePerson(const std::string&,bool=false){return true;}};
