<template>
    <div class="xn-page">
        <page-header :title="$t('memoryExtract.pageTitle')" :description="$t('xn.knowledge.memoryExtractDesc')" />

        <div class="xn-panel cfg-panel">
            <div class="xn-panel__head">
                <h2 class="xn-panel__title">{{ $t('xn.knowledge.cfgModelTitle') }}</h2>
            </div>
            <div class="xn-panel__body">
                <el-form ref="configForm" :model="form" label-width="140px" v-loading="loading" class="cfg-form" @submit.native.prevent>
                    <el-form-item :label="$t('memoryExtract.enabled')">
                        <el-switch v-model="form.enabled" />
                        <p class="cfg-tip">{{ $t('memoryExtract.enabledTip') }}</p>
                    </el-form-item>

                    <el-form-item :label="$t('memoryExtract.baseUrl')" prop="base_url">
                        <el-input v-model="form.base_url" :placeholder="$t('memoryExtract.baseUrlPlaceholder')" clearable :disabled="!form.enabled" />
                    </el-form-item>

                    <el-form-item :label="$t('memoryExtract.apiKey')" prop="api_key">
                        <el-input v-model="form.api_key" :type="showApiKey ? 'text' : 'password'" autocomplete="new-password"
                            :placeholder="$t('memoryExtract.apiKeyPlaceholder')" clearable :disabled="!form.enabled">
                            <el-button slot="append" @click="showApiKey = !showApiKey">
                                {{ showApiKey ? $t('memoryExtract.hide') : $t('memoryExtract.show') }}
                            </el-button>
                        </el-input>
                        <p class="cfg-tip">{{ $t('xn.knowledge.cfgKeyTip') }}</p>
                    </el-form-item>

                    <el-form-item :label="$t('memoryExtract.model')" prop="model">
                        <el-input v-model="form.model" :placeholder="$t('memoryExtract.modelPlaceholder')" clearable :disabled="!form.enabled" />
                    </el-form-item>

                    <el-form-item class="cfg-actions">
                        <el-button type="primary" @click="handleSave" :loading="saving">{{ $t('memoryExtract.save') }}</el-button>
                        <el-button :disabled="loading || saving" @click="loadConfig">{{ $t('xn.knowledge.cfgRevert') }}</el-button>
                    </el-form-item>
                </el-form>
            </div>
        </div>
    </div>
</template>

<script>
import Api from "@/apis/api";

// param_code -> form field 映射
const PARAM_MAP = {
    "memory_extract.enabled": "enabled",
    "memory_extract.base_url": "base_url",
    "memory_extract.api_key": "api_key",
    "memory_extract.model": "model",
};

export default {
    name: "MemoryExtractConfig",
    data() {
        return {
            loading: false,
            saving: false,
            showApiKey: false,
            form: {
                enabled: false,
                base_url: "https://api.deepseek.com/v1",
                api_key: "",
                model: "deepseek-chat",
            },
            // 存储从后端拿到的原始参数对象（含 id），更新时需要
            paramRecords: {},
        };
    },
    mounted() {
        this.loadConfig();
    },
    methods: {
        loadConfig() {
            this.loading = true;
            // 用 paramCode 前缀搜索，一次拿到所有 memory_extract.* 参数
            Api.admin.getParamsList(
                { page: 1, limit: 20, paramCode: "memory_extract" },
                (res) => {
                    this.loading = false;
                    // admin.js 传入的是完整响应对象，响应体在 res.data（原代码直接读 res.data.list，读不到参数）
                    const body = res && res.data ? res.data : res;
                    const page = body && body.code === 0 ? body.data : (body && body.list ? body : null);
                    if (page && page.list) {
                        page.list.forEach((item) => {
                            const field = PARAM_MAP[item.paramCode];
                            if (field) {
                                this.paramRecords[item.paramCode] = item;
                                if (field === "enabled") {
                                    this.form.enabled = item.paramValue === "true";
                                } else {
                                    this.form[field] = item.paramValue || "";
                                }
                            }
                        });
                    }
                }
            );
        },
        handleSave() {
            this.saving = true;
            const updates = [
                { code: "memory_extract.enabled", value: this.form.enabled ? "true" : "false" },
                { code: "memory_extract.base_url", value: this.form.base_url || "https://api.deepseek.com/v1" },
                { code: "memory_extract.model",    value: this.form.model    || "deepseek-chat" },
            ];
            // api_key 为空时跳过更新（后端不允许空值）
            if (this.form.api_key && this.form.api_key.trim()) {
                updates.push({ code: "memory_extract.api_key", value: this.form.api_key.trim() });
            }

            let completed = 0;
            let hasError = false;

            updates.forEach((item) => {
                const record = this.paramRecords[item.code];
                if (!record) {
                    completed++;
                    if (completed === updates.length) this._onSaveComplete(hasError);
                    return;
                }
                Api.admin.updateParam(
                    { id: record.id, paramCode: item.code, paramValue: item.value, valueType: "string", remark: record.remark },
                    () => {
                        completed++;
                        if (completed === updates.length) this._onSaveComplete(hasError);
                    },
                    () => {
                        hasError = true;
                        completed++;
                        if (completed === updates.length) this._onSaveComplete(hasError);
                    }
                );
            });
        },
        _onSaveComplete(hasError) {
            this.saving = false;
            if (hasError) {
                this.$message.error({ message: this.$t("memoryExtract.saveFail"), showClose: true });
            } else {
                this.$message.success({ message: this.$t("memoryExtract.saveSuccess"), showClose: true });
            }
        },
    },
};
</script>

<style scoped>
.cfg-panel { max-width: 820px; }
.cfg-form { max-width: 640px; }
.cfg-tip { margin: 4px 0 0; font-size: 13px; line-height: 1.6; color: var(--xn-ink-3); }
.cfg-actions { margin-bottom: 0; }
@media (max-width: 640px) {
    .cfg-form ::v-deep .el-form-item__label { float: none; display: block; text-align: left; }
    .cfg-form ::v-deep .el-form-item__content { margin-left: 0 !important; }
}
</style>
