import { getServiceUrl } from '../api'
import RequestService from '../httpRequest'

function mediaUrl(pathOrAbsolute) {
    if (!pathOrAbsolute) return ''
    if (/^https?:\/\//i.test(pathOrAbsolute)) return pathOrAbsolute
    const base = getServiceUrl().replace(/\/$/, '')
    const path = pathOrAbsolute.startsWith('/') ? pathOrAbsolute : `/${pathOrAbsolute}`
    return `${base}${path}`
}

export default {
    mediaUrl,

    catalog(callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/role-packs/catalog`)
            .method('GET')
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail((err) => {
                console.error('role pack catalog request failed:', err)
                callback({ code: 500 })
            })
            .send()
    },

    detail(packId, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/role-packs/${encodeURIComponent(packId)}`)
            .method('GET')
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail((err) => {
                callback({ code: 500 })
            })
            .send()
    },

    deploy(packId, deviceId, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/role-packs/${encodeURIComponent(packId)}/deploy/${encodeURIComponent(deviceId)}`)
            .method('POST')
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail((err) => {
                callback({ code: 500 })
            })
            .send()
    },

    getTask(taskId, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/role-packs/tasks/${encodeURIComponent(taskId)}`)
            .method('GET')
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail((err) => {
                callback({ code: 500 })
            })
            .send()
    },

    inspect(spineFile, callback) {
        const form = new FormData()
        form.append('spineBin', spineFile)
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/role-packs/inspect`)
            .method('POST')
            .header({})
            .data(form)
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail((err) => {
                callback({ code: 500 })
            })
            .send()
    },

    /**
     * 管理员发布：displayName + spine.bin，可选封面/演示视频。
     */
    publish(payload, callback) {
        const form = new FormData()
        form.append('displayName', payload.displayName)
        if (payload.description) {
            form.append('description', payload.description)
        }
        form.append('spineBin', payload.spineBin)
        if (payload.previewImage) {
            form.append('previewImage', payload.previewImage)
        }
        if (payload.previewVideo) {
            form.append('previewVideo', payload.previewVideo)
        }
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/role-packs/publish`)
            .method('POST')
            .header({})
            .data(form)
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail((err) => {
                callback({ code: 500 })
            })
            .send()
    },

    disable(packId, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/role-packs/${encodeURIComponent(packId)}/disable`)
            .method('POST')
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail((err) => {
                callback({ code: 500 })
            })
            .send()
    }
}
