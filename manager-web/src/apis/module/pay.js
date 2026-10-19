import { getServiceUrl } from '../api'
import RequestService from '../httpRequest'

export default {
    hardwareCalls(page, limit, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/pay/billing/calls?page=${encodeURIComponent(page || 1)}&limit=${encodeURIComponent(limit || 20)}`)
            .method('GET').success(res => { RequestService.clearRequestTime(); callback(res.data); })
            .fail(res => callback((res && res.data) || { code: 500, msg: '调用账单读取失败' }))
            .networkFail(() => callback({ code: 500, msg: '调用账单读取失败' })).send();
    },
    memoryBills(page, callback) {
        RequestService.sendRequest().url(`${getServiceUrl()}/pay/memory-bills?page=${encodeURIComponent(page || 1)}&limit=10`)
            .method('GET').success(res => { RequestService.clearRequestTime(); callback(res.data) })
            .networkFail(() => callback({ code: 500, msg: '费用读取失败' })).send()
    },
    // 查询启用中的套餐列表
    packages(callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/pay/packages`)
            .method('GET')
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail(() => {
                callback({ code: 500, msg: '请求失败' })
            })
            .send()
    },
    // 创建支付订单（alipay 渠道返回 payForm，前端渲染后跳转支付宝）
    createOrder(packageId, channel, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/pay/order/create`)
            .method('POST')
            .data({ packageId, channel })
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail(() => {
                callback({ code: 500, msg: '请求失败' })
            })
            .send()
    },
    // 查询订单
    queryOrder(orderNo, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/pay/order/query/${encodeURIComponent(orderNo)}`)
            .method('GET')
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail(() => {
                callback({ code: 500, msg: '请求失败' })
            })
            .send()
    },
    // 分页查询当前用户订单
    orders(params, callback) {
        const query = Object.keys(params || {})
            .map((k) => `${encodeURIComponent(k)}=${encodeURIComponent(params[k])}`)
            .join('&')
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/pay/orders${query ? '?' + query : ''}`)
            .method('GET')
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail(() => {
                callback({ code: 500, msg: '请求失败' })
            })
            .send()
    },
    // 查询当前用户额度与最近流水
    myQuota(callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/pay/quota/me`)
            .method('GET')
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail(() => {
                callback({ code: 500, msg: '请求失败' })
            })
            .send()
    },
    // 查询当前用户账单汇总（余额 + 每日用量/账单）
    billingSummary(days, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/pay/billing/summary?days=${encodeURIComponent(days || 7)}`)
            .method('GET')
            .success((res) => {
                RequestService.clearRequestTime()
                callback(res.data)
            })
            .networkFail(() => {
                callback({ code: 500, msg: '请求失败' })
            })
            .send()
    }
}
