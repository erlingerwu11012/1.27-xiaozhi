<template>
  <el-dialog :visible.sync="dialogVisible" :close-on-click-modal="false" append-to-body width="760px"
    :title="modelData.duplicateMode ? $t('modelConfigDialog.duplicateModel') : $t('modelConfigDialog.editModel')"
    custom-class="xn-model-dialog">
    <div class="md-section-head">
      <h3 class="md-section-title">{{ $t("modelConfigDialog.modelInfo") }}</h3>
      <label class="md-switch">
        <span>{{ $t("modelConfigDialog.enable") }}</span>
        <el-switch v-model="form.isEnabled" :active-value="1" :inactive-value="0"></el-switch>
      </label>
    </div>
    <p v-if="modelData.duplicateMode" class="md-note">{{ $t('xn.admin.model.duplicateHint') }}</p>

    <el-form :model="form" ref="form" label-position="top" class="md-form" @submit.native.prevent>
      <div class="md-grid">
        <el-form-item :label="$t('modelConfigDialog.modelName')" prop="name">
          <el-input v-model="form.modelName" :placeholder="$t('modelConfigDialog.enterModelName')"></el-input>
        </el-form-item>
        <el-form-item :label="$t('modelConfigDialog.modelCode')" prop="code">
          <el-input v-model="form.modelCode" :placeholder="$t('modelConfigDialog.enterModelCode')"></el-input>
        </el-form-item>
        <el-form-item :label="$t('modelConfigDialog.supplier')" prop="supplier">
          <el-select v-model="form.configJson.type" :placeholder="$t('modelConfigDialog.selectSupplier')" style="width: 100%"
            @focus="loadProviders" filterable>
            <el-option v-for="item in providers" :key="item.value" :label="item.label" :value="item.value">
              <span>{{ item.label }}</span><span class="md-opt-code">{{ item.value }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item :label="$t('modelConfigDialog.sortOrder')" prop="sort">
          <el-input v-model.number="form.sort" type="number" :placeholder="$t('modelConfigDialog.enterSortOrder')"></el-input>
        </el-form-item>
      </div>
      <el-form-item :label="$t('modelConfigDialog.docLink')" prop="docUrl">
        <el-input v-model="form.docLink" :placeholder="$t('modelConfigDialog.enterDocLink')"></el-input>
      </el-form-item>
      <el-form-item :label="$t('modelConfigDialog.remark')" prop="remark">
        <el-input v-model="form.remark" type="textarea" :placeholder="$t('modelConfigDialog.enterRemark')"
          :autosize="{ minRows: 2, maxRows: 5 }"></el-input>
      </el-form-item>
    </el-form>

    <div class="md-section-head md-section-head--call">
      <h3 class="md-section-title">{{ $t("modelConfigDialog.callInfo") }}</h3>
    </div>
    <p v-if="!dynamicCallInfoFields.length" class="md-empty">{{ $t('xn.admin.model.noCallFields') }}</p>
    <el-form v-else :model="form.configJson" ref="callInfoForm" label-position="top" class="md-form" @submit.native.prevent>
      <div class="md-grid">
        <el-form-item v-for="field in dynamicCallInfoFields" :key="field.prop" :label="field.label" :prop="field.prop"
          :class="{ 'md-span': field.type === 'json-textarea' }">
          <template v-if="field.type === 'json-textarea'">
            <el-input v-model="fieldJsonMap[field.prop]" type="textarea" :rows="3" class="md-code"
              :placeholder="$t('modelConfigDialog.enterJsonExample')"
              @change="(val) => handleJsonChange(field.prop, val)" @focus="
                isSensitiveField(field.prop)
                  ? handleJsonInputFocus(field.prop, fieldJsonMap[field.prop])
                  : undefined
                " @blur="
                isSensitiveField(field.prop)
                  ? handleJsonInputBlur(field.prop)
                  : undefined
                "></el-input>
          </template>
          <el-input v-else v-model="form.configJson[field.prop]" :placeholder="field.placeholder" :type="field.type"
            :show-password="field.type === 'password'" @focus="
              isSensitiveField(field.prop)
                ? handleInputFocus(field.prop, form.configJson[field.prop])
                : undefined
              " @blur="
              isSensitiveField(field.prop) ? handleInputBlur(field.prop) : undefined
              "></el-input>
          <p v-if="isSensitiveField(field.prop)" class="md-field-hint">{{ $t('xn.admin.model.secretHint') }}</p>
        </el-form-item>
      </div>
    </el-form>
    <p v-if="isMock && dynamicCallInfoFields.some((f) => isSensitiveField(f.prop))" class="md-demo"><demo-tag /> {{ $t('xn.admin.secretNotSaved') }}</p>

    <span slot="footer">
      <el-button @click="dialogVisible = false">{{ $t('xn.common.cancel') }}</el-button>
      <el-button type="primary" @click="handleSave" :loading="saving" :disabled="saving">{{ $t("modelConfigDialog.save") }}</el-button>
    </span>
  </el-dialog>
</template>

<script>
import Api from "@/apis/api";
import { IS_MOCK } from "@/utils/media";

export default {
  name: "ModelEditDialog",
  props: {
    visible: { type: Boolean, default: false },
    modelData: {
      type: Object,
      default: () => ({}),
      validator: (value) => typeof value === "object" && !Array.isArray(value),
    },
    modelType: { type: String, required: true },
  },
  data() {
    return {
      dialogVisible: this.visible,
      isMock: IS_MOCK,
      providers: [],
      providersLoaded: false,
      saving: false,
      allProvidersData: null,
      pendingProviderType: null,
      pendingModelData: null,
      dynamicCallInfoFields: [],
      fieldJsonMap: {}, // 用于存储JSON字段的字符串形式
      sensitive_keys: [
        "api_key",
        "personal_access_token",
        "access_token",
        "token",
        "secret",
        "access_key_secret",
        "secret_key",
      ],
      originalValues: {}, // 存储原始值，用于失焦时恢复
      form: {
        id: "",
        modelType: "",
        modelCode: "",
        modelName: "",
        isDefault: false,
        isEnabled: false,
        docLink: "",
        remark: "",
        sort: 0,
        configJson: {},
      },
    };
  },
  computed: {
    chunkedCallInfoFields() {
      const chunkSize = 2;
      const result = [];
      for (let i = 0; i < this.dynamicCallInfoFields.length; i += chunkSize) {
        result.push(this.dynamicCallInfoFields.slice(i, i + chunkSize));
      }
      return result;
    },
  },
  watch: {
    modelType() {
      this.resetProviders();
      this.loadProviders();
    },
    dialogVisible(val) {
      this.$emit("update:visible", val);
      if (!val) {
        this.resetForm();
      } else if (val && this.modelData.id) {
        this.loadModelData();
      }
    },
    visible(val) {
      this.dialogVisible = val;
      if (val) {
        this.loadProviders();
      }
    },
    "form.configJson.type"(newVal) {
      if (newVal && this.providersLoaded) {
        this.loadProviderFields(newVal);
      }
    },
  },
  methods: {
    resetForm() {
      this.form = {
        id: "",
        modelType: "",
        modelCode: "",
        modelName: "",
        isDefault: false,
        isEnabled: false,
        docLink: "",
        remark: "",
        sort: 0,
        configJson: {},
      };
      this.fieldJsonMap = {};
    },
    resetProviders() {
      this.providers = [];
      this.providersLoaded = false;
    },
    loadModelData() {
      if (this.modelData.id) {
        Api.model.getModelConfig(this.modelData.id, ({ data }) => {
          if (data.code === 0 && data.data) {
            let model = data.data;

            if (this.modelData.duplicateMode) {
              model.modelName =
                this.modelData.modelName + this.$t("modelConfigDialog.copySuffix");
              model.modelCode =
                this.modelData.modelCode + this.$t("modelConfigDialog.copySuffix");

              // 处理敏感字段
              if (model.configJson) {
                Object.keys(model.configJson).forEach((key) => {
                  if (this.isSensitiveField(key) && model.configJson[key]) {
                    const sensitiveName = this.getSensitiveFieldName(key);
                    model.configJson[key] = `你的${sensitiveName}`;
                  }
                });
              }
            }
            this.pendingProviderType = model.configJson.type;
            this.pendingModelData = model;

            if (this.providersLoaded) {
              this.loadProviderFields(model.configJson.type);
            } else {
              this.loadProviders();
            }
          }
        });
      }
    },
    handleSave() {
      this.saving = true; // 开始保存加载

      // 处理所有JSON字段
      Object.keys(this.fieldJsonMap).forEach((key) => {
        const parsed = this.validateJson(this.fieldJsonMap[key]);
        if (parsed !== null) {
          this.form.configJson[key] = parsed;
        }
      });

      const formData = {
        id: this.modelData.id,
        modelCode: this.form.modelCode,
        modelName: this.form.modelName,
        isDefault: this.form.isDefault ? 1 : 0,
        isEnabled: this.form.isEnabled ? 1 : 0,
        docLink: this.form.docLink,
        remark: this.form.remark,
        sort: this.form.sort || 0,
        configJson: { ...this.form.configJson },
      };

      this.$emit("save", {
        provideCode: this.form.configJson.type,
        formData,
        done: () => {
          this.saving = false; // 保存完成后回调
        },
      });

      // 如果父组件不处理done回调，3秒后自动关闭加载状态
      setTimeout(() => {
        this.saving = false;
      }, 3000);
    },
    loadProviders() {
      if (this.providersLoaded) return;

      Api.model.getModelProviders(this.modelType, (data) => {
        this.providers = data.map((item) => ({
          label: item.name,
          value: String(item.providerCode),
        }));
        this.providersLoaded = true;
        this.allProvidersData = data;

        if (this.pendingProviderType) {
          this.loadProviderFields(this.pendingProviderType);
        }
      });
    },
    loadProviderFields(providerCode) {
      if (this.allProvidersData) {
        const provider = this.allProvidersData.find(
          (p) => p.providerCode === providerCode
        );
        if (provider) {
          this.dynamicCallInfoFields = JSON.parse(provider.fields || "[]").map((f) => ({
            label: f.label,
            prop: f.key,
            type:
              f.type === "dict"
                ? "json-textarea"
                : f.type === "password"
                  ? "password"
                  : "text",
            placeholder: `请输入${f.key}`,
          }));

          if (this.pendingModelData && this.pendingProviderType === providerCode) {
            this.processModelData(this.pendingModelData);
            this.pendingModelData = null;
            this.pendingProviderType = null;
          }
        }
      }
    },
    processModelData(model) {
      let configJson = model.configJson || {};
      this.dynamicCallInfoFields.forEach((field) => {
        if (!configJson.hasOwnProperty(field.prop)) {
          configJson[field.prop] = "";
        } else if (field.type === "json-textarea") {
          this.$set(
            this.fieldJsonMap,
            field.prop,
            this.formatJson(configJson[field.prop])
          );
          configJson[field.prop] = this.ensureObject(configJson[field.prop]);
        } else if (typeof configJson[field.prop] !== "string") {
          configJson[field.prop] = String(configJson[field.prop]);
        }
      });

      this.form = {
        id: model.id,
        modelType: model.modelType,
        modelCode: model.modelCode,
        modelName: model.modelName,
        isDefault: model.isDefault,
        isEnabled: model.isEnabled,
        docLink: model.docLink,
        remark: model.remark,
        sort: Number(model.sort) || 0,
        configJson: { ...configJson },
      };
    },
    handleJsonChange(field, value) {
      const parsed = this.validateJson(value);
      if (parsed !== null) {
        this.form.configJson[field] = parsed;
      }
    },
    validateJson(value) {
      try {
        const parsed = JSON.parse(value);
        if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
          return parsed;
        }
        this.$message.error({
          message: '必须输入字典格式（如 {"key":"value"}），保存则使用原数据',
          showClose: true,
        });
        return null;
      } catch (e) {
        this.$message.error({
          message: 'JSON格式错误（如 {"key":"value"}），保存则使用原数据',
          showClose: true,
        });
        return null;
      }
    },
    formatJson(obj) {
      try {
        return JSON.stringify(obj, null, 2);
      } catch {
        return "";
      }
    },
    ensureObject(value) {
      return typeof value === "object" ? value : {};
    },

    // 检测字段是否为敏感字段
    isSensitiveField(fieldName) {
      // 将字段名转换为小写进行比较
      const lowerFieldName = fieldName.toLowerCase();
      // 精确匹配keyMap中定义的7个敏感词
      return this.sensitive_keys.includes(lowerFieldName);
    },

    // 获取敏感字段对应的中文名称
    getSensitiveFieldName(fieldName) {
      const keyMap = {
        api_key: "API密钥",
        personal_access_token: "个人访问令牌",
        access_token: "访问令牌",
        token: "令牌",
        secret: "密钥",
        access_key_secret: "访问密钥",
        secret_key: "密钥",
      };

      for (const [key, value] of Object.entries(keyMap)) {
        if (fieldName.toLowerCase().includes(key)) {
          return value;
        }
      }
      return "敏感信息";
    },

    // 处理input聚焦事件
    handleInputFocus(field, value) {
      // 如果值包含星号，清空显示
      if (value && value.includes("*")) {
        // 存储原始值，用于失焦时恢复
        this.$set(this.originalValues, field, this.form.configJson[field]);
        this.$set(this.form.configJson, field, "");
      }
    },

    // 处理input失焦事件
    handleInputBlur(field) {
      // 检查是否为敏感字段
      if (this.isSensitiveField(field)) {
        // 如果值为空，恢复掩码值
        if (!this.form.configJson[field] || this.form.configJson[field].trim() === "") {
          // 如果有原始值，则恢复原始值；否则设置为掩码提示
          if (this.originalValues[field]) {
            this.$set(this.form.configJson, field, this.originalValues[field]);
          } else {
            const sensitiveName = this.getSensitiveFieldName(field);
            this.$set(this.form.configJson, field, `你的${sensitiveName}`);
          }
          // 清除临时存储的原始值
          this.$delete(this.originalValues, field);
        }
      }
    },

    // 处理JSON字段的聚焦事件
    handleJsonInputFocus(field, value) {
      if (value && value.includes("*")) {
        this.$set(this.fieldJsonMap, field, "");
      }
    },

    // 处理JSON字段的失焦事件
    handleJsonInputBlur(field) {
      // JSON字段不做特殊处理，因为它们通常不包含简单的敏感信息
    },
  },
};
</script>

<style scoped>
.el-form--label-top ::v-deep .el-form-item__label { padding: 0 0 6px; line-height: 1.5; }
.md-section-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 0 0 12px; }
.md-section-head--call { margin-top: 4px; padding-top: 16px; border-top: 1px solid var(--xn-line-2); }
.md-section-title { margin: 0; font-size: 16px; font-weight: 600; color: var(--xn-ink); }
.md-switch { display: inline-flex; align-items: center; gap: 8px; font-size: 14px; color: var(--xn-ink-2); cursor: pointer; }
.md-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.md-span { grid-column: 1 / -1; }
.md-code ::v-deep .el-textarea__inner { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; }
.md-opt-code { float: right; margin-left: 16px; font-size: 12px; color: var(--xn-ink-3); }
.md-note { margin: -4px 0 14px; font-size: 13px; color: var(--xn-ink-3); }
.md-field-hint { margin: 4px 0 0; font-size: 12px; line-height: 1.5; color: var(--xn-ink-3); }
.md-empty { margin: 0 0 16px; padding: 14px 16px; border-radius: var(--xn-r); background: var(--xn-mist-2); font-size: 13px; color: var(--xn-ink-3); }
.md-demo { display: flex; align-items: center; gap: 8px; margin: 0 0 8px; font-size: 13px; color: var(--xn-ink-3); }
@media (max-width: 640px) { .md-grid { grid-template-columns: 1fr; } }
</style>
