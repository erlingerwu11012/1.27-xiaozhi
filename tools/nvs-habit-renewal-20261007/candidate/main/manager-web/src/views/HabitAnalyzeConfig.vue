<template>
    <div class="welcome">
        <HeaderBar />

        <div class="operation-bar">
            <h2 class="page-title">{{ $t('habitAnalyze.pageTitle') }}</h2>
        </div>

        <div class="main-wrapper">
            <div class="content-panel">
                <div class="content-area">
                    <el-card class="params-card" shadow="never">
                        <el-form ref="configForm" :model="form" label-width="160px" v-loading="loading"
                            class="config-form">

                            <el-form-item :label="$t('habitAnalyze.enabled')">
                                <el-switch v-model="form.enabled" active-color="#4f6ef6" />
                                <span class="form-tip">{{ $t('habitAnalyze.enabledTip') }}</span>
                            </el-form-item>

                            <el-form-item :label="$t('habitAnalyze.baseUrl')">
                                <el-input v-model="form.base_url" :placeholder="$t('habitAnalyze.baseUrlPlaceholder')"
                                    class="config-input" />
                            </el-form-item>

                            <el-form-item :label="$t('habitAnalyze.apiKey')">
                                <el-input v-model="form.api_key" :type="showApiKey ? 'text' : 'password'"
                                    :placeholder="$t('habitAnalyze.apiKeyPlaceholder')" class="config-input">
                                    <template slot="append">
                                        <el-button @click="showApiKey = !showApiKey">
                                            {{ showApiKey ? $t('habitAnalyze.hide') : $t('habitAnalyze.show') }}
                                        </el-button>
                                    </template>
                                </el-input>
                            </el-form-item>

                            <el-form-item :label="$t('habitAnalyze.model')">
                                <el-input v-model="form.model" :placeholder="$t('habitAnalyze.modelPlaceholder')"
                                    class="config-input" />
                            </el-form-item>

                            <el-form-item>
                                <el-button type="primary" class="btn-save" @click="handleSave" :loading="saving">
                                    {{ $t('habitAnalyze.save') }}
                                </el-button>
                            </el-form-item>

                        </el-form>
                    </el-card>
                </div>
            </div>
        </div>
    </div>
</template>

<script>
import HeaderBar from "@/components/HeaderBar.vue";
import Api from "@/apis/api";

const PARAM_MAP = {
    "habit_analyze.enabled": "enabled",
    "habit_analyze.base_url": "base_url",
    "habit_analyze.api_key": "api_key",
    "habit_analyze.model": "model",
};

export default {
    name: "HabitAnalyzeConfig",
    components: { HeaderBar },
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
.welcome {
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

.params-card {
    border: none;
}

.config-form {
    max-width: 640px;
}

.config-input {
    width: 100%;
}

.form-tip {
    margin-left: 12px;
    color: #909399;
    font-size: 13px;
}

.btn-save {
    background: #4f6ef6;
    border-color: #4f6ef6;
    border-radius: 8px;
    padding: 10px 40px;
}

.btn-save:hover {
    background: #3a5bd9;
    border-color: #3a5bd9;
}
</style>
