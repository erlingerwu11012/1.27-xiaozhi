#pragma once
#include <string>
class BehaviorLogger {public:static BehaviorLogger& GetInstance(){static BehaviorLogger i;return i;}bool RetirePerson(const std::string&){return true;}};
