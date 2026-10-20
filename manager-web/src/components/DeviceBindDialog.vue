<template>
  <el-dialog :visible="visible" :title="$t('device.dialogTitle')" width="560px" append-to-body
    custom-class="xn-bind-dialog" @open="onOpen" @close="close">
    <!-- 没有智能体时无法绑定：先引导创建 -->
    <xn-empty v-if="agentsLoaded && !agents.length" icon="agent" :title="$t('xn.bind.noAgentTitle')"
      :description="$t('xn.bind.noAgentDesc')">
      <el-button type="primary" @click="goCreateAgent">{{ $t('home.addAgent') }}</el-button>
    </xn-empty>

    <template v-else>
      <div class="bd-agent">
        <label class="bd-label" for="bd-agent">{{ $t('xn.bind.agent') }}</label>
        <el-select id="bd-agent" v-model="selectedAgent" filterable :loading="!agentsLoaded" :placeholder="$t('xn.bind.agentPlaceholder')">
          <el-option v-for="a in agents" :key="a.id" :label="a.agentName" :value="a.id">
            <span>{{ a.agentName }}</span>
            <span class="bd-opt-count">{{ $t('xn.bind.boundCount', { n: a.deviceCount || 0 }) }}</span>
          </el-option>
        </el-select>
      </div>

      <div class="bd-tabs" role="tablist">
        <button v-for="t in tabs" :key="t.key" type="button" role="tab" class="bd-tab"
          :class="{ 'is-on': tab === t.key }" :aria-selected="String(tab === t.key)" @click="tab = t.key">
          <xn-icon :name="t.icon" /> {{ t.label }}
        </button>
      </div>

      <!-- 验证码绑定 / 恢复设备连接：同一个接口，提示不同 -->
      <section v-if="tab !== 'manual'" class="bd-pane">
        <p class="bd-help">{{ tab === 'code' ? $t('xn.bind.codeHelp') : $t('xn.bind.recoverHelp') }}</p>
        <label class="bd-label">{{ tab === 'code' ? $t('device.bindWithCode') : $t('xn.bind.recoverCode') }}</label>
        <div class="bd-cells" :class="{ 'is-err': codeError }" @paste.prevent="onPaste">
          <input v-for="(c, i) in cells" :key="i" ref="cell" v-model="cells[i]" class="bd-cell xn-num" inputmode="numeric"
            maxlength="1" autocomplete="off" :aria-label="$t('xn.bind.digit', { n: i + 1 })"
            @input="onCellInput(i, $event)" @keydown="onCellKey(i, $event)" @focus="$event.target.select()" />
        </div>
        <p v-if="codeError" class="bd-err" role="alert">{{ codeError }}</p>
      </section>

      <!-- 手动添加（字段与校验沿用原 ManualAddDeviceDialog） -->
      <section v-else class="bd-pane">
        <p class="bd-help">{{ $t('xn.bind.manualHelp') }}</p>
        <el-form ref="manualForm" :model="manual" :rules="rules" label-position="top">
          <el-form-item :label="$t('manualAddDeviceDialog.deviceType')" prop="board">
            <el-select v-model="manual.board" :placeholder="$t('manualAddDeviceDialog.deviceTypePlaceholder')" style="width: 100%">
              <el-option v-for="item in firmwareTypes" :key="item.key" :label="item.name" :value="item.key" />
            </el-select>
          </el-form-item>
          <div class="bd-row">
            <el-form-item :label="$t('manualAddDeviceDialog.firmwareVersion')" prop="appVersion">
              <el-input v-model="manual.appVersion" :placeholder="$t('manualAddDeviceDialog.firmwareVersionPlaceholder')" />
            </el-form-item>
            <el-form-item :label="$t('manualAddDeviceDialog.macAddress')" prop="macAddress">
              <el-input v-model="manual.macAddress" class="xn-num" placeholder="00:1A:2B:3C:4D:5E" />
            </el-form-item>
          </div>
        </el-form>
      </section>
    </template>

    <span v-if="agents.length" slot="footer">
      <el-button @click="close">{{ $t('device.cancelButton') }}</el-button>
      <el-button type="primary" :loading="loading" :disabled="!canSubmit" @click="submit">{{ submitLabel }}</el-button>
    </span>
  </el-dialog>
</template>

<script>
/**
 * 添加设备（顶栏“添加设备”与设备管理页共用）。合并了原 AddDeviceDialog（含 recovery 模式）与 ManualAddDeviceDialog：
 * - 验证码绑定、恢复设备连接：Api.device.bindDevice(agentId, code)，与原组件完全相同，只是提示文案不同；
 * - 手动添加：Api.device.manualAddDevice({ agentId, board, appVersion, macAddress })，字段与校验同原组件。
 */
import Api from '@/apis/api';

const MAC_RE = /^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$/;

export default {
  name: 'DeviceBindDialog',
  props: {
    visible: { type: Boolean, default: false },
    agentId: { type: String, default: '' },     // 预选的智能体；空则默认第一个
    mode: { type: String, default: 'code' },    // code | recovery | manual
  },
  data() {
    const validateMac = (rule, value, callback) => {
      if (!value) callback(new Error(this.$t('manualAddDeviceDialog.requiredMacAddress')));
      else if (!MAC_RE.test(value)) callback(new Error(this.$t('manualAddDeviceDialog.invalidMacAddress')));
      else callback();
    };
    return {
      agents: [],
      agentsLoaded: false,
      tab: 'code',
      selectedAgent: '',
      cells: ['', '', '', '', '', ''],
      codeError: '',
      loading: false,
      firmwareTypes: [],
      manual: { board: '', appVersion: '', macAddress: '' },
      rules: {
        board: [{ required: true, message: this.$t('manualAddDeviceDialog.requiredDeviceType'), trigger: 'change' }],
        appVersion: [{ required: true, message: this.$t('manualAddDeviceDialog.requiredFirmwareVersion'), trigger: 'blur' }],
        macAddress: [{ required: true, validator: validateMac, trigger: 'blur' }],
      },
    };
  },
  computed: {
    tabs() {
      return [
        { key: 'code', icon: 'key', label: this.$t('device.bindWithCode') },
        { key: 'recovery', icon: 'refresh', label: this.$t('device.recoverConnection') },
        { key: 'manual', icon: 'edit', label: this.$t('device.manualAdd') },
      ];
    },
    code() { return this.cells.join(''); },
    canSubmit() {
      if (!this.selectedAgent) return false;
      return this.tab === 'manual' ? true : /^\d{6}$/.test(this.code);
    },
    submitLabel() {
      if (this.tab === 'recovery') return this.$t('xn.bind.recoverSubmit');
      if (this.tab === 'manual') return this.$t('manualAddDeviceDialog.confirm');
      return this.$t('xn.bind.bindSubmit');
    },
  },
  watch: {
    tab() { this.codeError = ''; this.focusFirst(); },
  },
  mounted() {
    window.addEventListener('xn:request-failed', this.onRequestFailed);
  },
  beforeDestroy() {
    window.removeEventListener('xn:request-failed', this.onRequestFailed);
  },
  methods: {
    // bindDevice / manualAddDevice 没有 fail 回调，业务错误时只会弹全局提示；这里结束加载并在验证码下方显示原因
    onRequestFailed({ detail }) {
      if (!this.loading || !/\/device\/(bind\/|manual-add)/.test(detail.url)) return;
      this.loading = false;
      if (this.tab !== 'manual') this.codeError = detail.msg || this.$t('device.bindFailed');
    },
    onOpen() {
      this.tab = this.mode;
      this.resetCode();
      this.fetchAgents();
      if (!this.firmwareTypes.length) this.fetchFirmwareTypes();
      this.focusFirst();
    },
    fetchAgents() {
      this.agentsLoaded = false;
      Api.agent.getAgentList(({ data }) => {
        this.agents = (data && data.data) || [];
        this.agentsLoaded = true;
        const preset = this.agentId && this.agents.some((a) => a.id === this.agentId) ? this.agentId : '';
        this.selectedAgent = preset || (this.agents[0] && this.agents[0].id) || '';
      });
    },
    async fetchFirmwareTypes() {
      try {
        const res = await Api.dict.getDictDataByType('FIRMWARE_TYPE');
        this.firmwareTypes = res.data || [];
      } catch (error) {
        this.$message.error(error.message || this.$t('manualAddDeviceDialog.getFirmwareTypeFailed'));
      }
    },
    focusFirst() {
      this.$nextTick(() => { const c = this.$refs.cell; if (c && c[0]) c[0].focus(); });
    },
    resetCode() {
      this.cells = ['', '', '', '', '', ''];
      this.codeError = '';
    },
    onCellInput(i, e) {
      const v = String(e.target.value || '').replace(/\D/g, '');
      if (v.length > 1) { this.fillFrom(i, v); return; }
      this.$set(this.cells, i, v);
      this.codeError = '';
      if (v && i < 5) this.$refs.cell[i + 1].focus();
    },
    onCellKey(i, e) {
      if (e.key === 'Backspace' && !this.cells[i] && i > 0) { this.$set(this.cells, i - 1, ''); this.$refs.cell[i - 1].focus(); e.preventDefault(); }
      else if (e.key === 'ArrowLeft' && i > 0) { this.$refs.cell[i - 1].focus(); e.preventDefault(); }
      else if (e.key === 'ArrowRight' && i < 5) { this.$refs.cell[i + 1].focus(); e.preventDefault(); }
      else if (e.key === 'Enter') { e.preventDefault(); this.submit(); }
    },
    onPaste(e) {
      const digits = ((e.clipboardData && e.clipboardData.getData('text')) || '').replace(/\D/g, '').slice(0, 6);
      if (digits) this.fillFrom(digits.length === 6 ? 0 : this.$refs.cell.indexOf(document.activeElement), digits);
    },
    fillFrom(start, digits) {
      const from = Math.max(0, start);
      digits.split('').forEach((d, k) => { if (from + k < 6) this.$set(this.cells, from + k, d); });
      this.$nextTick(() => this.$refs.cell[Math.min(from + digits.length, 5)].focus());
    },
    submit() {
      if (!this.canSubmit || this.loading) {
        if (this.tab !== 'manual' && !/^\d{6}$/.test(this.code)) this.codeError = this.$t('device.input6DigitCode');
        return;
      }
      const agentId = this.selectedAgent;
      if (this.tab === 'manual') {
        this.$refs.manualForm.validate((valid) => {
          if (!valid) return;
          this.loading = true;
          Api.device.manualAddDevice({ agentId, ...this.manual }, ({ data }) => {
            this.loading = false;
            if (data.code === 0) {
              this.$message.success(this.$t('manualAddDeviceDialog.addSuccess'));
              this.done(agentId);
            } else {
              this.$message.error(data.msg || this.$t('manualAddDeviceDialog.addFailed'));
            }
          });
        });
        return;
      }
      const recovery = this.tab === 'recovery';
      this.loading = true;
      Api.device.bindDevice(agentId, this.code, ({ data }) => {
        this.loading = false;
        if (data.code === 0) {
          this.$message.success({
            message: data.msg && data.msg !== 'success' ? data.msg : (recovery ? this.$t('device.recoverSuccess') : this.$t('device.bindSuccess')),
            showClose: true,
          });
          this.done(agentId);
        } else {
          this.codeError = data.msg || this.$t('device.bindFailed');
        }
      });
    },
    done(agentId) {
      this.$emit('bound', { agentId });
      this.$eventBus.$emit('xn:devices-changed', { agentId });
      this.close();
    },
    close() {
      this.$emit('update:visible', false);
      this.resetCode();
      if (this.$refs.manualForm) this.$refs.manualForm.resetFields();
    },
    goCreateAgent() {
      this.close();
      this.$router.push({ path: '/home', query: { create: '1' } }).catch(() => {});
    },
  },
};
</script>

<style scoped>
.bd-label { display: block; margin-bottom: 8px; font-size: 14px; font-weight: 500; color: var(--xn-ink-2); }
.bd-agent { margin-bottom: 18px; }
.bd-agent .el-select { width: 100%; }
.bd-opt-count { float: right; margin-left: 16px; font-size: 12px; color: var(--xn-ink-3); }
.bd-tabs { display: flex; gap: 4px; padding: 4px; margin-bottom: 18px; border-radius: 10px; background: var(--xn-mist); }
.bd-tab {
  flex: 1; display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 36px;
  border: 0; border-radius: 8px; background: none; color: var(--xn-ink-2); font: inherit; font-size: 14px; cursor: pointer;
}
.bd-tab:hover { color: var(--xn-ink); }
.bd-tab.is-on { background: #fff; color: var(--xn-ink); font-weight: 600; box-shadow: 0 1px 2px rgba(30, 43, 64, 0.08); }
.bd-pane { min-height: 168px; }
.bd-help { margin: 0 0 14px; font-size: 13px; line-height: 1.7; color: var(--xn-ink-3); }
.bd-cells { display: flex; gap: 10px; }
.bd-cell {
  width: 52px; height: 58px; padding: 0; border: 1.5px solid var(--xn-line); border-radius: 10px; background: #fff;
  font: 600 24px/1 var(--xn-sans); color: var(--xn-ink); text-align: center; caret-color: var(--xn-lake);
}
.bd-cell:hover { border-color: #AEBBC8; }
.bd-cell:focus { outline: none; border-color: var(--xn-lake); box-shadow: var(--xn-focus); }
.bd-cells.is-err .bd-cell { border-color: var(--xn-danger); }
.bd-err { margin: 10px 0 0; font-size: 13px; color: var(--xn-danger); }
.bd-row { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
@media (max-width: 560px) {
  .bd-cell { width: 42px; height: 50px; font-size: 20px; }
  .bd-row { grid-template-columns: 1fr; }
  .bd-tab { font-size: 13px; }
}
</style>
