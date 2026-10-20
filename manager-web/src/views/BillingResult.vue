<template>
  <div class="xn-page br">
    <page-header :title="$t('billing.resultTitle')" back="/billing/packages" :back-label="$t('billing.backPackages')" />

    <section class="xn-panel br-panel" aria-live="polite">
      <div v-if="loading" class="br-loading" v-loading="true" :element-loading-text="$t('billing.loading')"></div>

      <xn-empty v-else-if="loadFailed" error :description="loadError || $t('xn.billing.orderLoadFail')" @retry="refresh">
        <el-button @click="refresh"><xn-icon name="refresh" /> {{ $t('xn.common.retry') }}</el-button>
        <el-button @click="goOrders">{{ $t('billing.viewOrders') }}</el-button>
      </xn-empty>

      <xn-empty v-else-if="!order" icon="receipt" :title="$t('billing.noOrder')" :description="$t('xn.billing.noOrderDesc')">
        <el-button type="primary" @click="goPackages">{{ $t('billing.backPackages') }}</el-button>
        <el-button @click="goOrders">{{ $t('billing.viewOrders') }}</el-button>
      </xn-empty>

      <div v-else class="br-box">
        <div class="br-status" :class="statusClass">
          <span class="br-status__icon" aria-hidden="true">
            <i v-if="isProcessing" class="el-icon-loading"></i>
            <xn-icon v-else :name="order.status === 'delivered' ? 'check' : 'alert'" />
          </span>
          <div>
            <h2 class="br-status__text">{{ statusText }} <demo-tag :text="$t('xn.common.simulated')" /></h2>
            <p class="br-status__desc">{{ statusDesc }}</p>
          </div>
        </div>

        <dl class="br-meta">
          <div><dt>{{ $t('billing.orderNo') }}</dt><dd class="xn-num">{{ order.outTradeNo }}</dd></div>
          <div><dt>{{ $t('billing.packageName') }}</dt><dd>{{ order.packageName }}</dd></div>
          <div><dt>{{ $t('billing.amount') }}</dt><dd class="xn-num">¥{{ formatYuan(order.amountCents) }}</dd></div>
          <div><dt>{{ $t('billing.quota') }}</dt><dd class="xn-num">{{ formatPoints(order.quotaPoints) }}</dd></div>
        </dl>

        <div class="br-actions">
          <el-button v-if="isProcessing" @click="refresh"><xn-icon name="refresh" /> {{ $t('billing.refresh') }}</el-button>
          <el-button :type="order.status === 'delivered' ? 'primary' : 'default'" @click="goOrders">{{ $t('billing.viewOrders') }}</el-button>
          <el-button :type="order.status === 'delivered' ? 'default' : 'primary'" @click="goPackages">{{ $t('billing.backPackages') }}</el-button>
        </div>
      </div>
    </section>
  </div>
</template>

<script>
import Api from '@/apis/api';

/** 请求层对业务错误（code≠0）只弹出提示、不回调页面；超过这个时间仍无响应就显示失败状态，避免一直加载 */
const NO_REPLY_MS = 10000;

export default {
  name: 'BillingResult',
  data() {
    return {
      loading: true,
      loadFailed: false,
      loadError: '',
      order: null,
      pollTimer: null
    };
  },
  computed: {
    isProcessing() {
      return !!this.order && (this.order.status === 'pending' || this.order.status === 'paid');
    },
    statusClass() {
      if (!this.order) return '';
      if (this.order.status === 'delivered') return 'status-success';
      if (this.order.status === 'paid') return 'status-processing';
      if (this.order.status === 'pending') return 'status-processing';
      return 'status-failed';
    },
    statusText() {
      if (!this.order) return '';
      if (this.order.status === 'delivered') return this.$t('billing.statusDelivered');
      if (this.order.status === 'paid') return this.$t('billing.statusPaid');
      if (this.order.status === 'pending') return this.$t('billing.statusPending');
      if (this.order.status === 'closed') return this.$t('billing.statusClosed');
      if (this.order.status === 'refunded') return this.$t('billing.statusRefunded');
      return this.$t('billing.statusFailed');
    },
    statusDesc() {
      if (!this.order) return '';
      const s = this.order.status;
      if (s === 'delivered') return this.$t('xn.billing.descDelivered', { n: this.formatPoints(this.order.quotaPoints) });
      if (s === 'paid') return this.$t('xn.billing.descPaid');
      if (s === 'pending') return this.$t('xn.billing.descPending');
      if (s === 'closed') return this.$t('xn.billing.descClosed');
      if (s === 'refunded') return this.$t('xn.billing.descRefunded');
      return this.$t('xn.billing.descFailed');
    }
  },
  watch: {
    'order.status'(s) {
      // 到账后让外壳刷新余额
      if (s === 'delivered') this.$eventBus.$emit('xn:quota-changed');
    }
  },
  mounted() {
    this.fetchOrder();
  },
  beforeDestroy() {
    clearTimeout(this.guard);
    this.clearPoll();
  },
  methods: {
    formatYuan(cents) {
      if (cents === null || cents === undefined) return '0.00';
      return (cents / 100).toFixed(2);
    },
    formatPoints(points) {
      const unit = this.$t('billing.pointsUnit');
      if (points === null || points === undefined) return '0 ' + unit;
      return points + ' ' + unit;
    },
    orderNoFromQuery() {
      return this.$route.query.out_trade_no || this.$route.query.outTradeNo || this.$route.query.orderNo || '';
    },
    fetchOrder() {
      const orderNo = this.orderNoFromQuery();
      if (!orderNo) {
        this.loading = false;
        return;
      }
      this.loadFailed = false;
      clearTimeout(this.guard);
      this.guard = setTimeout(() => { if (this.loading) { this.loading = false; this.loadFailed = true; } }, NO_REPLY_MS);
      Api.pay.queryOrder(orderNo, (res) => {
        clearTimeout(this.guard);
        this.loading = false;
        if (res && res.code === 0) {
          this.order = res.data;
          if (this.order && (this.order.status === 'pending' || this.order.status === 'paid')) {
            this.startPoll(orderNo);
          }
        } else {
          this.loadFailed = true;
          this.loadError = res && res.msg ? res.msg : '';
          this.$message.error(res && res.msg ? res.msg : this.$t('billing.loadFail'));
        }
      });
    },
    refresh() {
      this.clearPoll();
      this.loading = true;
      this.fetchOrder();
    },
    startPoll(orderNo) {
      this.clearPoll();
      this.pollTimer = setInterval(() => {
        Api.pay.queryOrder(orderNo, (res) => {
          if (res && res.code === 0) {
            this.order = res.data;
            if (this.order && this.order.status !== 'pending' && this.order.status !== 'paid') {
              this.clearPoll();
            }
          }
        });
      }, 3000);
    },
    clearPoll() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer);
        this.pollTimer = null;
      }
    },
    goOrders() {
      this.$router.push('/billing/orders');
    },
    goPackages() {
      this.$router.push('/billing/packages');
    }
  }
};
</script>

<style scoped>
.br-panel { max-width: 640px; }
.br-loading { height: 240px; }
.br-box { padding: 28px 28px 24px; }
.br-status { display: flex; align-items: flex-start; gap: 16px; }
.br-status__icon { display: grid; place-items: center; flex: none; width: 48px; height: 48px; border-radius: 50%; font-size: 24px; }
.status-success .br-status__icon { background: var(--xn-success-soft); color: var(--xn-success); }
.status-processing .br-status__icon { background: var(--xn-lake-soft); color: var(--xn-lake); }
.status-failed .br-status__icon { background: var(--xn-danger-soft); color: var(--xn-danger); }
.br-status__text { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 2px 0 4px; font-size: 20px; font-weight: 600; color: var(--xn-ink); }
.br-status__desc { margin: 0; color: var(--xn-ink-3); }
.br-meta { margin: 24px 0 0; padding-top: 8px; border-top: 1px solid var(--xn-line-2); }
.br-meta div { display: flex; justify-content: space-between; gap: 16px; padding: 10px 0; border-bottom: 1px solid var(--xn-line-2); }
.br-meta dt { color: var(--xn-ink-3); }
.br-meta dd { margin: 0; color: var(--xn-ink); font-weight: 500; text-align: right; word-break: break-all; }
.br-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 24px; }
.br-actions .el-button + .el-button { margin-left: 0; }
</style>
