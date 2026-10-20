<template>
  <div class="xn-page">
    <page-header :title="$t('serverSideManager.pageTitle')" :description="$t('xn.admin.server.desc')">
      <el-button @click="fetchParams" :loading="loading"><xn-icon name="refresh" /> {{ $t('xn.admin.refresh') }}</el-button>
    </page-header>

    <div v-if="isMock" class="xa-demo-note">
      <demo-tag :text="$t('xn.common.simulated')" />
      <span>{{ $t('xn.admin.server.demoNote') }}</span>
    </div>

    <div class="xn-panel xn-panel--flush xa-panel">
      <xn-empty v-if="loadFailed && !loading" error @retry="fetchParams" />
      <el-table v-else ref="paramsTable" :data="paramsList" v-loading="loading" row-key="address">
        <el-table-column :label="$t('serverSideManager.wsAddress')" min-width="320">
          <template slot-scope="{ row }"><span class="xa-code">{{ row.address }}</span></template>
        </el-table-column>
        <el-table-column :label="$t('xn.admin.server.lastAction')" min-width="260">
          <template slot-scope="{ row }">
            <span v-if="row.pending" class="xn-tag xn-tag--lake"><i class="dot"></i>{{ $t('xn.admin.server.sending') }}</span>
            <span v-else-if="row.lastResult" class="xa-result">
              <span class="xn-tag" :class="row.lastResult.ok ? 'xn-tag--success' : 'xn-tag--danger'">
                <i class="dot"></i>{{ row.lastResult.label }}{{ row.lastResult.ok ? $t('xn.admin.server.sent') : $t('xn.admin.server.failed') }}
              </span>
              <span class="xn-muted xn-num">{{ row.lastResult.time }}</span>
              <demo-tag v-if="isMock && row.lastResult.ok" :text="$t('xn.common.simulated')" />
            </span>
            <span v-else class="xn-muted">{{ $t('xn.admin.server.noAction') }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="$t('serverSideManager.operation')" width="200" align="right">
          <template slot-scope="scope">
            <el-button type="text" :disabled="scope.row.pending" @click="emitAction(scope.row, actionMap.update_config)">{{ $t('serverSideManager.updateConfig') }}</el-button>
            <el-button type="text" class="xa-danger" :disabled="scope.row.pending" @click="emitAction(scope.row, actionMap.restart)">{{ $t('serverSideManager.restart') }}</el-button>
          </template>
        </el-table-column>
        <template slot="empty">
          <xn-empty icon="globe" :title="$t('xn.admin.server.empty')" :description="$t('xn.admin.server.emptyDesc')">
            <el-button @click="$router.push('/params-management')">{{ $t('xn.admin.server.goParams') }}</el-button>
          </xn-empty>
        </template>
      </el-table>
    </div>
  </div>
</template>

<script>
import Api from "@/apis/api";
import { IS_MOCK } from "@/utils/media";

export default {
  data() {
    return {
      isMock: IS_MOCK,
      paramsList: [],
      loading: false,
      loadFailed: false,
      total: 0,
    };
  },
  created() {
    this.fetchParams();
  },
  beforeDestroy() {
    clearTimeout(this._loadTimer);
  },
  computed: {
    actionMap() {
      return {
        restart: {
          value: 'restart',
          title: this.$t('serverSideManager.restartServer'),
          message: this.$t('serverSideManager.confirmRestart'),
          confirmText: this.$t('serverSideManager.restart'),
        },
        update_config: {
          value: 'update_config',
          title: this.$t('serverSideManager.updateConfigTitle'),
          message: this.$t('serverSideManager.confirmUpdateConfig'),
          confirmText: this.$t('serverSideManager.updateConfig'),
        }
      };
    }
  },
  methods: {
    fetchParams() {
      this.loading = true;
      this.loadFailed = false;
      clearTimeout(this._loadTimer);
      // 业务错误由请求层统一提示且不回调；超过 8 秒仍无结果时显示失败状态
      this._loadTimer = setTimeout(() => {
        if (this.loading) { this.loading = false; this.loadFailed = true; }
      }, 8000);
      Api.admin.getWsServerList(
        {},
        ({ data }) => {
          this.loading = false;
          clearTimeout(this._loadTimer);
          if (data.code === 0) {
            this.paramsList = (data.data || []).map(item => ({ address: item, pending: false, lastResult: null }));
            this.total = (data.data || []).length;
          } else {
            this.loadFailed = true;
            this.$message.error({
              message: data.msg || this.$t('serverSideManager.getServerListFailed'),
              showClose: true
            });
          }
        }
      );
    },
    timeNow() {
      const d = new Date();
      const p = (n) => String(n).padStart(2, '0');
      return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
    },
    emitAction(rowItem, actionItem) {
      if (actionItem === undefined || rowItem.address === undefined) {
        return;
      }
      // 弹开询问框
      this.$confirm(this.$t('xn.admin.server.confirm', { msg: actionItem.message, address: rowItem.address }), actionItem.title, {
        confirmButtonText: actionItem.confirmText, // 确认按钮文本
        cancelButtonText: this.$t('common.cancel'), // 取消按钮文本
        type: 'warning',
      }).then(() => {
        // 用户点击了确认按钮
        rowItem.pending = true;
        clearTimeout(rowItem._timer);
        // 业务错误时请求层不回调：超时后显示为失败
        rowItem._timer = setTimeout(() => {
          if (rowItem.pending) {
            rowItem.pending = false;
            rowItem.lastResult = { ok: false, label: actionItem.confirmText, time: this.timeNow() };
          }
        }, 8000);
        Api.admin.sendWsServerAction({
          targetWs: rowItem.address,
          action: actionItem.value
        }, ({ data }) => {
          rowItem.pending = false;
          clearTimeout(rowItem._timer);
          if (data.code !== 0) {
            rowItem.lastResult = { ok: false, label: actionItem.confirmText, time: this.timeNow() };
            this.$message.error({
              message: data.msg || this.$t('serverSideManager.operationFailed'),
              showClose: true
            });
            return;
          }
          rowItem.lastResult = { ok: true, label: actionItem.confirmText, time: this.timeNow() };
          // 演示模式下显示接口返回的“演示结果”说明，避免误以为真实服务器已执行
          const simulated = this.isMock && data.msg && data.msg !== 'success';
          this.$message.success({
            message: simulated ? data.msg : (actionItem.value === 'restart' ? this.$t('serverSideManager.restartSuccess') : this.$t('serverSideManager.updateConfigSuccess')),
            showClose: true,
            duration: simulated ? 5000 : 3000,
          })
        })
      }).catch(() => {})
    },
  },
};
</script>

<style scoped>
.xa-panel { overflow: hidden; }
.xa-panel ::v-deep .el-table th.el-table__cell:first-child > .cell, .xa-panel ::v-deep .el-table td.el-table__cell:first-child > .cell { padding-left: 20px; }
.xa-code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; word-break: break-all; }
.xa-result { display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.xa-danger { color: var(--xn-danger); }
.xa-danger:hover, .xa-danger:focus { color: #8D3523; }
.xa-danger.is-disabled { color: var(--xn-ink-4); }
.xa-demo-note {
  display: flex; align-items: center; gap: 10px; margin-bottom: 16px; padding: 10px 14px;
  border: 1px solid var(--xn-line); border-radius: var(--xn-r-lg); background: var(--xn-white);
  font-size: 13px; line-height: 1.6; color: var(--xn-ink-2);
}
.xa-demo-note .xn-tag { flex: none; }
</style>
