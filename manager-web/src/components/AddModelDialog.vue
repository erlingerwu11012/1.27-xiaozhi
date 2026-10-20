<template>
  <el-dialog :visible="dialogVisible" @update:visible="handleVisibleChange" :title="$t('modelConfigDialog.addModel')"
    width="760px" append-to-body :close-on-click-modal="false" custom-class="xn-model-dialog">
    <div class="md-section-head">
      <h3 class="md-section-title">{{ $t('modelConfigDialog.modelInfo') }}</h3>
      <label class="md-switch">
        <span>{{ $t('modelConfigDialog.enable') }}</span>
        <el-switch v-model="formData.isEnabled"></el-switch>
      </label>
    </div>
    <el-form :model="formData" label-position="top" class="md-form" @submit.native.prevent>
      <div class="md-grid">
        <el-form-item :label="$t('modelConfigDialog.modelId')" prop="id">
          <el-input v-model="formData.id" :placeholder="$t('modelConfigDialog.enterModelId')" class="md-code" maxlength="32"></el-input>
        </el-form-item>
        <el-form-item :label="$t('modelConfigDialog.supplier')" prop="supplier" class="is-required">
          <el-select v-model="formData.supplier" :placeholder="$t('modelConfigDialog.selectSupplier')" style="width: 100%;"
            @focus="loadProviders" filterable :no-data-text="$t('xn.admin.model.noProviders')">
            <el-option v-for="item in providers" :key="item.value" :label="item.label" :value="item.value">
              <span>{{ item.label }}</span><span class="md-opt-code">{{ item.value }}</span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item :label="$t('modelConfigDialog.modelName')" prop="modelName">
          <el-input v-model="formData.modelName" :placeholder="$t('modelConfigDialog.enterModelName')"></el-input>
        </el-form-item>
        <el-form-item :label="$t('modelConfigDialog.modelCode')" prop="modelCode">
          <el-input v-model="formData.modelCode" :placeholder="$t('modelConfigDialog.enterModelCode')"></el-input>
        </el-form-item>
        <el-form-item :label="$t('modelConfigDialog.sortOrder')" prop="sortOrder">
          <el-input v-model="formData.sort" type="number" :placeholder="$t('modelConfigDialog.enterSortOrder')"></el-input>
        </el-form-item>
        <el-form-item :label="$t('modelConfigDialog.docLink')" prop="docLink">
          <el-input v-model="formData.docLink" :placeholder="$t('modelConfigDialog.enterDocLink')"></el-input>
        </el-form-item>
      </div>
      <el-form-item :label="$t('modelConfigDialog.remark')" prop="remark">
        <el-input v-model="formData.remark" type="textarea" :placeholder="$t('modelConfigDialog.enterRemark')"
          :autosize="{ minRows: 2, maxRows: 5 }"></el-input>
      </el-form-item>
    </el-form>

    <div class="md-section-head md-section-head--call">
      <h3 class="md-section-title">{{ $t('modelConfigDialog.callInfo') }}</h3>
    </div>
    <p v-if="!formData.supplier" class="md-empty">{{ $t('xn.admin.model.pickProviderFirst') }}</p>
    <p v-else-if="!dynamicCallInfoFields.length" class="md-empty">{{ $t('xn.admin.model.noCallFields') }}</p>
    <el-form v-else :model="formData.configJson" label-position="top" class="md-form" @submit.native.prevent>
      <div class="md-grid">
        <el-form-item v-for="field in dynamicCallInfoFields" :key="field.prop" :label="field.label" :prop="field.prop">
          <el-input v-model="formData.configJson[field.prop]" :placeholder="field.placeholder"
            :type="field.type || 'text'" :show-password="field.type === 'password'">
          </el-input>
        </el-form-item>
      </div>
    </el-form>
    <p v-if="isMock && hasSecretField" class="md-demo"><demo-tag /> {{ $t('xn.admin.secretNotSaved') }}</p>

    <span slot="footer">
      <el-button @click="handleClose">{{ $t('xn.common.cancel') }}</el-button>
      <el-button type="primary" @click="confirm" :loading="saving" :disabled="saving">{{ $t('modelConfigDialog.save') }}</el-button>
    </span>
  </el-dialog>
</template>

<script>
import Api from '@/apis/api';
import { IS_MOCK } from '@/utils/media';

const SECRET_WORDS = ['api_key', 'secret', 'token', 'password', 'private_key', 'access_key'];
export default {
  name: 'AddModelDialog',
  props: {
    visible: { type: Boolean, required: true },
    modelType: { type: String, required: true }
  },
  data() {
    return {
      saving: false,
      isMock: IS_MOCK,
      providers: [],
      dialogVisible: false,
      providersLoaded: false,
      providerFields: [],
      currentProvider: null,
      formData: {
        id: '',
        modelName: '',
        modelCode: '',
        supplier: '',
        sort: 1,
        docLink: '',
        remark: '',
        isEnabled: true,
        isDefault: true,
        configJson: {}
      }
    }
  },
  watch: {
    visible(val) {
      this.dialogVisible = val;
      if (val) {
        this.initConfigJson();
      } else {
        this.resetForm();
      }
    },
    'formData.supplier'(newVal) {
      this.currentProvider = this.providers.find(p => p.value === newVal);
      this.providerFields = this.currentProvider?.fields || [];
      this.initDynamicConfig();
    }
  },
  computed: {
    dynamicCallInfoFields() {
      return this.providerFields;
    },
    hasSecretField() {
      return this.providerFields.some((f) => SECRET_WORDS.some((w) => String(f.prop).toLowerCase().includes(w)));
    },
    chunkedCallInfoFields() {
      const chunkSize = 2;
      const result = [];
      for (let i = 0; i < this.dynamicCallInfoFields.length; i += chunkSize) {
        result.push(this.dynamicCallInfoFields.slice(i, i + chunkSize));
      }
      return result;
    }
  },
  methods: {
    loadProviders() {
      if (this.providersLoaded)
        return

      Api.model.getModelProviders(this.modelType, (data) => {
        this.providers = data.map(item => ({
          label: item.name,
          value: item.providerCode,
          fields: JSON.parse(item.fields || '[]').map(f => ({
            label: f.label,
            prop: f.key,
            type: f.type === 'password' ? 'password' : 'text',
            placeholder: `请输入${f.key}`
          }))
        }))
        this.providersLoaded = true
      })
    },
    initConfigJson() {
      const defaultConfig = {};
      this.providerFields.forEach(field => {
        defaultConfig[field.prop] = '';
      });
      this.formData.configJson = { ...defaultConfig };
    },
    handleVisibleChange(val) {
      this.dialogVisible = val;
      this.$emit('update:visible', val);
      if (!val) {
        this.resetForm();
      }
    },

    handleClose() {
      this.saving = false;
      this.$emit('update:visible', false);
    },
    initDynamicConfig() {
      const newConfig = {};
      this.providerFields.forEach(field => {
        newConfig[field.prop] = this.formData.configJson[field.prop] || '';
      });
      this.formData.configJson = newConfig;
    },
    confirm() {
      this.saving = true;

      // 校验模型ID不能为纯文字或空格
      if (this.formData.id && !this.validateModelId(this.formData.id)) {
        this.$message.error(this.$t('modelConfigDialog.invalidModelId'));
        this.saving = false;
        return;
      }

      if (!this.formData.supplier) {
        this.$message.error(this.$t('addModelDialog.requiredSupplier'));
        this.saving = false;
        return;
      }

      const submitData = {
        id: this.formData.id || '',
        modelName: this.formData.modelName || '',
        modelCode: this.formData.modelCode || '',
        supplier: this.formData.supplier,
        sort: this.formData.sort || 1,
        docLink: this.formData.docLink || '',
        remark: this.formData.remark || '',
        isEnabled: this.formData.isEnabled ? 1 : 0,
        isDefault: this.formData.isDefault ? 1 : 0,
        provideCode: this.formData.supplier,
        configJson: {
          ...this.formData.configJson,
          type: this.formData.supplier
        }
      };

      try {
        this.$emit('confirm', submitData);
        this.$emit('update:visible', false);
        this.resetForm();
      } catch (e) {
        console.error(e);
      } finally {
        this.saving = false;
      }
    },
    resetForm() {
      this.saving = false;
      this.formData = {
        id: '',
        modelName: '',
        modelCode: '',
        supplier: '',
        sort: 1,
        docLink: '',
        remark: '',
        isEnabled: true,
        isDefault: true,
        configJson: {}
      };
      // 重置加载状态
      this.providers = [];
      this.providersLoaded = false;
      // 重置字段配置
      this.providerFields = [];
      this.currentProvider = null;
    },
    
    // 校验模型ID：不能为纯文字或空格
    validateModelId(modelId) {
      if (!modelId || typeof modelId !== 'string') {
        return false;
      }
      
      // 去除首尾空格
      const trimmedId = modelId.trim();
      
      // 检查是否为空或纯空格
      if (trimmedId === '') {
        return false;
      }
      
      // 检查是否只包含字母（纯文字）
      if (/^[a-zA-Z]+$/.test(trimmedId)) {
        return false;
      }
      
      // 检查是否包含空格
      if (/\s/.test(trimmedId)) {
        return false;
      }
      
      // 允许字母、数字、下划线、连字符
      if (!/^[a-zA-Z0-9_-]+$/.test(trimmedId)) {
        return false;
      }
      
      return true;
    }
  }
}
</script>

<style scoped>
.md-section-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 0 0 12px; }
.md-section-head--call { margin-top: 4px; padding-top: 16px; border-top: 1px solid var(--xn-line-2); }
.md-section-title { margin: 0; font-size: 16px; font-weight: 600; color: var(--xn-ink); }
.md-switch { display: inline-flex; align-items: center; gap: 8px; font-size: 14px; color: var(--xn-ink-2); cursor: pointer; }
.md-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.md-code ::v-deep .el-input__inner { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.md-opt-code { float: right; margin-left: 16px; font-size: 12px; color: var(--xn-ink-3); }
.md-empty { margin: 0 0 16px; padding: 14px 16px; border-radius: var(--xn-r); background: var(--xn-mist-2); font-size: 13px; color: var(--xn-ink-3); }
.md-demo { display: flex; align-items: center; gap: 8px; margin: 0 0 8px; font-size: 13px; color: var(--xn-ink-3); }
@media (max-width: 640px) { .md-grid { grid-template-columns: 1fr; } }
</style>
