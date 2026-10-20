import { getServiceUrl } from '../api'
import RequestService from '../httpRequest'

export default {
    listProfiles(includeDraft, callback) {
        const flag = includeDraft !== false
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/face/profiles?include_draft=${flag ? 'true' : 'false'}`)
            .method('GET')
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail(() => callback({ code: 500, msg: '请求失败' }))
            .send()
    },

    createProfile(displayName, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/face/profiles`)
            .method('POST')
            .data({ display_name: displayName })
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail(() => callback({ code: 500, msg: '请求失败' }))
            .send()
    },

    uploadFace(userId, file, callback) {
        const formData = new FormData()
        formData.append('image', file)
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/face/profiles/${encodeURIComponent(userId)}/faces`)
            .method('POST')
            .header({}) // 让浏览器为 FormData 自动带 multipart boundary
            .data(formData)
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail(() => callback({ code: 500, msg: '请求失败' }))
            .send()
    },

    activateProfile(userId, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/face/profiles/${encodeURIComponent(userId)}/activate`)
            .method('POST')
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail(() => callback({ code: 500, msg: '请求失败' }))
            .send()
    },

    deleteProfile(userId, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/face/profiles/${encodeURIComponent(userId)}`)
            .method('DELETE')
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail(() => callback({ code: 500, msg: '请求失败' }))
            .send()
    },

    listEnrollmentSessions(callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/face/enrollment/sessions`)
            .method('GET')
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail(() => callback({ code: 500, msg: '请求失败' }))
            .send()
    },

    /** 受鉴权保护的预览图 → Blob URL */
    fetchEnrollmentPreview(sessionId, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/face/enrollment/sessions/${encodeURIComponent(sessionId)}/preview`)
            .method('GET')
            .type('blob')
            .success((res) => {
                RequestService.clearRequestTime()
                try {
                    const blob = res.data
                    const url = URL.createObjectURL(blob)
                    callback({ code: 0, url })
                } catch (e) {
                    callback({ code: 500, msg: '预览失败' })
                }
            })
            .networkFail(() => callback({ code: 500, msg: '请求失败' }))
            .send()
    },

    confirmEnrollment(sessionId, displayName, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/face/enrollment/sessions/${encodeURIComponent(sessionId)}/confirm`)
            .method('POST')
            .data({ display_name: displayName })
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail(() => callback({ code: 500, msg: '请求失败' }))
            .send()
    },

    discardEnrollment(sessionId, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/face/enrollment/sessions/${encodeURIComponent(sessionId)}`)
            .method('DELETE')
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail(() => callback({ code: 500, msg: '请求失败' }))
            .send()
    },
}
