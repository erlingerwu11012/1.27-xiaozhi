#pragma once
class UserContext {public:static UserContext& GetInstance(){static UserContext i;return i;}void ClearCurrentSpeakerUser(){}void ClearSessionUserId(){}void ClearActiveUserId(){}void ClearCurrentPresentUser(){}};
