<template>
    <div class="welcome">
        <HeaderBar />

        <div class="operation-bar">
            <h2 class="page-title">{{ $t('memoryExtract.pageTitle') }}</h2>
        </div>

        <div class="main-wrapper">
            <div class="content-panel">
                <div class="content-area">
                    <el-card class="params-card" shadow="never">
                        <el-form ref="configForm" :model="form" label-width="160px" v-loading="loading"
                            class="config-form">

                            <el-form-item :label="$t('memoryExtract.enabled')">
                                <el-switch v-model="form.enabled" active-color="#4f6ef6" />
                                <span class="form-tip">{{ $t('memoryExtract.enabledTip') }}</span>
                            </el-form-item>

                            <el-form-item :label="$t('memoryExtract.baseUrl')" prop="base_url">
                                <el-input v-model="form.base_url"
                                    :placeholder="$t('memoryExtract.baseUrlPlaceholder')" clearable
                                    :disabled="!form.enabled" />
                            </el-form-item>

                            <el-form-item :label="$t('memoryExtract.apiKey')" prop="api_key">
                                <el-input v-model="form.api_key" :type="showApiKey ? 'text' : 'password'"
                                    :placeholder="$t('memoryExtract.apiKeyPlaceholder')" clearable
                                    :disabled="!form.enabled">
                                    <el-button slot="append" @click="showApiKey = !showApiKey">
                                        {{ showApiKey ? $t('memoryExtract.hide') : $t('memoryExtract.show') }}
                                    </el-button>
                                </el-input>
                            </el-form-item>

                            <el-form-item :label="$t('memoryExtract.model')" prop="model">
                                <el-input v-model="form.model" :placeholder="$t('memoryExtract.modelPlaceholder')"
                                    clearable :disabled="!form.enabled" />
                            </el-form-item>

                            <el-form-item>
                                <el-button type="primary" class="btn-save" @click="handleSave" :loading="saving">
                                    {{ $t('memoryExtract.save') }}
                                </el-button>
                            </el-form-item>
                        </el-form>
                    </el-card>
                </div>
            </div>
        </div>

        <VersionFooter />
    </div>
</template>

<script>
import Api from "@/apis/api";
import HeaderBar from "@/components/HeaderBar.vue";
import VersionFooter from "@/components/VersionFooter.vue";

// param_code -> form field 映射
const PARAM_MAP = {
    "memory_extract.enabled": "enabled",
    "memory_extract.base_url": "base_url",
    "memory_extract.api_key": "api_key",
    "memory_extract.model": "model",
};

export default {
    name: "MemoryExtractConfig",
    components: { HeaderBar, VersionFooter },
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
                    if (res && res.data && res.data.list) {
                        res.data.list.forEach((item) => {
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
.welcome {
    min-height: 100vh;
    background: linear-gradient(135deg, #e8ecf8 0%, #f0f4ff 50%, #e8ecf8 100%);
}

.operation-bar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 20px 40px 0;
}

.page-title {
    font-size: 20px;
    font-weight: 600;
    color: #333;
}

.main-wrapper {
    padding: 20px 40px;
}

.content-panel {
    background: transparent;
}

.params-card {
    border-radius: 12px;
    border: none;
}

.params-card >>> .el-card__body {
    padding: 30px 40px;
}

.config-form {
    max-width: 700px;
}

.config-form >>> .el-form-item__label {
    font-weight: 500;
    color: #333;
}

.form-tip {
    margin-left: 12px;
    font-size: 12px;
    color: #999;
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
