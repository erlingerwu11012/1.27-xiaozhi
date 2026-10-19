import RequestService from '../httpRequest';

const PYTHON_API = process.env.VUE_APP_PYTHON_API_URL || '';

export default {
    /**
     * 获取记忆列表
     * @param {Object} params - { device_id, page, limit }
     * @param {Function} callback
     */
    getMemoryList(params, callback) {
        const query = new URLSearchParams({
            page: params.page || 1,
            limit: params.limit || 20,
        });
        if (params.device_id) {
            query.set('device_id', params.device_id);
        }
        RequestService.sendRequest()
            .url(`${PYTHON_API}/admin/memory?${query.toString()}`)
            .method('GET')
            .success((res) => {
                RequestService.clearRequestTime();
                callback(res.data);
            })
            .networkFail((err) => {
                console.error('获取记忆列表失败:', err);
                callback({ code: 500, msg: '请求失败' });
            })
            .send();
    },

    /**
     * 删除单条记忆
     * @param {number} id
     * @param {Function} callback
     */
    deleteMemory(id, callback) {
        RequestService.sendRequest()
            .url(`${PYTHON_API}/admin/memory/${id}`)
            .method('DELETE')
            .success((res) => {
                RequestService.clearRequestTime();
                callback(res.data);
            })
            .networkFail((err) => {
                console.error('删除记忆失败:', err);
                callback({ code: 500, msg: '请求失败' });
            })
            .send();
    },

    /**
     * 清空某设备全部记忆
     * @param {string} device_id
     * @param {Function} callback
     */
    clearDeviceMemory(device_id, callback) {
        RequestService.sendRequest()
            .url(`${PYTHON_API}/admin/memory/device/${encodeURIComponent(device_id)}`)
            .method('DELETE')
            .success((res) => {
                RequestService.clearRequestTime();
                callback(res.data);
            })
            .networkFail((err) => {
                console.error('清空设备记忆失败:', err);
                callback({ code: 500, msg: '请求失败' });
            })
            .send();
    },
};
