from pathlib import Path
root=Path(__file__).parent/'candidate/main/manager-web/src'
p=root/'apis/module/habit.js';s=p.read_text(encoding='utf-8')
s=s.replace('export default {','''export default {
    bindingOptions(callback) {
        RequestService.sendRequest().url(`${getServiceUrl()}/habits/options`).method('GET')
            .success(res => { RequestService.clearRequestTime(); callback(res.data); })
            .networkFail(() => callback({code:500})).send();
    },
    updateHabit(id, data, callback) {
        RequestService.sendRequest().url(`${getServiceUrl()}/habits/${id}`).method('PUT').data(data)
            .success(res => { RequestService.clearRequestTime(); callback(res.data); })
            .networkFail(() => callback({code:500})).send();
    },''');p.write_text(s,encoding='utf-8')
p=root/'views/HabitManagement.vue';s=p.read_text(encoding='utf-8')
s=s.replace(":type=\"row.synced === 1 ? 'success' : 'warning'\"", ":type=\"row.syncState === 'synced' ? 'success' : 'warning'\"")
s=s.replace("{{ row.synced === 1\n                                        ? $t('habitManagement.syncedYes')\n                                        : $t('habitManagement.syncedNo') }}",'{{ statusText(row) }}')
s=s.replace('width="100"\n                            fixed="right"','width="160"\n                            fixed="right"')
s=s.replace('<template slot-scope="{ row }">\n                                <el-button\n                                    type="danger"','<template slot-scope="{ row }">\n                                <el-button size="mini" @click="editHabit(row)" :disabled="row.enabled !== 1">编辑</el-button>\n                                <el-button\n                                    :disabled="row.enabled !== 1"\n                                    type="danger"')
s=s.replace('maxlength="50"','maxlength="32"').replace(':max="60"',':max="30"').replace('min: 1, max: 50','min: 1, max: 32')
old='''                <el-form-item :label="$t('habitManagement.form.deviceId')">
                    <el-input
                        v-model="form.deviceId"
                        :placeholder="$t('habitManagement.form.deviceIdPlaceholder')"
                    />
                </el-form-item>'''
new='''                <el-form-item label="提醒设备" prop="deviceId">
                    <el-select v-model="form.deviceId" placeholder="选择本账号的设备" style="width:100%">
                        <el-option v-for="d in devices" :key="d.deviceId" :value="d.deviceId" :label="(d.deviceName || d.alias || '设备') + ' · ' + d.deviceId" />
                    </el-select>
                </el-form-item>
                <el-form-item label="接收人" prop="recipientPersonId">
                    <el-select v-model="form.recipientPersonId" placeholder="明确选择接收人" style="width:100%">
                        <el-option label="公共接收人（all）" value="all" />
                        <el-option v-for="p in people" :key="p.user_id" :label="p.display_name" :value="p.user_id" />
                    </el-select>
                </el-form-item>
                <p class="form-tip">设备保存成功后才显示“已同步”。旧记录请先编辑绑定，旧固件需要升级。删除后需设备在线确认停止提醒。</p>'''
assert old in s;s=s.replace(old,new)
s=s.replace('            habitList: [],','            habitList: [],\n            devices: [], people: [], editingId: null, refreshTimer: null,')
s=s.replace('                deviceId: "",','                deviceId: "",\n                recipientPersonId: "",')
s=s.replace('            return {\n                description:', '            return {\n                deviceId: [{required:true,message:"请选择提醒设备",trigger:"change"}],\n                recipientPersonId: [{required:true,message:"请选择接收人",trigger:"change"}],\n                description:')
s=s.replace('        this.loadHabits();\n    },\n    methods:', '        this.loadHabits();\n        this.refreshTimer = setInterval(() => this.loadHabits(), 15000);\n    },\n    beforeDestroy() { clearInterval(this.refreshTimer); },\n    methods:')
s=s.replace('        openCreateDialog() {\n            this.dialogVisible = true;\n        },','''        loadOptions() {
            Api.habit.bindingOptions(res => { if(res && res.code===0) { this.devices=res.data.devices; this.people=res.data.people; } });
        },
        statusText(row) {
            const labels={needs_binding:'待绑定',pending:'待同步',upgrade_required:'需升级固件',failed:'同步失败',synced:row.enabled===1?'已同步':'已停止提醒'};
            const reasons={device_offline:'设备离线',receipt_timeout:'回执超时，将核对重试',storage_full:'存储空间不足',storage_error:'保存失败',quota_exceeded:'规则数量已满',identity_mismatch:'人员目录不匹配',directory_not_ready:'人员目录同步中',legacy_ambiguous:'旧规则存在歧义',ownership_mismatch:'设备归属不匹配',recipient_missing:'接收人已移除'};
            return (labels[row.syncState] || '待同步') + (reasons[row.syncError] ? '：'+reasons[row.syncError] : '');
        },
        openCreateDialog() { this.resetForm(); this.loadOptions(); this.dialogVisible=true; },
        editHabit(row) {
            this.resetForm(); this.editingId=row.id; this.loadOptions();
            this.form={description:row.description,timeValue:this.formatTime(row.hour,row.minute),hour:row.hour,minute:row.minute,advanceMinutes:row.advanceMinutes,deviceId:row.deviceId || '',recipientPersonId:row.recipientPersonId || ''};
            this.dialogVisible=true;
        },''')
s=s.replace('        resetForm() {\n            this.form', '        resetForm() {\n            this.editingId=null;\n            this.form')
s=s.replace('                    deviceId: this.form.deviceId.trim() || null,','                    deviceId: this.form.deviceId.trim(),\n                    recipientPersonId: this.form.recipientPersonId,')
s=s.replace('                Api.habit.createHabit(payload, (res) => {','                const submit = this.editingId ? (data, cb) => Api.habit.updateHabit(this.editingId, data, cb) : Api.habit.createHabit;\n                submit(payload, (res) => {')
p.write_text(s,encoding='utf-8')
p=Path(__file__).parent/'candidate/main/manager-api/src/main/java/xiaozhi/modules/habit/service/HabitSyncService.java';s=p.read_text(encoding='utf-8');s=s.replace('if(!Objects.equals(old.get("device_id"),dto.getDeviceId()))','if(old.get("device_id")!=null && !String.valueOf(old.get("device_id")).isBlank() && !Objects.equals(old.get("device_id"),dto.getDeviceId()))');p.write_text(s,encoding='utf-8')
