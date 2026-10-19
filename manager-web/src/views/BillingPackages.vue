<template>
  <div class="billing-page">
    <div class="billing-navigation"><HeaderBar /></div>

    <div class="main-wrapper">
      <div class="billing-container glass-panel">
        <div class="page-header">
          <h2 class="page-title">{{ $t('billing.packagesTitle') }}</h2>
          <p class="page-subtitle">{{ $t('billing.packagesSubtitle') }}</p>
        </div>

        <!-- 当前可用余额 + 立即充值（汇总加载/失败时入口依然可用） -->
        <div class="balance-card">
          <div class="balance-left">
            <div class="balance-label">{{ $t('billing.currentBalance') }}</div>
            <div v-if="summaryLoading" class="balance-pending">
              <i class="el-icon-loading"></i>
              <span>{{ $t('billing.loading') }}</span>
            </div>
            <template v-else-if="summary">
              <div class="balance-number">
                <span class="balance-amount">{{ formatPoints(summary.balancePoints) }}</span>
                <span class="balance-unit">{{ $t('billing.pointsUnit') }}</span>
              </div>
              <el-tag size="mini" :type="balanceTagType" effect="plain">{{ balanceSourceText }}</el-tag>
            </template>
            <div v-else class="balance-pending">
              <span class="balance-amount balance-amount-muted">--</span>
              <el-tag size="mini" type="info" effect="plain">{{ $t('billing.balanceUnavailable') }}</el-tag>
            </div>
          </div>
          <div class="balance-right">
            <el-button type="primary" size="medium" icon="el-icon-plus" @click="goRecharge">
              {{ $t('billing.rechargeNow') }}
            </el-button>
          </div>
        </div>

        <!-- 缓存余额提示：仅在确认读到缓存余额时展示；none（无记录）不算缓存 -->
        <el-alert v-if="summary && summary.balanceSource === 'cache'" class="mb16"
          :title="$t('billing.balanceCacheHint')" type="warning" :closable="false" show-icon />

        <!-- 用量趋势（仅受汇总请求状态影响） -->
        <div class="section-toolbar">
          <span class="section-title">{{ $t('billing.usageTrend') }}</span>
          <el-radio-group v-model="days" size="mini" @change="fetchSummary">
            <el-radio-button :label="7">{{ $t('billing.last7Days') }}</el-radio-button>
            <el-radio-button :label="30">{{ $t('billing.last30Days') }}</el-radio-button>
          </el-radio-group>
        </div>

        <div class="trend-card">
          <div v-if="summaryLoading" class="inline-status">
            <i class="el-icon-loading"></i>
            <span>{{ $t('billing.loading') }}</span>
          </div>
          <div v-else-if="summaryError" class="inline-status">
            <span class="inline-error-text">{{ summaryError }}</span>
            <el-button size="mini" type="primary" plain @click="fetchSummary">{{ $t('billing.retry') }}</el-button>
          </div>
          <el-alert v-else-if="summary && !summary.consumptionAvailable" :title="usageUnavailableText" type="info"
            :closable="false" show-icon />
          <div v-else-if="summary" class="trend-chart">
            <div class="trend-bars">
              <div v-for="d in summary.daily" :key="d.date" class="trend-bar-wrap">
                <el-tooltip :content="trendTooltip(d)" placement="top">
                  <div class="trend-bar" :style="{ height: barHeight(d.usagePoints) }"></div>
                </el-tooltip>
              </div>
            </div>
            <div class="trend-xaxis">
              <span v-for="(d, i) in summary.daily" :key="d.date" class="trend-xlabel">{{ xLabel(d, i) }}</span>
            </div>
          </div>
        </div>

        <!-- 按日汇总账单（仅受汇总请求状态影响） -->
        <div class="section-toolbar">
          <span class="section-title">{{ $t('billing.dailyBills') }}</span>
          <span class="section-note">{{ $t('billing.usageZoneNote') }}</span>
        </div>
        <el-table v-if="summary && !summaryError" :data="summary.daily" style="width: 100%"
          :empty-text="$t('billing.noData')">
          <el-table-column prop="date" :label="$t('billing.date')" min-width="120" />
          <el-table-column :label="$t('billing.rechargeAmount')" min-width="110">
            <template slot-scope="scope">¥{{ formatYuan(scope.row.rechargeAmountCents) }}</template>
          </el-table-column>
          <el-table-column :label="$t('billing.rechargePoints')" min-width="110">
            <template slot-scope="scope">{{ formatPoints(scope.row.rechargePoints) }}</template>
          </el-table-column>
          <el-table-column :label="$t('billing.dailyUsage')" min-width="110">
            <template slot-scope="scope">
              <span v-if="scope.row.usagePoints === null || scope.row.usagePoints === undefined">-</span>
              <span v-else>{{ formatPoints(scope.row.usagePoints) }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="$t('billing.netChange')" min-width="110">
            <template slot-scope="scope">
              <span v-if="scope.row.netChangePoints === null || scope.row.netChangePoints === undefined">-</span>
              <span v-else :class="netChangeClass(scope.row.netChangePoints)">{{ formatSigned(scope.row.netChangePoints) }}</span>
            </template>
          </el-table-column>
        </el-table>
        <div v-else-if="summaryLoading" class="inline-status">
          <i class="el-icon-loading"></i>
          <span>{{ $t('billing.loading') }}</span>
        </div>
        <div v-else class="inline-status">
          <span class="inline-error-text">{{ summaryError || $t('billing.billingLoadFail') }}</span>
          <el-button size="mini" type="primary" plain @click="fetchSummary">{{ $t('billing.retry') }}</el-button>
        </div>

        <HardwareCallBills />

        <!-- 充值套餐 / 充值入口（独立于汇总状态，始终可用） -->
        <div ref="packageSection" class="section-toolbar">
          <span class="section-title">{{ $t('billing.packagesTitle') }}</span>
        </div>

        <div v-if="packagesLoading" class="loading-wrap">
          <i class="el-icon-loading"></i>
          <span>{{ $t('billing.loading') }}</span>
        </div>
        <div v-else-if="packages.length === 0" class="empty-wrap">
          <p>{{ $t('billing.noPackages') }}</p>
        </div>
        <template v-else>
          <div class="package-grid">
            <div v-for="pkg in packages" :key="pkg.id" class="package-card"
              :class="{ 'selected': selectedId === pkg.id }" @click="selectedId = pkg.id">
              <div class="package-name">{{ pkg.name }}</div>
              <div class="package-price">
                <span class="currency">¥</span>
                <span class="amount">{{ formatYuan(pkg.amountCents) }}</span>
              </div>
              <div class="package-quota">{{ formatPoints(pkg.quotaPoints) }} {{ $t('billing.pointsUnit') }}</div>
              <div v-if="pkg.description" class="package-desc">{{ pkg.description }}</div>
              <div class="package-check" v-if="selectedId === pkg.id">
                <i class="el-icon-check"></i>
              </div>
            </div>
          </div>

          <div class="pay-actions">
            <el-button type="primary" size="medium" :disabled="!selectedId || submitting" :loading="submitting"
              @click="submitOrder">
              {{ $t('billing.payWithAlipay') }}
            </el-button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script>
import HeaderBar from '@/components/HeaderBar.vue';
import HardwareCallBills from '@/components/HardwareCallBills.vue';
import Api from '@/apis/api';

export default {
  name: 'BillingPackages',
  components: { HeaderBar, HardwareCallBills },
  data() {
    return {
      days: 7,
      summaryLoading: true,
      summaryError: '',
      summary: null,
      summaryRequestId: 0,
      packagesLoading: true,
      packages: [],
      selectedId: null,
      submitting: false
    };
  },
  computed: {
    maxUsage() {
      if (!this.summary || !this.summary.daily) return 0;
      return this.summary.daily.reduce((max, d) => {
        const v = d.usagePoints === null || d.usagePoints === undefined ? 0 : Number(d.usagePoints);
        return v > max ? v : max;
      }, 0);
    },
    balanceSourceText() {
      const source = this.summary ? this.summary.balanceSource : null;
      if (source === 'hardware_ledger') return '实时账本';
      if (source === 'oneapi') return this.$t('billing.balanceSourceOneapi');
      if (source === 'cache') return this.$t('billing.balanceSourceCache');
      return this.$t('billing.balanceSourceNone');
    },
    balanceTagType() {
      const source = this.summary ? this.summary.balanceSource : null;
      if (source === 'oneapi' || source === 'hardware_ledger') return 'success';
      if (source === 'cache') return 'warning';
      return 'info';
    },
    usageUnavailableText() {
      const reason = this.summary ? this.summary.consumptionUnavailableReason : null;
      if (reason === 'no_binding') return this.$t('billing.usageUnavailableNoBinding');
      if (reason === 'logs_disabled') return this.$t('billing.usageUnavailableDisabled');
      if (reason === 'logs_unreadable') return this.$t('billing.usageUnavailableUnreadable');
      return this.$t('billing.usageUnavailableGeneric');
    }
  },
  mounted() {
    this.fetchSummary();
    this.fetchPackages();
  },
  methods: {
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
    formatSigned(points) {
      if (points === null || points === undefined) return '-';
      const n = Number(points);
      const text = this.formatPoints(Math.abs(n));
      if (n > 0) return '+' + text;
      if (n < 0) return '-' + text;
      return '0';
    },
    netChangeClass(points) {
      const n = Number(points);
      if (n > 0) return 'net-positive';
      if (n < 0) return 'net-negative';
      return '';
    },
    barHeight(v) {
      if (v === null || v === undefined) return '0%';
      const val = Number(v);
      if (!this.maxUsage || this.maxUsage <= 0) return val > 0 ? '5%' : '2%';
      const pct = (val / this.maxUsage) * 100;
      return Math.max(pct, val > 0 ? 5 : 2) + '%';
    },
    xLabel(d, i) {
      if (!this.summary || !this.summary.daily) return '';
      const n = this.summary.daily.length;
      const step = n > 10 ? Math.ceil(n / 6) : 1;
      if (i === 0 || i === n - 1 || i % step === 0) return d.date.slice(5);
      return '';
    },
    trendTooltip(d) {
      return d.date + ' · ' + this.formatPoints(d.usagePoints) + ' ' + this.$t('billing.pointsUnit');
    },
    goRecharge() {
      const el = this.$refs.packageSection;
      if (el && el.scrollIntoView) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
    },
    fetchSummary() {
      // 请求序号：用于丢弃乱序返回的过期响应（快速切换 7/30 天时）
      const seq = ++this.summaryRequestId;
      const requestedDays = this.days;
      this.summaryLoading = true;
      this.summaryError = '';
      // 立即清空旧区间数据，避免加载期间继续展示错误日期范围的账单
      this.summary = null;
      Api.pay.billingSummary(requestedDays, (res) => {
        // 过期请求：不得修改任何页面状态
        if (seq !== this.summaryRequestId) {
          return;
        }
        this.summaryLoading = false;
        if (res && res.code === 0 && res.data) {
          this.summary = res.data;
        } else {
          // 失败时清空，避免把旧数据伪装成最新
          this.summary = null;
          this.summaryError = res && res.msg ? res.msg : this.$t('billing.billingLoadFail');
        }
      });
    },
    fetchPackages() {
      this.packagesLoading = true;
      Api.pay.packages((res) => {
        if (res && res.code === 0) {
          this.packages = res.data || [];
          if (this.packages.length > 0) {
            this.selectedId = this.packages[0].id;
          }
        } else {
          this.packages = [];
          this.$message.error(res && res.msg ? res.msg : this.$t('billing.loadFail'));
        }
        this.packagesLoading = false;
      });
    },
    submitOrder() {
      if (!this.selectedId) {
        this.$message.warning(this.$t('billing.selectPackage'));
        return;
      }
      this.submitting = true;
      Api.pay.createOrder(this.selectedId, 'alipay', (res) => {
        this.submitting = false;
        if (res && res.code === 0) {
          const order = res.data || {};
          if (order.payForm) {
            // 渲染支付宝表单并跳转
            const container = document.createElement('div');
            container.innerHTML = order.payForm;
            document.body.appendChild(container);
            const form = container.querySelector('form');
            if (form) {
              form.submit();
            }
            // 跳转结果页（query 携带订单号）
            this.$router.push({ path: '/billing/result', query: { out_trade_no: order.outTradeNo } });
          } else {
            this.$message.error(this.$t('billing.noPayForm'));
          }
        } else {
          this.$message.error(res && res.msg ? res.msg : this.$t('billing.createFail'));
        }
      });
    }
  }
};
</script>

<style scoped>
.billing-navigation { max-width: 100%; overflow-x: auto; }
@media (max-width: 600px) {
  .billing-page .balance-card { flex-direction: column; align-items: flex-start; gap: 12px; }
  .balance-card .balance-left { min-width: 0; }
  .balance-card .balance-amount { font-size: 28px; white-space: nowrap; }
}
.billing-page {
  min-height: 100vh;
  background: #f5f7fb;
  box-sizing: border-box;
}
.main-wrapper {
  padding: 16px 24px 24px;
}
.billing-container {
  max-width: 1080px;
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
.page-subtitle {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 14px;
}
.loading-wrap,
.empty-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 48px 0;
  color: #64748b;
}
.inline-status {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 28px 0;
  color: #64748b;
  font-size: 14px;
}
.inline-error-text {
  color: #dc2626;
}
.mb16 {
  margin-bottom: 16px;
}

/* 余额卡 */
.balance-card {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 24px 28px;
  border-radius: 16px;
  background: linear-gradient(135deg, #eff6ff 0%, #f5f3ff 100%);
  border: 1px solid #e0e7ff;
  margin-bottom: 20px;
}
.balance-label {
  color: #64748b;
  font-size: 14px;
}
.balance-pending {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 8px;
  color: #64748b;
  font-size: 14px;
}
.balance-amount-muted {
  color: #94a3b8;
  font-size: 32px;
}
.balance-number {
  margin: 6px 0 8px;
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.balance-amount {
  font-size: 40px;
  font-weight: 800;
  color: #3b82f6;
  line-height: 1.1;
  word-break: break-all;
}
.balance-unit {
  font-size: 16px;
  color: #64748b;
  font-weight: 600;
}
.balance-right {
  flex-shrink: 0;
}

/* 区块标题 */
.section-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 28px 0 12px;
}
.section-title {
  font-size: 16px;
  font-weight: 600;
  color: #0f172a;
}
.section-note {
  font-size: 12px;
  color: #94a3b8;
}

/* 趋势图 */
.trend-card {
  padding: 16px 20px;
  border-radius: 12px;
  border: 1px solid #eef0f6;
  background: #fff;
}
.trend-chart {
  width: 100%;
}
.trend-bars {
  display: flex;
  align-items: flex-end;
  gap: 4px;
  height: 140px;
  padding: 0 2px;
}
.trend-bar-wrap {
  flex: 1;
  height: 100%;
  display: flex;
  align-items: flex-end;
  justify-content: center;
  min-width: 0;
}
.trend-bar {
  width: 70%;
  max-width: 26px;
  min-height: 2px;
  border-radius: 4px 4px 0 0;
  background: linear-gradient(180deg, #60a5fa 0%, #3b82f6 100%);
  transition: height 0.3s ease;
}
.trend-xaxis {
  display: flex;
  gap: 4px;
  margin-top: 6px;
  padding: 0 2px;
}
.trend-xlabel {
  flex: 1;
  min-width: 0;
  text-align: center;
  font-size: 11px;
  color: #94a3b8;
  white-space: nowrap;
  overflow: hidden;
}

.net-positive {
  color: #16a34a;
  font-weight: 600;
}
.net-negative {
  color: #dc2626;
  font-weight: 600;
}

/* 套餐 */
.package-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 20px;
}
.package-card {
  position: relative;
  padding: 24px;
  border-radius: 16px;
  background: #fff;
  border: 2px solid #eef0f6;
  cursor: pointer;
  transition: all 0.2s ease;
}
.package-card:hover {
  border-color: #c7d2fe;
  box-shadow: 0 8px 24px rgba(59, 130, 246, 0.12);
}
.package-card.selected {
  border-color: #3b82f6;
  box-shadow: 0 12px 30px rgba(59, 130, 246, 0.2);
}
.package-name {
  font-size: 16px;
  font-weight: 600;
  color: #0f172a;
}
.package-price {
  margin-top: 12px;
  color: #3b82f6;
}
.package-price .currency {
  font-size: 18px;
  font-weight: 600;
}
.package-price .amount {
  font-size: 32px;
  font-weight: 700;
}
.package-quota {
  margin-top: 8px;
  color: #64748b;
  font-size: 13px;
}
.package-desc {
  margin-top: 10px;
  color: #94a3b8;
  font-size: 12px;
}
.package-check {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background: #3b82f6;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
}
.pay-actions {
  margin-top: 28px;
  display: flex;
  justify-content: center;
}
</style>
