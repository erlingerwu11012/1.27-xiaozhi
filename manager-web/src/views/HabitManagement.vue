<template>
    <div class="xn-page">
        <page-header :title="$t('habitManagement.pageTitle')" :description="$t('xn.knowledge.habitDesc')">
            <el-button type="primary" @click="openCreateDialog"><xn-icon name="plus" /> {{ $t('habitManagement.addHabit') }}</el-button>
        </page-header>

        <div class="xn-panel xn-panel--flush hm-panel">
            <xn-empty v-if="loadFailed && !loading" error @retry="loadHabits" />
            <template v-else>
                <el-table :data="habitList" v-loading="loading && !loaded" row-key="id" :row-class-name="rowClass">
                    <el-table-column prop="description" :label="$t('habitManagement.col.description')" min-width="160">
                        <template slot-scope="{ row }"><span class="hm-name">{{ row.description }}</span></template>
                    </el-table-column>
                    <el-table-column :label="$t('habitManagement.col.triggerTime')" width="100">
                        <template slot-scope="{ row }"><span class="xn-num">{{ formatTime(row.hour, row.minute) }}</span></template>
                    </el-table-column>
                    <el-table-column prop="advanceMinutes" :label="$t('habitManagement.col.advanceMinutes')" width="120">
                        <template slot-scope="{ row }">
                            <span v-if="row.advanceMinutes > 0"><span class="xn-num">{{ row.advanceMinutes }}</span> {{ $t('habitManagement.minutesBefore') }}</span>
                            <span v-else class="xn-muted">{{ $t('xn.knowledge.onTime') }}</span>
                        </template>
                    </el-table-column>
                    <el-table-column :label="$t('habitManagement.col.source')" width="90">
                        <template slot-scope="{ row }">
                            <span class="xn-tag" :class="row.source === 'manual' ? 'xn-tag--lake' : 'xn-tag--muted'">
                                {{ row.source === 'manual' ? $t('habitManagement.sourceManual') : $t('habitManagement.sourceAuto') }}
                            </span>
                        </template>
                    </el-table-column>
                    <el-table-column :label="$t('habitManagement.col.synced')" min-width="170">
                        <template slot-scope="{ row }">
                            <span class="xn-tag hm-sync" :class="statusClass(row)" :title="statusText(row)">{{ statusText(row) }}</span>
                        </template>
                    </el-table-column>
                    <el-table-column prop="createdAt" :label="$t('habitManagement.col.createdAt')" width="160" class-name="hm-nowrap">
                        <template slot-scope="{ row }"><span class="xn-num">{{ (row.createdAt || '').slice(0, 16) }}</span></template>
                    </el-table-column>
                    <el-table-column :label="$t('habitManagement.col.actions')" width="120" align="right">
                        <template slot-scope="{ row }">
                            <el-button type="text" :disabled="row.enabled !== 1" @click="editHabit(row)">{{ $t('xn.knowledge.edit') }}</el-button>
                            <el-button type="text" class="hm-danger" :disabled="row.enabled !== 1" @click="handleDelete(row)">{{ $t('habitManagement.delete') }}</el-button>
                        </template>
                    </el-table-column>
                    <template slot="empty">
                        <xn-empty icon="chat" :title="$t('xn.knowledge.habitEmptyTitle')" :description="$t('xn.knowledge.habitEmptyDesc')">
                            <el-button type="primary" @click="openCreateDialog"><xn-icon name="plus" /> {{ $t('habitManagement.addHabit') }}</el-button>
                        </xn-empty>
                    </template>
                </el-table>
                <div v-if="habitList.length" class="hm-foot">
                    <span class="xn-muted hm-note"><xn-icon name="info" /> {{ $t('xn.knowledge.habitSyncNote') }}</span>
                    <span class="xn-muted hm-count">{{ $t('xn.knowledge.habitCount', { n: habitList.length }) }}</span>
                </div>
            </template>
        </div>

        <!-- 新建 / 编辑习惯 -->
        <el-dialog :title="editingId ? $t('xn.knowledge.habitEditTitle') : $t('habitManagement.createTitle')"
            :visible.sync="dialogVisible" width="520px" append-to-body @close="resetForm">
            <el-form ref="createForm" :model="form" :rules="rules" label-position="top" v-loading="optionsLoading" @submit.native.prevent>
                <el-form-item :label="$t('habitManagement.form.description')" prop="description">
                    <el-input v-model="form.description" :placeholder="$t('habitManagement.form.descriptionPlaceholder')" maxlength="32" show-word-limit />
                </el-form-item>
                <div class="hm-row">
                    <el-form-item :label="$t('habitManagement.form.triggerTime')" prop="hour">
                        <el-time-picker v-model="form.timeValue" format="HH:mm" value-format="HH:mm"
                            :placeholder="$t('habitManagement.form.timePlaceholder')" style="width: 100%" @change="onTimeChange" />
                    </el-form-item>
                    <el-form-item :label="$t('habitManagement.form.advanceMinutes')" prop="advanceMinutes">
                        <el-input-number v-model="form.advanceMinutes" :min="0" :max="30" :step="1" step-strictly style="width: 100%" />
                    </el-form-item>
                </div>
                <p class="hm-tip hm-tip--inline">{{ $t('xn.knowledge.habitAdvanceTip') }}</p>
                <el-form-item :label="$t('xn.knowledge.habitDevice')" prop="deviceId">
                    <el-select v-model="form.deviceId" :placeholder="$t('xn.knowledge.habitDevicePlaceholder')" style="width:100%"
                        :no-data-text="$t('xn.knowledge.habitNoDevice')">
                        <el-option v-for="d in devices" :key="d.deviceId" :value="d.deviceId" :label="deviceLabel(d)" />
                    </el-select>
                </el-form-item>
                <el-form-item :label="$t('xn.knowledge.habitRecipient')" prop="recipientPersonId">
                    <el-select v-model="form.recipientPersonId" :placeholder="$t('xn.knowledge.habitRecipientPlaceholder')" style="width:100%">
                        <el-option :label="$t('xn.knowledge.habitRecipientAll')" value="all" />
                        <el-option v-for="p in people" :key="p.user_id" :label="p.display_name" :value="p.user_id" />
                    </el-select>
                </el-form-item>
                <p class="hm-tip">{{ $t('xn.knowledge.habitFormNote') }}</p>
            </el-form>

            <span slot="footer">
                <el-button @click="dialogVisible = false">{{ $t('habitManagement.cancel') }}</el-button>
                <el-button type="primary" :loading="saving" @click="handleCreate">
                    {{ editingId ? $t('xn.knowledge.saveChanges') : $t('habitManagement.confirm') }}
                </el-button>
            </span>
        </el-dialog>
    </div>
</template>

<script>
import Api from "@/apis/api";

export default {
    name: "HabitManagement",
    data() {
        return {
            loading: false,
            loaded: false,
            loadFailed: false,
            optionsLoading: false,
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
                deviceId: [{required:true,message:this.$t("xn.knowledge.habitDeviceRequired"),trigger:"change"}],
                recipientPersonId: [{required:true,message:this.$t("xn.knowledge.habitRecipientRequired"),trigger:"change"}],
                description: [
                    { required: true, message: this.$t("habitManagement.form.descriptionRequired"), trigger: "blur" },
                    { min: 1, max: 32, message: this.$t("xn.knowledge.habitNameLength"), trigger: "blur" },
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
                this.loaded = true;
                if (res && res.code === 0 && res.data) {
                    this.habitList = res.data;
                    this.loadFailed = false;
                } else {
                    // 定时刷新失败时保留已有列表，只有首次加载失败才显示失败状态
                    if (!this.habitList.length) this.loadFailed = true;
                    this.$message.error(this.$t("habitManagement.loadFail"));
                }
            });
        },

        loadOptions() {
            this.optionsLoading = true;
            Api.habit.bindingOptions(res => {
                this.optionsLoading = false;
                if(res && res.code===0) { this.devices=res.data.devices; this.people=res.data.people; }
                else { this.$message.error(this.$t("xn.knowledge.habitOptionsFailed")); }
            });
        },
        statusText(row) {
            const state = row.syncState === 'synced' && row.enabled !== 1 ? 'stopped' : row.syncState;
            const known = ['needs_binding', 'pending', 'upgrade_required', 'failed', 'synced', 'stopped'];
            const label = this.$t('xn.knowledge.sync.' + (known.includes(state) ? state : 'pending'));
            const reasonKey = 'xn.knowledge.syncError.' + row.syncError;
            return label + (row.syncError && this.$te(reasonKey) ? this.$t('xn.knowledge.syncSep') + this.$t(reasonKey) : '');
        },
        statusClass(row) {
            if (row.enabled !== 1) return row.syncState === 'synced' ? 'xn-tag--muted' : 'xn-tag--warning';
            return { synced: 'xn-tag--success', failed: 'xn-tag--danger', upgrade_required: 'xn-tag--warning', needs_binding: 'xn-tag--warning' }[row.syncState] || 'xn-tag--lake';
        },
        deviceLabel(d) {
            return (d.deviceName || d.alias || this.$t('xn.knowledge.habitDeviceFallback')) + ' · ' + d.deviceId;
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
                        this.$message.success(this.$t(this.editingId ? "xn.knowledge.habitUpdated" : "habitManagement.createSuccess"));
                        this.dialogVisible = false;
                        this.loadHabits();
                    } else {
                        this.$message.error((res && res.msg) || this.$t("habitManagement.createFail"));
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
                        this.$message.error((res && res.msg) || this.$t("habitManagement.deleteFail"));
                    }
                });
            }).catch(() => {});
        },

        rowClass({ row }) {
            return row.enabled !== 1 ? 'hm-row--off' : '';
        },
        formatTime(hour, minute) {
            return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
        },
    },
};
</script>

<style scoped>
.hm-panel { overflow: hidden; }
.hm-panel ::v-deep .hm-nowrap .cell { white-space: nowrap; }
.hm-name { font-weight: 500; }
.hm-panel ::v-deep .hm-row--off .hm-name { color: var(--xn-ink-3); text-decoration: line-through; text-decoration-color: var(--xn-ink-4); }
.hm-sync { max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
.hm-danger { color: var(--xn-danger); }
.hm-danger:hover, .hm-danger:focus { color: #8D3523; }
.hm-danger.is-disabled, .hm-danger.is-disabled:hover { color: var(--xn-ink-4); }
.hm-foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; padding: 12px 16px 14px; border-top: 1px solid var(--xn-line-2); }
.hm-note { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; }
.hm-count { font-size: 13px; }
.hm-row { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.hm-tip { margin: 0; font-size: 13px; line-height: 1.7; color: var(--xn-ink-3); }
.hm-tip--inline { margin: -10px 0 16px; }
@media (max-width: 560px) { .hm-row { grid-template-columns: 1fr; } }
</style>
