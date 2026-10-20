<template>
  <el-dialog :visible="visible" :title="$t('xn.mock.title')" width="520px" append-to-body @close="$emit('update:visible', false)">
    <p class="mp-desc">{{ $t('xn.mock.desc') }}</p>

    <section class="mp-sec">
      <h3>{{ $t('xn.mock.identity') }}</h3>
      <p class="xn-muted mp-hint">{{ $t('xn.mock.identityHint') }}</p>
      <el-button :disabled="!isAdmin" @click="switchTo('user')">{{ $t('xn.mock.switchToUser') }}</el-button>
      <el-button :disabled="isAdmin" @click="switchTo('admin')">{{ $t('xn.mock.switchToAdmin') }}</el-button>
    </section>

    <section class="mp-sec">
      <h3>{{ $t('xn.mock.scenario') }}</h3>
      <el-radio-group v-model="scenario.data" size="small" @change="apply">
        <el-radio-button label="normal">{{ $t('xn.mock.scenarioNormal') }}</el-radio-button>
        <el-radio-button label="empty">{{ $t('xn.mock.scenarioEmpty') }}</el-radio-button>
        <el-radio-button label="error">{{ $t('xn.mock.scenarioError') }}</el-radio-button>
      </el-radio-group>
    </section>

    <section class="mp-sec">
      <h3>{{ $t('xn.mock.balance') }}</h3>
      <el-radio-group v-model="scenario.balance" size="small" @change="apply">
        <el-radio-button label="realtime">{{ $t('xn.mock.balanceRealtime') }}</el-radio-button>
        <el-radio-button label="stale">{{ $t('xn.mock.balanceStale') }}</el-radio-button>
        <el-radio-button label="unavailable">{{ $t('xn.mock.balanceUnavailable') }}</el-radio-button>
      </el-radio-group>
    </section>

    <span slot="footer" class="mp-foot">
      <el-button type="danger" plain @click="reset"><xn-icon name="refresh" /> {{ $t('xn.mock.reset') }}</el-button>
      <el-button type="primary" @click="$emit('update:visible', false)">{{ $t('xn.common.close') }}</el-button>
    </span>
  </el-dialog>
</template>

<script>
/* 演示模式面板：只在 mock 构建中加载。切换场景后刷新页面，让各页面按新场景重新请求。 */
import { getScenario, setScenario, signInAs, resetDemoData } from '@/mock/controls';

export default {
  name: 'MockPanel',
  props: { visible: Boolean, isAdmin: Boolean },
  data() {
    return { scenario: getScenario() };
  },
  methods: {
    apply() {
      setScenario(this.scenario);
      this.$message.success(this.$t('xn.mock.applied'));
      setTimeout(() => window.location.reload(), 400);
    },
    switchTo(role) {
      const token = signInAs(role);
      if (!token) return;
      this.$store.commit('setToken', token);
      localStorage.removeItem('isSuperAdmin');
      window.location.hash = '#/home';
      window.location.reload();
    },
    reset() {
      this.$confirm(this.$t('xn.mock.resetConfirm'), this.$t('xn.mock.reset'), { type: 'warning' }).then(() => {
        const role = this.isAdmin ? 'admin' : 'user';
        resetDemoData();
        const token = signInAs(role);
        if (token) this.$store.commit('setToken', token);
        this.$message.success(this.$t('xn.mock.resetDone'));
        setTimeout(() => window.location.reload(), 400);
      }).catch(() => {});
    },
  },
};
</script>

<style scoped>
.mp-desc { margin: 0 0 8px; color: var(--xn-ink-2); line-height: 1.7; }
.mp-sec { padding: 16px 0 4px; border-top: 1px solid var(--xn-line-2); margin-top: 12px; }
.mp-sec h3 { margin: 0 0 8px; font-size: 14px; font-weight: 600; color: var(--xn-ink); }
.mp-hint { margin: -2px 0 10px; font-size: 13px; }
.mp-foot { display: flex; justify-content: space-between; }
</style>
