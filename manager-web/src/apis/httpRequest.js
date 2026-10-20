import Fly from 'flyio/dist/npm/fly';
import store from '../store/index';
import Constant from '../utils/constant';
import { goToPage, isNotNull, showDanger, showWarning } from '../utils/index';
import i18n from '../i18n/index';

// 数据模式在构建期确定：只有 VUE_APP_DATA_MODE=real 才走真实接口，其余一律 mock。
// 条件是构建期常量，real 构建时 webpack 会整段剔除 src/mock，不把演示数据打进正式包。
// （必须写成小写 real；留空或其他任何值都是 mock）
const USE_MOCK = process.env.VUE_APP_DATA_MODE !== 'real'
const mockRequest = process.env.VUE_APP_DATA_MODE !== 'real' ? require('../mock/index').mockRequest : null

const fly = new Fly()
// 设置超时
fly.config.timeout = 30000

/**
 * Request服务封装
 */
export default {
    sendRequest,
    reAjaxFun,
    clearRequestTime
}

function sendRequest() {
    return {
        _sucCallback: null,
        _failCallback: null,
        _networkFailCallback: null,
        _method: 'GET',
        _data: {},
        _header: { 'content-type': 'application/json; charset=utf-8' },
        _url: '',
        _responseType: undefined, // 新增响应类型字段
        'send'() {
            // 设置语言请求头
            const currentLang = i18n.locale;
            // 转换语言代码格式，将zh_CN转换为zh-CN
            let acceptLanguage = currentLang.replace('_', '-');
            // 为英语添加默认地区代码
            if (acceptLanguage === 'en') {
                acceptLanguage = 'en-US';
            }
            this._header['Accept-Language'] = acceptLanguage;
            
            if (isNotNull(store.getters.getToken)) {
                this._header.Authorization = 'Bearer ' + (JSON.parse(store.getters.getToken)).token
            }

            // mock 模式（默认）由 src/mock 在浏览器内应答，不发出网络请求；real 模式走原 flyio
            const transport = USE_MOCK ? mockRequest : fly.request.bind(fly);
            transport(this._url, this._data, {
                method: this._method,
                headers: this._header,
                responseType: this._responseType
            }).then((res) => {
                const error = httpHandlerError(res, this._failCallback, this._networkFailCallback);
                if (error) {
                    notifyUnhandledFailure(this._url, res, res && res.status === 200 ? this._failCallback : this._networkFailCallback)
                    return
                }

                if (this._sucCallback) {
                    this._sucCallback(res)
                }
            }).catch((res) => {
                // 打印失败响应
                console.log('catch', res)
                httpHandlerError(res, this._failCallback, this._networkFailCallback)
                notifyUnhandledFailure(this._url, res, this._networkFailCallback)
            })
            return this
        },
        'success'(callback) {
            this._sucCallback = callback
            return this
        },
        'fail'(callback) {
            this._failCallback = callback
            return this
        },
        'networkFail'(callback) {
            this._networkFailCallback = callback
            return this
        },
        'url'(url) {
            if (url) {
                url = url.replaceAll('$', '/')
            }
            this._url = url
            return this
        },
        'data'(data) {
            this._data = data
            return this
        },
        'method'(method) {
            this._method = method
            return this
        },
        'header'(header) {
            this._header = header
            return this
        },
        'showLoading'(showLoading) {
            this._showLoading = showLoading
            return this
        },
        'async'(flag) {
            this.async = flag
        },
        // 新增类型设置方法
        'type'(responseType) {
            this._responseType = responseType;
            return this;
        }
    }
}

/**
 * Info 请求完成后返回信息
 * failCallback 回调函数
 * networkFailCallback 回调函数
 */
// 在错误处理函数中添加日志
/**
 * 调用方没有传 fail / networkFail 回调时，原逻辑只弹出全局提示，页面收不到任何结果。
 * 这里额外广播一个 window 事件 `xn:request-failed`（detail: { url, status, code, msg }），
 * 让页面可以结束加载状态；不改变原有的提示、401 跳转与回调行为。
 */
function notifyUnhandledFailure(url, info, handler) {
    if (handler || typeof window === 'undefined' || typeof window.CustomEvent !== 'function') return
    const data = (info && info.data) || {}
    if (info && info.status === 200 && data.code === 401) return
    window.dispatchEvent(new window.CustomEvent('xn:request-failed', {
        detail: { url: String(url || ''), status: info && info.status, code: data.code, msg: data.msg }
    }))
}

function httpHandlerError(info, failCallback, networkFailCallback) {

    /** 请求成功，退出该函数 可以根据项目需求来判断是否请求成功。这里判断的是status为200的时候是成功 */
    let networkError = false
    if (info.status === 200) {
        if (info.data.code === 'success' || info.data.code === 0 || info.data.code === undefined) {
            return networkError
        } else if (info.data.code === 401) {
            store.commit('clearAuth');
            goToPage(Constant.PAGE.LOGIN, true);
            return true
        } else {
            // 直接使用后端返回的国际化消息
            let errorMessage = info.data.msg;
            
            if (failCallback) {
                failCallback(info)
            } else {
                showDanger(errorMessage)
            }
            return true
        }
    }
    if (networkFailCallback) {
        networkFailCallback(info)
    } else {
        showDanger(`网络请求出现了错误【${info.status}】`)
    }
    return true
}

let requestTime = 0
let reAjaxSec = 2

function reAjaxFun(fn) {
    let nowTimeSec = new Date().getTime() / 1000
    if (requestTime === 0) {
        requestTime = nowTimeSec
    }
    let ajaxIndex = parseInt((nowTimeSec - requestTime) / reAjaxSec)
    if (ajaxIndex > 10) {
        showWarning('似乎无法连接服务器')
    } else {
        showWarning('正在连接服务器(' + ajaxIndex + ')')
    }
    if (ajaxIndex < 10 && fn) {
        setTimeout(() => {
            fn()
        }, reAjaxSec * 1000)
    }
}

function clearRequestTime() {
    requestTime = 0
}