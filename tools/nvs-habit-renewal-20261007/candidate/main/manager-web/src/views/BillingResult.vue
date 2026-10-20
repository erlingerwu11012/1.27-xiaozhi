<template>
  <div class="billing-page">
    <HeaderBar />

    <div class="main-wrapper">
    <div class="billing-container glass-panel">
      <div class="page-header">
        <h2 class="page-title">{{ $t('billing.resultTitle') }}</h2>
      </div>

      <div v-if="loading" class="loading-wrap">
        <i class="el-icon-loading"></i>
        <span>{{ $t('billing.loading') }}</span>
      </div>

      <div v-else-if="!order" class="empty-wrap">
        <p>{{ $t('billing.noOrder') }}</p>
      </div>

      <div v-else class="result-box">
        <div class="status-icon" :class="statusClass">
          <i :class="statusIcon"></i>
        </div>
        <div class="status-text">{{ statusText }}</div>

        <div class="order-meta">
          <div class="meta-row">
            <span class="meta-label">{{ $t('billing.orderNo') }}</span>
            <span class="meta-value">{{ order.outTradeNo }}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">{{ $t('billing.packageName') }}</span>
            <span class="meta-value">{{ order.packageName }}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">{{ $t('billing.amount') }}</span>
            <span class="meta-value">¥{{ formatYuan(order.amountCents) }}</span>
          </div>
          <div class="meta-row">
            <span class="meta-label">{{ $t('billing.quota') }}</span>
            <span class="meta-value">{{ formatPoints(order.quotaPoints) }}</span>
          </div>
        </div>

        <div class="result-actions">
          <el-button type="primary" size="medium" @click="refresh">{{ $t('billing.refresh') }}</el-button>
          <el-button size="medium" @click="goOrders">{{ $t('billing.viewOrders') }}</el-button>
          <el-button size="medium" @click="goPackages">{{ $t('billing.backPackages') }}</el-button>
        </div>
      </div>
    </div>
    </div>
  </div>
</template>

<script>
import HeaderBar from '@/components/HeaderBar.vue';
import Api from '@/apis/api';

export default {
  name: 'BillingResult',
  components: { HeaderBar },
  data() {
    return {
      loading: true,
      order: null,
      pollTimer: null
    };
  },
  computed: {
    statusClass() {
      if (!this.order) return '';
      if (this.order.status === 'delivered') return 'status-success';
      if (this.order.status === 'paid') return 'status-processing';
      if (this.order.status === 'pending') return 'status-processing';
      return 'status-failed';
    },
    statusIcon() {
      if (!this.order) return 'el-icon-question';
      if (this.order.status === 'delivered') return 'el-icon-success';
      if (this.order.status === 'paid' || this.order.status === 'pending') return 'el-icon-loading';
      return 'el-icon-error';
    },
    statusText() {
      if (!this.order) return '';
      if (this.order.status === 'delivered') return this.$t('billing.statusDelivered');
      if (this.order.status === 'paid') return this.$t('billing.statusPaid');
      if (this.order.status === 'pending') return this.$t('billing.statusPending');
      return this.$t('billing.statusFailed');
    }
  },
  mounted() {
    this.fetchOrder();
  },
  beforeDestroy() {
    this.clearPoll();
  },
  methods: {
    formatYuan(cents) {
      if (cents === null || cents === undefined) return '0.00';
      return (cents / 100).toFixed(2);
    },
    formatPoints(points) {
      if (points === null || points === undefined) return '0 点';
      return points + ' 点';
    },
    orderNoFromQuery() {
      return this.$route.query.out_trade_no || this.$route.query.outTradeNo || '';
    },
    fetchOrder() {
      const orderNo = this.orderNoFromQuery();
      if (!orderNo) {
        this.loading = false;
        return;
      }
      Api.pay.queryOrder(orderNo, (res) => {
        this.loading = false;
        if (res && res.code === 0) {
          this.order = res.data;
          if (this.order && (this.order.status === 'pending' || this.order.status === 'paid')) {
            this.startPoll(orderNo);
          }
        } else {
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
.billing-page {
  min-height: 100vh;
  background: #f5f7fb;
  box-sizing: border-box;
}
.main-wrapper {
  padding: 16px 24px 24px;
}
.billing-container {
  max-width: 640px;
  margin: 0 auto;
  padding: 28px 32px;
  border-radius: 12px;
  background: #fff;
  border: none;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
}
.page-header {
  margin-bottom: 24px;
}
.page-title {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  color: #1a1a2e;
}
.loading-wrap, .empty-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 48px 0;
  color: #64748b;
}
.result-box {
  display: flex;
  flex-direction: column;
  align-items: center;
}
.status-icon {
  width: 72px;
  height: 72px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 36px;
  color: #fff;
}
.status-success {
  background: #22c55e;
}
.status-processing {
  background: #3b82f6;
}
.status-failed {
  background: #ef4444;
}
.status-text {
  margin-top: 16px;
  font-size: 18px;
  font-weight: 600;
  color: #0f172a;
}
.order-meta {
  width: 100%;
  margin-top: 24px;
  border-top: 1px solid #eef0f6;
  padding-top: 16px;
}
.meta-row {
  display: flex;
  justify-content: space-between;
  padding: 8px 0;
  font-size: 14px;
}
.meta-label {
  color: #94a3b8;
}
.meta-value {
  color: #0f172a;
  font-weight: 500;
}
.result-actions {
  margin-top: 24px;
  display: flex;
  gap: 12px;
}
</style>
