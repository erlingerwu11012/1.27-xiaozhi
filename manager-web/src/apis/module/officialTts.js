import { getServiceUrl } from '../api'
import RequestService from '../httpRequest'

function idem() {
    if (typeof crypto !== 'undefined' && crypto.randomUUID) {
        return crypto.randomUUID()
    }
    return 'ot-' + Date.now() + '-' + Math.random().toString(16).slice(2)
}

export default {
    capabilities(callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/official-tts/capabilities`)
            .method('GET')
            .success((res) => { RequestService.clearRequestTime(); callback(res) })
            .networkFail((err) => fail && fail(err))
            .send()
    },
    listVoices(callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/official-tts/voices`)
            .method('GET')
            .success((res) => { RequestService.clearRequestTime(); callback(res) })
            .networkFail((err) => fail && fail(err))
            .send()
    },
    createVoice(body, callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/official-tts/voices`)
            .method('POST')
            .header({ 'content-type': 'application/json; charset=utf-8', 'Idempotency-Key': idem() })
            .data(body)
            .success((res) => { RequestService.clearRequestTime(); callback(res) })
            .networkFail((err) => fail && fail(err))
            .send()
    },
    uploadClone(file, name, callback, fail) {
        const form = new FormData()
        form.append('file', file)
        form.append('kind', 'clone')
        form.append('name', name || '我的音色')
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/official-tts/assets`)
            .method('POST')
            .header({ 'Idempotency-Key': idem() })
            .data(form)
            .success((res) => { RequestService.clearRequestTime(); callback(res) })
            .networkFail((err) => fail && fail(err))
            .send()
    },
    deleteVoice(id, callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/official-tts/voices/${id}`)
            .method('DELETE')
            .success((res) => { RequestService.clearRequestTime(); callback(res) })
            .fail((err) => fail && fail(err))
            .networkFail((err) => fail && fail(err))
            .send()
    },
    renameVoice(id, name, callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/official-tts/voices/${id}`)
            .method('PUT')
            .header({ 'content-type': 'application/json; charset=utf-8' })
            .data({ name })
            .success((res) => { RequestService.clearRequestTime(); callback && callback(res) })
            .fail((err) => fail && fail(err))
            .networkFail((err) => fail && fail(err))
            .send()
    },
    /** 带鉴权拉取音色预览 Blob */
    fetchVoicePreview(id, callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/official-tts/voices/${id}/preview`)
            .method('GET')
            .type('blob')
            .success((res) => {
                RequestService.clearRequestTime()
                callback && callback(res.data, res.headers)
            })
            .fail((err) => fail && fail(err))
            .networkFail((err) => fail && fail(err))
            .send()
    },
    // 缺失试听音频时按需生成（用户点击播放才触发，避免列表加载时批量计费）
    ensureVoicePreview(id, callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/official-tts/voices/${id}/preview`)
            .method('POST')
            .type('blob')
            .success((res) => {
                RequestService.clearRequestTime()
                callback && callback(res.data, res.headers)
            })
            .fail((err) => fail && fail(err))
            .networkFail((err) => fail && fail(err))
            .send()
    },
    bindVoice(id, agentId, callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/official-tts/voices/${id}/bind?agentId=${encodeURIComponent(agentId)}`)
            .method('POST')
            .success((res) => { RequestService.clearRequestTime(); callback(res) })
            .networkFail((err) => fail && fail(err))
            .send()
    },
    listJobs(callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/official-tts/jobs`)
            .method('GET')
            .success((res) => { RequestService.clearRequestTime(); callback(res) })
            .networkFail((err) => fail && fail(err))
            .send()
    },
    createJob(body, callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/official-tts/jobs`)
            .method('POST')
            .header({ 'content-type': 'application/json; charset=utf-8', 'Idempotency-Key': idem() })
            .data(body)
            .success((res) => { RequestService.clearRequestTime(); callback(res) })
            .networkFail((err) => fail && fail(err))
            .send()
    },
    downloadJob(id) {
        return `${getServiceUrl()}/official-tts/jobs/${id}/download`
    },
    cancelJob(id, callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/official-tts/jobs/${id}/cancel`)
            .method('POST')
            .success((res) => { RequestService.clearRequestTime(); callback && callback(res) })
            .networkFail((err) => fail && fail(err))
            .send()
    },
    deleteJob(id, callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/official-tts/jobs/${id}`)
            .method('DELETE')
            .success((res) => { RequestService.clearRequestTime(); callback && callback(res) })
            .fail((err) => fail && fail(err))
            .networkFail((err) => fail && fail(err))
            .send()
    },
    /** 带鉴权拉取任务音频 Blob（用于试听/下载，避免 window.open 丢 token） */
    fetchJobAudio(id, callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/official-tts/jobs/${id}/download`)
            .method('GET')
            .type('blob')
            .success((res) => {
                RequestService.clearRequestTime()
                callback && callback(res.data, res.headers)
            })
            .fail((err) => fail && fail(err))
            .networkFail((err) => fail && fail(err))
            .send()
    },
    adminOverview(callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/admin/official-tts/overview`)
            .method('GET')
            .success((res) => { RequestService.clearRequestTime(); callback(res) })
            .networkFail((err) => fail && fail(err))
            .send()
    },
    updatePrice(body, callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/admin/official-tts/prices`)
            .method('PUT')
            .data(body)
            .success((res) => { RequestService.clearRequestTime(); callback(res) })
            .networkFail((err) => fail && fail(err))
            .send()
    },
    publishPrice(body, callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/admin/official-tts/prices/publish`)
            .method('POST')
            .header({ 'content-type': 'application/json; charset=utf-8' })
            .data(body)
            .success((res) => { RequestService.clearRequestTime(); callback(res) })
            .networkFail((err) => fail && fail(err))
            .send()
    },
    draftFromPublished(id, callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/admin/official-tts/prices/draft-from`)
            .method('POST')
            .header({ 'content-type': 'application/json; charset=utf-8' })
            .data({ id: Number(id) })
            .success((res) => { RequestService.clearRequestTime(); callback(res) })
            .networkFail((err) => fail && fail(err))
            .send()
    },
    syncPublished(id, callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/admin/official-tts/prices/sync`)
            .method('POST')
            .header({ 'content-type': 'application/json; charset=utf-8' })
            .data({ id: Number(id) })
            .success((res) => { RequestService.clearRequestTime(); callback(res) })
            .networkFail((err) => fail && fail(err))
            .send()
    },
    jobLedger(jobId, callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/admin/official-tts/jobs/${Number(jobId)}/ledger`)
            .method('GET')
            .success((res) => { RequestService.clearRequestTime(); callback(res) })
            .networkFail((err) => fail && fail(err))
            .send()
    },
    addNote(jobId, operationId, reason, evidence, callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/admin/official-tts/notes`)
            .method('POST')
            .header({ 'content-type': 'application/json; charset=utf-8' })
            .data({ jobId: Number(jobId), operationId, reason, evidence })
            .success((res) => { RequestService.clearRequestTime(); callback(res) })
            .networkFail((err) => fail && fail(err))
            .send()
    },
    settle(body, callback, fail) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/admin/official-tts/settle`)
            .method('POST')
            .header({ 'content-type': 'application/json; charset=utf-8' })
            .data(body)
            .success((res) => { RequestService.clearRequestTime(); callback(res) })
            .networkFail((err) => fail && fail(err))
            .send()
    }
}
