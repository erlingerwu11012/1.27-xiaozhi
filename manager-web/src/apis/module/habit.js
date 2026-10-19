import { getServiceUrl } from '../api';
import RequestService from '../httpRequest';

export default {
    bindingOptions(callback) {
        RequestService.sendRequest().url(`${getServiceUrl()}/habits/options`).method('GET')
            .success(res => { RequestService.clearRequestTime(); callback(res.data); })
            .networkFail(() => callback({code:500})).send();
    },
    updateHabit(id, data, callback) {
        RequestService.sendRequest().url(`${getServiceUrl()}/habits/${id}`).method('PUT').data(data)
            .success(res => { RequestService.clearRequestTime(); callback(res.data); })
            .networkFail(() => callback({code:500})).send();
    },
    /**
     * 查询手动习惯列表
     * @param {Object} params - { enabledOnly }
     * @param {Function} callback
     */
    listHabits(params, callback) {
        const enabledOnly = params.enabledOnly !== false;
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/habits?enabledOnly=${enabledOnly}`)
            .method('GET')
            .success((res) => {
                RequestService.clearRequestTime();
                callback(res.data);
            })
            .networkFail((err) => {
                console.error('获取习惯列表失败:', err);
                callback({ code: 500, msg: '请求失败' });
            })
            .send();
    },

    /**
     * 创建手动习惯
     * @param {Object} data - { description, hour, minute, advanceMinutes, intent, deviceId }
     * @param {Function} callback
     */
    createHabit(data, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/habits`)
            .method('POST')
            .data(data)
            .success((res) => {
                RequestService.clearRequestTime();
                callback(res.data);
            })
            .networkFail((err) => {
                console.error('创建习惯失败:', err);
                callback({ code: 500, msg: '请求失败' });
            })
            .send();
    },

    /**
     * 删除手动习惯（软删除）
     * @param {number} id
     * @param {Function} callback
     */
    deleteHabit(id, callback) {
        RequestService.sendRequest()
            .url(`${getServiceUrl()}/habits/${id}`)
            .method('DELETE')
            .success((res) => {
                RequestService.clearRequestTime();
                callback(res.data);
            })
            .networkFail((err) => {
                console.error('删除习惯失败:', err);
                callback({ code: 500, msg: '请求失败' });
            })
            .send();
    },
};
