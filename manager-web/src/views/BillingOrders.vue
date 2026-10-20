<template>
  <div class="xn-page bo">
    <page-header :title="$t('billing.ordersTitle')" :description="$t('xn.billing.ordersDesc')">
      <el-button type="primary" @click="$router.push('/billing/packages')"><xn-icon name="wallet" /> {{ $t('billing.rechargeNow') }}</el-button>
    </page-header>

    <!-- 余额：不显示来源名称，只区分 正常 / 可能不是最新 / 暂不可用 -->
    <div class="xn-toolbar bo-balance" aria-live="polite">
      <span class="xn-muted">{{ $t('billing.balance') }}</span>
      <template v-if="balanceState === 'loading'"><span class="xn-muted">{{ $t('billing.loading') }}</span></template>
      <template v-else-if="balanceState === 'unavailable'">
        <strong class="bo-balance__warn">{{ $t('billing.balanceUnavailable') }}</strong>
      </template>
      <template v-else>
        <strong class="bo-balance__num xn-num">{{ formatPoints(quota.balance) }}</strong>
        <span class="xn-muted">{{ $t('billing.pointsUnit') }}</span>
        <span v-if="balanceState === 'stale'" class="xn-tag xn-tag--warning"><i class="dot"></i>{{ $t('billing.balanceSourceCache') }}</span>
      </template>
      <demo-tag />
      <span class="xn-toolbar__grow"></span>
      <el-button type="text" @click="fetchQuota"><xn-icon name="refresh" /> {{ $t('xn.billing.refreshBalance') }}</el-button>
    </div>
    <el-alert v-if="balanceState === 'stale'" class="bo-alert" :title="$t('billing.balanceCacheHint')" type="warning" :closable="false" show-icon />

    <!-- 充值订单 -->
    <section class="xn-panel xn-panel--flush bo-panel">
      <div class="xn-panel__head">
        <h2 class="xn-panel__title">{{ $t('xn.billing.ordersPanel') }}</h2>
        <el-button type="text" :disabled="loading" @click="fetchOrders"><xn-icon name="refresh" /> {{ $t('xn.billing.refresh') }}</el-button>
      </div>
      <xn-empty v-if="ordersFailed && !loading" error @retry="fetchOrders" />
      <template v-else>
        <el-table :data="orders" v-loading="loading" row-key="outTradeNo">
          <el-table-column prop="outTradeNo" :label="$t('billing.orderNo')" min-width="190">
            <template slot-scope="scope"><span class="xn-num">{{ scope.row.outTradeNo }}</span></template>
          </el-table-column>
          <el-table-column prop="packageName" :label="$t('billing.packageName')" min-width="130" show-overflow-tooltip />
          <el-table-column :label="$t('billing.amount')" min-width="100" align="right">
            <template slot-scope="scope"><span class="xn-num">¥{{ formatYuan(scope.row.amountCents) }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('billing.rechargePoints')" min-width="100" align="right">
            <template slot-scope="scope"><span class="xn-num">{{ formatPoints(scope.row.quotaPoints) }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('billing.channel')" min-width="90">
            <template slot-scope="scope">{{ channelText(scope.row.channel) }}</template>
          </el-table-column>
          <el-table-column :label="$t('billing.status')" min-width="110">
            <template slot-scope="scope">
              <span class="xn-tag" :class="statusTagClass(scope.row.status)">{{ statusText(scope.row.status) }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="$t('billing.createdAt')" min-width="170">
            <template slot-scope="scope"><span class="xn-num">{{ formatTime(scope.row.createdAt) }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('xn.billing.colActions')" width="90" align="right">
            <template slot-scope="scope">
              <el-button type="text" @click="openOrder(scope.row)">{{ $t('xn.billing.viewOrder') }}</el-button>
            </template>
          </el-table-column>
          <template slot="empty">
            <xn-empty icon="receipt" :title="$t('billing.noOrders')" :description="$t('xn.billing.noOrdersDesc')">
              <el-button @click="$router.push('/billing/packages')">{{ $t('xn.billing.goPackages') }}</el-button>
            </xn-empty>
          </template>
        </el-table>
        <div v-if="total > 0" class="bo-pager">
          <el-pagination background layout="total, sizes, prev, pager, next" :total="total" :page-size="pageSize"
            :page-sizes="[10, 20, 50]" :current-page.sync="page" @current-change="fetchOrders" @size-change="onSizeChange" />
        </div>
      </template>
    </section>

    <!-- 官方服务（记忆）费用 -->
    <section class="xn-panel xn-panel--flush bo-panel">
      <div class="xn-panel__head">
        <div>
          <h2 class="xn-panel__title">{{ $t('xn.billing.memoryTitle') }}</h2>
          <p class="bo-sub xn-muted">{{ $t('xn.billing.memoryDesc') }}</p>
        </div>
        <el-button type="text" :disabled="memoryLoading" @click="fetchMemoryBills"><xn-icon name="refresh" /> {{ $t('xn.billing.refresh') }}</el-button>
      </div>
      <xn-empty v-if="!memoryAvailable && !memoryLoading" error :title="$t('xn.billing.memoryUnavailable')"
        :description="$t('xn.billing.memoryUnavailableDesc')" @retry="fetchMemoryBills" />
      <template v-else>
        <el-table :data="memoryBills" v-loading="memoryLoading">
          <el-table-column :label="$t('xn.billing.colTime')" min-width="170">
            <template slot-scope="scope"><span class="xn-num">{{ formatTime(scope.row.createdAt) }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('xn.billing.colItem')" min-width="110">
            <template slot-scope="scope">{{ memoryOperation(scope.row.operation) }}</template>
          </el-table-column>
          <el-table-column :label="$t('xn.billing.colFeeYuan')" min-width="130" align="right">
            <template slot-scope="scope"><span class="xn-num">¥{{ formatMemoryAmount(scope.row.amountCny) }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('xn.billing.colCharged')" min-width="100" align="right">
            <template slot-scope="scope"><span class="xn-num">{{ formatPoints(scope.row.chargedPoints) }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('billing.status')" min-width="100">
            <template slot-scope="scope"><span class="xn-tag" :class="memoryStateClass(scope.row.state)">{{ memoryState(scope.row.state) }}</span></template>
          </el-table-column>
          <template slot="empty">
            <xn-empty icon="memory" :title="$t('xn.billing.memoryEmpty')" />
          </template>
        </el-table>
        <div v-if="memoryTotal > 0" class="bo-pager">
          <el-pagination background layout="total, prev, pager, next" :total="memoryTotal" :page-size="10"
            :current-page.sync="memoryPage" @current-change="fetchMemoryBills" />
        </div>
      </template>
    </section>
  </div>
</template>

<script>
import Api from '@/apis/api';

/** 请求层对业务错误（code≠0）只弹出提示、不回调页面；超过这个时间仍无响应就显示失败状态，避免一直加载 */
const NO_REPLY_MS = 10000;
const MEMORY_OPS = { fact: 'memFact', portrait: 'memPortrait', search: 'memSearch', storage: 'memStorage' };
const MEMORY_STATES = { settled: 'msSettled', refunded: 'msRefunded', reserved: 'msProcessing', submitted: 'msProcessing', review: 'msReview', manual_review: 'msReview', pending: 'msPending', debt: 'msDebt' };

export default {
  name: 'BillingOrders',
  data() {
    return {
      loading: false,
      ordersFailed: false,
      orders: [],
      total: 0,
      page: 1,
      pageSize: 10,
      quota: null,
      quotaLoading: true,
      memoryBills: [], memoryPage: 1, memoryTotal: 0, memoryAvailable: true, memoryLoading: false
    };
  },
  mounted() {
    this.fetchOrders();
    this.fetchQuota();
    this.fetchMemoryBills();
  },
  beforeDestroy() {
    clearTimeout(this.ordersGuard);
    clearTimeout(this.memoryGuard);
    clearTimeout(this.quotaGuard);
  },
  computed: {
    /** 与外壳余额条一致：读取失败 / 余额或来源为空 → 暂不可用；cache 或非实时 → 可能不是最新 */
    balanceState() {
      if (this.quotaLoading) return 'loading';
      const q = this.quota;
      if (!q || q.balance === null || q.balance === undefined || q.balanceSource == null) return 'unavailable';
      if (q.balanceRealtime === false || q.balanceSource === 'cache') return 'stale';
      return 'ok';
    }
  },
  methods: {
    memoryOperation(value) { return this.$t('xn.billing.' + (MEMORY_OPS[value] || 'memOther')); },
    memoryState(value) { return this.$t('xn.billing.' + (MEMORY_STATES[value] || 'msProcessing')); },
    memoryStateClass(value) {
      if (value === 'settled') return 'xn-tag--success';
      if (value === 'refunded') return 'xn-tag--muted';
      if (value === 'debt') return 'xn-tag--warning';
      return 'xn-tag--lake';
    },
    formatMemoryAmount(value) { return Number(value || 0).toFixed(8).replace(/0+$/, '').replace(/\.$/, '.00'); },
    fetchMemoryBills() {
      this.memoryLoading = true;
      clearTimeout(this.memoryGuard);
      this.memoryGuard = setTimeout(() => { if (this.memoryLoading) { this.memoryLoading = false; this.memoryAvailable = false; } }, NO_REPLY_MS);
      Api.pay.memoryBills(this.memoryPage, (res) => {
        clearTimeout(this.memoryGuard);
        this.memoryLoading = false;
        this.memoryAvailable = !!(res && res.code === 0 && res.data && res.data.available);
        this.memoryBills = this.memoryAvailable ? res.data.list || [] : [];
        this.memoryTotal = this.memoryAvailable ? res.data.total || 0 : 0;
      });
    },
    formatYuan(cents) {
      if (cents === null || cents === undefined) return '0.00';
      return (Number(cents) / 100).toFixed(2);
    },
    formatPoints(points) {
      if (points === null || points === undefined) return '0';
      const n = Number(points);
      if (isNaN(n)) return '0';
      return n.toFixed(3).replace(/\.?0+$/, '') || '0';
    },
    formatTime(t) {
      if (!t) return '-';
      const d = new Date(t);
      const pad = (n) => (n < 10 ? '0' + n : '' + n);
      return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' +
        pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
    },
    channelText(c) {
      if (c === 'alipay') return this.$t('billing.channelAlipay');
      if (c === 'wechat') return this.$t('billing.channelWechat');
      if (c === 'mock') return this.$t('billing.channelMock');
      return c || '-';
    },
    statusText(s) {
      if (s === 'pending') return this.$t('billing.statusPending');
      if (s === 'paid') return this.$t('billing.statusPaid');
      if (s === 'delivered') return this.$t('billing.statusDelivered');
      if (s === 'closed') return this.$t('billing.statusClosed');
      if (s === 'refunded') return this.$t('billing.statusRefunded');
      if (s === 'failed') return this.$t('billing.statusFailed');
      return s || '-';
    },
    statusTagClass(s) {
      if (s === 'delivered') return 'xn-tag--success';
      if (s === 'paid') return 'xn-tag--lake';
      if (s === 'pending') return 'xn-tag--warning';
      if (s === 'failed') return 'xn-tag--danger';
      return 'xn-tag--muted';
    },
    openOrder(row) {
      this.$router.push({ path: '/billing/result', query: { out_trade_no: row.outTradeNo } });
    },
    onSizeChange(size) {
      this.pageSize = size;
      this.page = 1;
      this.fetchOrders();
    },
    fetchOrders() {
      this.loading = true;
      this.ordersFailed = false;
      clearTimeout(this.ordersGuard);
      this.ordersGuard = setTimeout(() => { if (this.loading) { this.loading = false; this.ordersFailed = true; } }, NO_REPLY_MS);
      Api.pay.orders({ page: this.page, limit: this.pageSize }, (res) => {
        clearTimeout(this.ordersGuard);
        this.loading = false;
        if (res && res.code === 0) {
          const data = res.data || {};
          this.orders = data.list || [];
          this.total = data.total || 0;
        } else {
          this.ordersFailed = true;
          this.$message.error(res && res.msg ? res.msg : this.$t('billing.loadFail'));
        }
      });
    },
    fetchQuota() {
      this.quotaLoading = true;
      clearTimeout(this.quotaGuard);
      this.quotaGuard = setTimeout(() => { if (this.quotaLoading) { this.quotaLoading = false; this.quota = null; } }, NO_REPLY_MS);
      Api.pay.myQuota((res) => {
        clearTimeout(this.quotaGuard);
        this.quotaLoading = false;
        if (res && res.code === 0) {
          this.quota = res.data;
        } else {
          // 失败时清空，避免把旧余额伪装成最新
          this.quota = null;
          this.$message.error(res && res.msg ? res.msg : this.$t('billing.loadFail'));
        }
      });
    }
  }
};
</script>

<style scoped>
.bo-balance { gap: 10px; }
.bo-balance__num { font-size: 20px; font-weight: 600; color: var(--xn-ink); }
.bo-balance__warn { color: var(--xn-warning); font-weight: 600; }
.bo-alert { margin: -4px 0 16px; }
.bo-panel { overflow: hidden; }
.bo-sub { margin: 2px 0 0; font-size: 13px; }
.bo-pager { display: flex; justify-content: flex-end; padding: 2px 20px 14px; }
</style>
