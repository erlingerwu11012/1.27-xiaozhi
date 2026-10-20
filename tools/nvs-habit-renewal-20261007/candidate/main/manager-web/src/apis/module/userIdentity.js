import { getServiceUrl } from '../api'
import RequestService from '../httpRequest'

function request(method, path, data, callback) {
  RequestService.sendRequest()
    .url(getServiceUrl() + path)
    .method(method)
    .data(data)
    .success((res) => {
      RequestService.clearRequestTime()
      callback(res.data)
    })
    .networkFail(() => callback({ code: 500, msg: '请求失败' }))
    .send()
}

export default {
  list(callback) { request('GET', '/user-identities/users', null, callback) },
  voices(callback) { request('GET', '/user-identities/voiceprints', null, callback) },
  remove(userId,callback) { request('DELETE','/user-identities/users/'+encodeURIComponent(userId),null,callback) },
  create(data, callback) { request('POST', '/user-identities/users', data, callback) },
  updateDisplayName(userId, data, callback) {
    request('PUT', '/user-identities/users/' + encodeURIComponent(userId) + '/display-name', data, callback)
  },
  bindFace(userId, faceProfileId, callback) {
    request('POST', '/user-identities/users/' + encodeURIComponent(userId) + '/faces/' + encodeURIComponent(faceProfileId), null, callback)
  },
  unbindFace(userId, faceProfileId, callback) {
    request('DELETE', '/user-identities/users/' + encodeURIComponent(userId) + '/faces/' + encodeURIComponent(faceProfileId), null, callback)
  },
  bindVoiceprint(userId, voiceprintId, callback) {
    request('POST', '/user-identities/users/' + encodeURIComponent(userId) + '/voiceprints/' + encodeURIComponent(voiceprintId), null, callback)
  },
  unbindVoiceprint(userId, voiceprintId, callback) {
    request('DELETE', '/user-identities/users/' + encodeURIComponent(userId) + '/voiceprints/' + encodeURIComponent(voiceprintId), null, callback)
  },
}
