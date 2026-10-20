<template>
    <div class="xn-page">
        <page-header :title="$t('habitAnalyze.pageTitle')" :description="$t('xn.knowledge.habitAnalyzeDesc')" />

        <div class="xn-panel cfg-panel">
            <div class="xn-panel__head">
                <h2 class="xn-panel__title">{{ $t('xn.knowledge.cfgModelTitle') }}</h2>
            </div>
            <div class="xn-panel__body">
                <el-form ref="configForm" :model="form" label-width="140px" v-loading="loading" class="cfg-form" @submit.native.prevent>
                    <el-form-item :label="$t('habitAnalyze.enabled')">
                        <el-switch v-model="form.enabled" />
                        <p class="cfg-tip">{{ $t('habitAnalyze.enabledTip') }}</p>
                    </el-form-item>

                    <el-form-item :label="$t('habitAnalyze.baseUrl')" prop="base_url">
                        <el-input v-model="form.base_url" :placeholder="$t('habitAnalyze.baseUrlPlaceholder')" clearable />
                    </el-form-item>

                    <el-form-item :label="$t('habitAnalyze.apiKey')" prop="api_key">
                        <el-input v-model="form.api_key" :type="showApiKey ? 'text' : 'password'" autocomplete="new-password"
                            :placeholder="$t('habitAnalyze.apiKeyPlaceholder')" clearable>
                            <el-button slot="append" @click="showApiKey = !showApiKey">
                                {{ showApiKey ? $t('habitAnalyze.hide') : $t('habitAnalyze.show') }}
                            </el-button>
                        </el-input>
                        <p class="cfg-tip">{{ $t('xn.knowledge.cfgKeyTip') }}</p>
                    </el-form-item>

                    <el-form-item :label="$t('habitAnalyze.model')" prop="model">
                        <el-input v-model="form.model" :placeholder="$t('habitAnalyze.modelPlaceholder')" clearable />
                    </el-form-item>

                    <el-form-item class="cfg-actions">
                        <el-button type="primary" @click="handleSave" :loading="saving">{{ $t('habitAnalyze.save') }}</el-button>
                        <el-button :disabled="loading || saving" @click="loadConfig">{{ $t('xn.knowledge.cfgRevert') }}</el-button>
                    </el-form-item>
                </el-form>
            </div>
        </div>
    </div>
</template>

<script>
import Api from "@/apis/api";

const PARAM_MAP = {
    "habit_analyze.enabled": "enabled",
    "habit_analyze.base_url": "base_url",
    "habit_analyze.api_key": "api_key",
    "habit_analyze.model": "model",
};

export default {
    name: "HabitAnalyzeConfig",
    data() {
        return {
            loading: false,
            saving: false,
            showApiKey: false,
            paramIds: {},   // paramCode -> id 映射，保存时带上 id
            form: {
                enabled: false,
                base_url: "https://api.deepseek.com/v1",
                api_key: "",
                model: "deepseek-chat",
            },
        };
    },
    mounted() {
        this.loadConfig();
    },
    methods: {
        loadConfig() {
            this.loading = true;
            Api.admin.getParamsList({ page: 1, limit: 100, paramCode: "habit_analyze" }, (res) => {
                this.loading = false;
                // admin.js 传入的是完整响应对象，body 在 res.data
                const body = res && res.data ? res.data : res;
                if (body && body.code === 0 && body.data) {
                    const list = body.data.list || [];
                    list.forEach((item) => {
                        const field = PARAM_MAP[item.paramCode];
                        // 记录 id，保存时带上
                        this.paramIds[item.paramCode] = item.id;
                        if (field !== undefined) {
                            if (field === "enabled") {
                                this.form.enabled = item.paramValue === "true";
                            } else {
                                this.form[field] = item.paramValue || "";
                            }
                        }
                    });
                }
            });
        },

        handleSave() {
            this.saving = true;
            const updates = [
                { id: this.paramIds["habit_analyze.enabled"],  paramCode: "habit_analyze.enabled",  paramValue: String(this.form.enabled),             valueType: "string" },
                { id: this.paramIds["habit_analyze.base_url"], paramCode: "habit_analyze.base_url", paramValue: this.form.base_url || "https://api.deepseek.com/v1", valueType: "string" },
                { id: this.paramIds["habit_analyze.model"],    paramCode: "habit_analyze.model",    paramValue: this.form.model    || "deepseek-chat",  valueType: "string" },
            ];
            // api_key 为空时跳过更新（后端不允许空值）
            if (this.form.api_key && this.form.api_key.trim()) {
                updates.push({ id: this.paramIds["habit_analyze.api_key"], paramCode: "habit_analyze.api_key", paramValue: this.form.api_key.trim(), valueType: "string" });
            }

            let completed = 0;
            let allOk = true;
            const total = updates.length;

            for (const item of updates) {
                Api.admin.updateParam(item, () => {
                    completed++;
                    if (completed === total) {
                        this.saving = false;
                        if (allOk) {
                            this.$message.success(this.$t("habitAnalyze.saveSuccess"));
                        } else {
                            this.$message.error(this.$t("habitAnalyze.saveFail"));
                        }
                    }
                }, () => {
                    allOk = false;
                    completed++;
                    if (completed === total) {
                        this.saving = false;
                        this.$message.error(this.$t("habitAnalyze.saveFail"));
                    }
                });
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
