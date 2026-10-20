<template>
  <el-dialog :title="title" :visible="visible" width="520px" :append-to-body="true" :close-on-click-modal="false"
    :key="dialogKey" custom-class="xn-param-dialog" @close="cancel">
    <el-form :model="form" :rules="rules" ref="form" label-position="top" @submit.native.prevent>
      <el-form-item :label="$t('paramDialog.paramCode')" prop="paramCode">
        <el-input v-model="form.paramCode" :placeholder="$t('paramDialog.paramCodePlaceholder')" class="xn-num" />
      </el-form-item>

      <el-form-item :label="$t('paramDialog.paramValue')" prop="paramValue">
        <el-input v-model="form.paramValue" type="textarea" :autosize="{ minRows: 1, maxRows: 6 }"
          :placeholder="$t('paramDialog.paramValuePlaceholder')" />
        <p v-if="isMock && isSecret" class="pd-hint"><demo-tag /> {{ $t('xn.admin.secretNotSaved') }}</p>
      </el-form-item>

      <el-form-item :label="$t('paramDialog.valueType')" prop="valueType">
        <el-select v-model="form.valueType" :placeholder="$t('paramDialog.valueTypePlaceholder')" style="width: 100%">
          <el-option v-for="item in valueTypeOptions" :key="item.value" :label="$t(`paramDialog.${item.value}Type`)"
            :value="item.value" />
        </el-select>
      </el-form-item>

      <el-form-item :label="$t('paramDialog.remark')" prop="remark">
        <el-input type="textarea" v-model="form.remark" :placeholder="$t('paramDialog.remarkPlaceholder')" :rows="3" />
      </el-form-item>
    </el-form>

    <span slot="footer" class="pd-footer">
      <el-button class="pd-reset" @click="reset">{{ $t('xn.common.reset') }}</el-button>
      <span class="pd-grow"></span>
      <el-button @click="cancel">{{ $t('paramDialog.cancel') }}</el-button>
      <el-button type="primary" @click="submit" :loading="saving" :disabled="saving">{{ $t('paramDialog.save') }}</el-button>
    </span>
  </el-dialog>
</template>

<script>
import { IS_MOCK } from '@/utils/media';

const SECRET_WORDS = ['api_key', 'secret', 'token', 'password', 'private_key', 'signature_key', 'access_key'];

export default {
  props: {
    title: {
      type: String,
      default: '新增参数'
    },
    visible: {
      type: Boolean,
      default: false
    },
    form: {
      type: Object,
      default: () => ({
        id: null,
        paramCode: '',
        paramValue: '',
        valueType: 'string',
        remark: ''
      })
    }
  },
  data() {
    return {
      dialogKey: Date.now(),
      saving: false,
      isMock: IS_MOCK,
      snapshot: null,
      valueTypeOptions: [
        { value: 'string' },
        { value: 'number' },
        { value: 'boolean' },
        { value: 'array' },
        { value: 'json' }
      ],
      rules: {
        paramCode: [
          { required: true, message: this.$t('paramDialog.requiredParamCode'), trigger: "blur" }
        ],
        paramValue: [
          { required: true, message: this.$t('paramDialog.requiredParamValue'), trigger: "blur" }
        ],
        valueType: [
          { required: true, message: this.$t('paramDialog.requiredValueType'), trigger: "change" }
        ]
      }
    };
  },
  computed: {
    isSecret() {
      const code = String(this.form.paramCode || '').toLowerCase();
      return SECRET_WORDS.some((w) => code.includes(w));
    },
  },
  methods: {
    submit() {
      this.$refs.form.validate((valid) => {
        if (valid) {
          this.saving = true; // 开始加载
          this.$emit('submit', this.form);
          // 业务错误时请求层不回调：避免保存按钮一直转圈
          clearTimeout(this._savingTimer);
          this._savingTimer = setTimeout(() => { this.saving = false; }, 8000);
        }
      });
    },
    cancel() {
      this.saving = false; // 取消时重置状态
      this.$emit('cancel');
      this.$emit('update:visible', false);
    },
    // 恢复到打开弹窗时的内容
    reset() {
      if (this.snapshot) Object.keys(this.snapshot).forEach((k) => { this.form[k] = this.snapshot[k]; });
      this.$nextTick(() => this.$refs.form && this.$refs.form.clearValidate());
    },

    // 提供给父组件调用以重置saving状态
    resetSaving() {
      this.saving = false;
    }
  },
  watch: {
    visible: {
      immediate: true,
      handler(newVal) {
        if (newVal) {
          this.dialogKey = Date.now();
          this.snapshot = { ...this.form };
        } else {
          // 当对话框关闭时，重置saving状态
          this.saving = false;
          clearTimeout(this._savingTimer);
        }
      }
    }
  }
};
</script>

<style scoped>
.pd-hint { display: flex; align-items: center; gap: 8px; margin: 8px 0 0; font-size: 13px; line-height: 1.5; color: var(--xn-ink-3); }
.pd-footer { display: flex; align-items: center; }
.pd-grow { flex: 1; }
</style>
