<template>
  <el-dialog :visible="visible" :title="$t('xn.admin.pwd.title')" width="440px" append-to-body
    :close-on-click-modal="false" @close="closeDialog">
    <p class="vp-help">{{ $t('xn.admin.pwd.help') }}</p>
    <label class="vp-label" for="vp-password">{{ $t('xn.admin.pwd.label') }}</label>
    <el-input id="vp-password" :value="password" readonly class="vp-input xn-num" />
    <p v-if="isMock" class="vp-demo">
      <demo-tag /> <span>{{ $t('xn.admin.pwd.demo') }}</span>
    </p>
    <span slot="footer">
      <el-button @click="closeDialog">{{ $t('xn.common.close') }}</el-button>
      <el-button type="primary" :disabled="!password" @click="copyPassword">{{ $t('xn.admin.pwd.copy') }}</el-button>
    </span>
  </el-dialog>
</template>

<script>
/* 重置密码结果：只显示本次返回的新密码，不保存。mock 模式下这是演示密码（在内存里临时生成）。 */
import { IS_MOCK } from '@/utils/media';

export default {
  name: 'ViewPasswordDialog',
  props: {
    visible: { type: Boolean, required: true },
    password: { type: String, default: '' }
  },
  data() {
    return { isMock: IS_MOCK };
  },
  methods: {
    closeDialog() {
      this.$emit('update:visible', false)
    },
    copyPassword() {
      const done = () => this.$message.success({ message: this.$t('xn.admin.pwd.copied'), showClose: true });
      const fail = () => this.$message.warning({ message: this.$t('xn.admin.pwd.copyFailed'), showClose: true });
      try {
        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(this.password).then(done, fail);
        } else {
          fail();
        }
      } catch (e) {
        fail();
      }
    }
  }
}
</script>

<style scoped>
.vp-help { margin: 0 0 16px; font-size: 14px; line-height: 1.7; color: var(--xn-ink-3); }
.vp-label { display: block; margin-bottom: 8px; font-size: 14px; font-weight: 500; color: var(--xn-ink-2); }
.vp-input ::v-deep .el-input__inner { font-size: 16px; font-weight: 600; letter-spacing: 0.04em; background: var(--xn-mist-2); }
.vp-demo { display: flex; align-items: flex-start; gap: 8px; margin: 12px 0 0; font-size: 13px; line-height: 1.6; color: var(--xn-ink-3); }
.vp-demo .xn-tag { flex: none; }
</style>
