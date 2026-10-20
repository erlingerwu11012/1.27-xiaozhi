#pragma once
#include <vector>
#include <string>
struct UserIdentity {std::string user_id,display_name;};
class IdentityManager {std::vector<UserIdentity> people;public:static IdentityManager& GetInstance(){static IdentityManager i;return i;}auto GetAll(){return people;}bool ReplaceFromServer(const std::vector<UserIdentity>& p){people=p;return true;}};
