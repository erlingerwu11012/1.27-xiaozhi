<template>
    <div class="habit-management">
        <HeaderBar />

        <div class="operation-bar">
            <h2 class="page-title">{{ $t('habitManagement.pageTitle') }}</h2>
            <el-button type="primary" class="btn-add" @click="openCreateDialog">
                + {{ $t('habitManagement.addHabit') }}
            </el-button>
        </div>

        <div class="main-wrapper">
            <div class="content-panel">
                <div class="content-area">
                    <!-- 习惯列表 -->
                    <el-table
                        :data="habitList"
                        v-loading="loading"
                        style="width: 100%"
                        empty-text="暂无手动习惯，点击右上角「+ 添加习惯」创建"
                    >
                        <el-table-column
                            prop="description"
                            :label="$t('habitManagement.col.description')"
                            min-width="140"
                        />
                        <el-table-column
                            :label="$t('habitManagement.col.triggerTime')"
                            width="120"
                        >
                            <template slot-scope="{ row }">
                                {{ formatTime(row.hour, row.minute) }}
                            </template>
                        </el-table-column>
                        <el-table-column
                            prop="advanceMinutes"
                            :label="$t('habitManagement.col.advanceMinutes')"
                            width="130"
                        >
                            <template slot-scope="{ row }">
                                {{ row.advanceMinutes }} {{ $t('habitManagement.minutesBefore') }}
                            </template>
                        </el-table-column>
                        <el-table-column
                            :label="$t('habitManagement.col.source')"
                            width="100"
                        >
                            <template slot-scope="{ row }">
                                <el-tag
                                    :type="row.source === 'manual' ? 'primary' : 'info'"
                                    size="small"
                                >
                                    {{ row.source === 'manual'
                                        ? $t('habitManagement.sourceManual')
                                        : $t('habitManagement.sourceAuto') }}
                                </el-tag>
                            </template>
                        </el-table-column>
                        <el-table-column
                            :label="$t('habitManagement.col.synced')"
                            width="100"
                        >
                            <template slot-scope="{ row }">
                                <el-tag
                                    :type="row.syncState === 'synced' ? 'success' : 'warning'"
                                    size="small"
                                >
                                    {{ statusText(row) }}
                                </el-tag>
                            </template>
                        </el-table-column>
                        <el-table-column
                            prop="createdAt"
                            :label="$t('habitManagement.col.createdAt')"
                            width="160"
                        />
                        <el-table-column
                            :label="$t('habitManagement.col.actions')"
                            width="160"
                            fixed="right"
                        >
                            <template slot-scope="{ row }">
                                <el-button size="mini" @click="editHabit(row)" :disabled="row.enabled !== 1">编辑</el-button>
                                <el-button
                                    :disabled="row.enabled !== 1"
                                    type="danger"
                                    size="mini"
                                    @click="handleDelete(row)"
                                >
                                    {{ $t('habitManagement.delete') }}
                                </el-button>
                            </template>
                        </el-table-column>
                    </el-table>
                </div>
            </div>
        </div>

        <!-- 创建习惯对话框 -->
        <el-dialog
            :title="$t('habitManagement.createTitle')"
            :visible.sync="dialogVisible"
            width="480px"
            @close="resetForm"
        >
            <el-form
                ref="createForm"
                :model="form"
                :rules="rules"
                label-width="120px"
            >
                <el-form-item
                    :label="$t('habitManagement.form.description')"
                    prop="description"
                >
                    <el-input
                        v-model="form.description"
                        :placeholder="$t('habitManagement.form.descriptionPlaceholder')"
                        maxlength="32"
                        show-word-limit
                    />
                </el-form-item>

                <el-form-item
                    :label="$t('habitManagement.form.triggerTime')"
                    prop="hour"
                >
                    <el-time-picker
                        v-model="form.timeValue"
                        format="HH:mm"
                        value-format="HH:mm"
                        :placeholder="$t('habitManagement.form.timePlaceholder')"
                        style="width: 100%"
                        @change="onTimeChange"
                    />
                </el-form-item>

                <el-form-item
                    :label="$t('habitManagement.form.advanceMinutes')"
                    prop="advanceMinutes"
                >
                    <el-input-number
                        v-model="form.advanceMinutes"
                        :min="0"
                        :max="30"
                        :step="1"
                        style="width: 100%"
                    />
                    <span class="form-tip">{{ $t('habitManagement.form.advanceTip') }}</span>
                </el-form-item>

                <el-form-item label="提醒设备" prop="deviceId">
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
                <p class="form-tip">设备保存成功后才显示“已同步”。旧记录请先编辑绑定，旧固件需要升级。删除后需设备在线确认停止提醒。</p>
            </el-form>

            <span slot="footer" class="dialog-footer">
                <el-button @click="dialogVisible = false">
                    {{ $t('habitManagement.cancel') }}
                </el-button>
                <el-button
                    type="primary"
                    :loading="saving"
                    @click="handleCreate"
                >
                    {{ $t('habitManagement.confirm') }}
                </el-button>
            </span>
        </el-dialog>
    </div>
</template>

<script>
import HeaderBar from "@/components/HeaderBar.vue";
import Api from "@/apis/api";

export default {
    name: "HabitManagement",
    components: { HeaderBar },
    data() {
        return {
            loading: false,
            saving: false,
            dialogVisible: false,
            habitList: [],
            devices: [], people: [], editingId: null, refreshTimer: null,
            form: {
                description: "",
                timeValue: null,
                hour: 8,
                minute: 0,
                advanceMinutes: 2,
                deviceId: "",
                recipientPersonId: "",
            },
        };
    },
    computed: {
        rules() {
            return {
                deviceId: [{required:true,message:"请选择提醒设备",trigger:"change"}],
                recipientPersonId: [{required:true,message:"请选择接收人",trigger:"change"}],
                description: [
                    { required: true, message: this.$t("habitManagement.form.descriptionRequired"), trigger: "blur" },
                    { min: 1, max: 32, message: this.$t("habitManagement.form.descriptionLength"), trigger: "blur" },
                ],
                hour: [
                    { required: true, message: this.$t("habitManagement.form.timeRequired"), trigger: "change" },
                ],
                advanceMinutes: [
                    { required: true, message: this.$t("habitManagement.form.advanceRequired"), trigger: "blur" },
                ],
            };
        },
    },
    mounted() {
        this.loadHabits();
        this.refreshTimer = setInterval(() => this.loadHabits(), 15000);
    },
    beforeDestroy() { clearInterval(this.refreshTimer); },
    methods: {
        loadHabits() {
            this.loading = true;
            Api.habit.listHabits({ enabledOnly: false }, (res) => {
                this.loading = false;
                if (res && res.code === 0 && res.data) {
                    this.habitList = res.data;
                } else {
                    this.$message.error(this.$t("habitManagement.loadFail"));
                }
            });
        },

        loadOptions() {
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
        },

        resetForm() {
            this.editingId=null;
            this.form = {
                description: "",
                timeValue: null,
                hour: 8,
                minute: 0,
                advanceMinutes: 2,
                deviceId: "",
                recipientPersonId: "",
            };
            if (this.$refs.createForm) {
                this.$refs.createForm.clearValidate();
            }
        },

        onTimeChange(val) {
            if (val) {
                const parts = val.split(":");
                this.form.hour = parseInt(parts[0], 10);
                this.form.minute = parseInt(parts[1], 10);
            }
        },

        handleCreate() {
            this.$refs.createForm.validate((valid) => {
                if (!valid) return;
                if (!this.form.timeValue) {
                    this.$message.warning(this.$t("habitManagement.form.timeRequired"));
                    return;
                }
                this.saving = true;
                const payload = {
                    description: this.form.description.trim(),
                    hour: this.form.hour,
                    minute: this.form.minute,
                    advanceMinutes: this.form.advanceMinutes,
                    deviceId: this.form.deviceId.trim(),
                    recipientPersonId: this.form.recipientPersonId,
                };
                const submit = this.editingId ? (data, cb) => Api.habit.updateHabit(this.editingId, data, cb) : Api.habit.createHabit;
                submit(payload, (res) => {
                    this.saving = false;
                    if (res && res.code === 0) {
                        this.$message.success(this.$t("habitManagement.createSuccess"));
                        this.dialogVisible = false;
                        this.loadHabits();
                    } else {
                        this.$message.error(res.msg || this.$t("habitManagement.createFail"));
                    }
                });
            });
        },

        handleDelete(row) {
            this.$confirm(
                this.$t("habitManagement.deleteConfirm", { name: row.description }),
                this.$t("habitManagement.deleteTitle"),
                {
                    confirmButtonText: this.$t("habitManagement.confirmDelete"),
                    cancelButtonText: this.$t("habitManagement.cancel"),
                    type: "warning",
                }
            ).then(() => {
                Api.habit.deleteHabit(row.id, (res) => {
                    if (res && res.code === 0) {
                        this.$message.success(this.$t("habitManagement.deleteSuccess"));
                        this.loadHabits();
                    } else {
                        this.$message.error(res.msg || this.$t("habitManagement.deleteFail"));
                    }
                });
            }).catch(() => {});
        },

        formatTime(hour, minute) {
            return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
        },
    },
};
</script>

<style scoped>
.habit-management {
    min-height: 100vh;
    background: #f5f7fb;
}

.operation-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 16px 32px 0;
}

.page-title {
    font-size: 20px;
    font-weight: 600;
    color: #1a1a2e;
    margin: 0;
}

.btn-add {
    background: #4f6ef6;
    border-color: #4f6ef6;
    border-radius: 8px;
}

.btn-add:hover {
    background: #3a5bd9;
    border-color: #3a5bd9;
}

.main-wrapper {
    padding: 24px 32px;
}

.content-panel {
    background: #fff;
    border-radius: 12px;
    box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
    overflow: hidden;
}

.content-area {
    padding: 24px;
}

.form-tip {
    margin-left: 8px;
    color: #909399;
    font-size: 12px;
}
</style>
