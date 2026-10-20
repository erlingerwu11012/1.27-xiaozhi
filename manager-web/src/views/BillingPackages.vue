<template>
  <div class="xn-page bp">
    <page-header :title="$t('billing.packagesTitle')" :description="$t('billing.packagesSubtitle')">
      <el-button @click="$router.push('/billing/orders')"><xn-icon name="receipt" /> {{ $t('billing.viewOrders') }}</el-button>
    </page-header>

    <div class="bp-top">
      <!-- 当前余额：加载 / 正常 / 可能不是最新 / 暂不可用 -->
      <section class="xn-panel bp-balance" :class="'is-' + balanceState" aria-live="polite">
        <div class="bp-balance__label">
          <xn-icon name="wallet" />
          <span>{{ $t('billing.currentBalance') }}</span>
          <demo-tag />
        </div>
        <div v-if="balanceState === 'loading'" class="bp-balance__num is-loading" aria-hidden="true"><span class="bp-skel"></span></div>
        <template v-else-if="balanceState === 'unavailable'">
          <div class="bp-balance__unavailable">{{ $t('billing.balanceUnavailable') }}</div>
          <p class="bp-balance__hint">{{ $t('xn.billing.balanceUnavailableHint') }}</p>
        </template>
        <template v-else>
          <div class="bp-balance__num">
            <span class="xn-num">{{ formatPoints(summary.balancePoints) }}</span>
            <span class="bp-balance__unit">{{ $t('billing.pointsUnit') }}</span>
          </div>
          <template v-if="balanceState === 'stale'">
            <span class="xn-tag xn-tag--warning"><i class="dot"></i>{{ $t('billing.balanceSourceCache') }}</span>
            <p class="bp-balance__hint">{{ $t('billing.balanceCacheHint') }}</p>
          </template>
        </template>
        <div class="bp-balance__actions">
          <el-button class="bp-balance__jump" @click="goRecharge"><xn-icon name="plus" /> {{ $t('billing.rechargeNow') }}</el-button>
          <el-button type="text" :disabled="summaryLoading" @click="fetchSummary"><xn-icon name="refresh" /> {{ $t('xn.billing.refreshBalance') }}</el-button>
        </div>
      </section>

      <!-- 充值套餐（独立于汇总状态，始终可用） -->
      <section ref="packageSection" class="xn-panel bp-packages" tabindex="-1">
        <div class="xn-panel__head">
          <h2 class="xn-panel__title">{{ $t('xn.billing.choosePackage') }}</h2>
          <demo-tag :text="$t('xn.billing.demoPackages')" />
        </div>
        <div class="xn-panel__body">
          <div v-if="packagesLoading" class="bp-grid" aria-hidden="true">
            <div v-for="i in 3" :key="i" class="bp-pkg is-skel"><span class="bp-skel w50"></span><span class="bp-skel w70 tall"></span><span class="bp-skel w40"></span></div>
          </div>
          <xn-empty v-else-if="packagesFailed" error @retry="fetchPackages" />
          <xn-empty v-else-if="packages.length === 0" icon="wallet" :title="$t('billing.noPackages')" :description="$t('xn.billing.noPackagesDesc')">
            <el-button @click="fetchPackages"><xn-icon name="refresh" /> {{ $t('xn.common.retry') }}</el-button>
          </xn-empty>
          <template v-else>
            <div class="bp-grid" role="radiogroup" :aria-label="$t('xn.billing.choosePackage')">
              <button v-for="pkg in packages" :key="pkg.id" ref="pkgCard" type="button" role="radio" class="bp-pkg"
                :class="{ 'is-on': selectedId === pkg.id }" :aria-checked="String(selectedId === pkg.id)"
                @click="selectedId = pkg.id">
                <span class="bp-pkg__name">{{ pkg.name }}</span>
                <span class="bp-pkg__price"><span class="bp-pkg__cur">¥</span><span class="xn-num">{{ formatYuan(pkg.amountCents) }}</span></span>
                <span class="bp-pkg__quota">{{ $t('xn.billing.getsPoints', { n: formatPoints(pkg.quotaPoints) }) }}</span>
                <span v-if="pkg.description" class="bp-pkg__desc">{{ pkg.description }}</span>
                <span class="bp-pkg__check" aria-hidden="true"><xn-icon name="check" /></span>
              </button>
            </div>

            <div class="bp-pay">
              <div class="bp-pay__sum">
                <template v-if="selectedPackage">
                  <span>{{ $t('xn.billing.payable') }} <strong class="xn-num">¥{{ formatYuan(selectedPackage.amountCents) }}</strong></span>
                  <span class="xn-muted">{{ $t('xn.billing.toAccount', { n: formatPoints(selectedPackage.quotaPoints) }) }}</span>
                </template>
                <span class="bp-pay__note xn-muted">{{ mock ? $t('xn.billing.mockPayNote') : $t('xn.billing.topupNote') }}</span>
              </div>
              <el-button type="primary" :disabled="!selectedId || submitting" :loading="submitting" @click="submitOrder">
                {{ $t('billing.payWithAlipay') }}
              </el-button>
            </div>
          </template>
        </div>
      </section>
    </div>

    <!-- 用量趋势 + 每日账单（只受汇总请求状态影响） -->
    <section class="xn-panel bp-usage">
      <div class="xn-panel__head">
        <div>
          <h2 class="xn-panel__title">{{ $t('billing.usageTrend') }}</h2>
          <p class="bp-sub xn-muted">{{ $t('billing.usageZoneNote') }}</p>
        </div>
        <el-radio-group v-model="days" size="small" @change="fetchSummary">
          <el-radio-button :label="7">{{ $t('billing.last7Days') }}</el-radio-button>
          <el-radio-button :label="30">{{ $t('billing.last30Days') }}</el-radio-button>
        </el-radio-group>
      </div>
      <div class="xn-panel__body">
        <div v-if="summaryLoading" class="bp-chart is-loading" v-loading="true" :element-loading-text="$t('billing.loading')"></div>
        <xn-empty v-else-if="summaryError" error :description="summaryError" @retry="fetchSummary" />
        <el-alert v-else-if="summary && !summary.consumptionAvailable" :title="usageUnavailableText" type="info" :closable="false" show-icon />
        <div v-else-if="summary" class="bp-chart">
          <div class="bp-chart__meta">
            <span class="xn-muted">{{ $t('xn.billing.totalUsage') }}</span>
            <strong class="xn-num">{{ formatPoints(totalUsage) }}</strong>
            <span class="xn-muted">{{ $t('billing.pointsUnit') }}</span>
            <span class="bp-chart__peak xn-muted">{{ $t('xn.billing.peak', { n: formatPoints(maxUsage) }) }}</span>
          </div>
          <div class="bp-chart__plot" role="img" :aria-label="$t('billing.usageTrend')">
            <span class="bp-chart__grid is-top"></span><span class="bp-chart__grid is-mid"></span>
            <div class="bp-chart__bars">
              <el-tooltip v-for="d in summary.daily" :key="d.date" :content="trendTooltip(d)" placement="top" :open-delay="60">
                <div class="bp-chart__col" tabindex="0">
                  <div class="bp-chart__bar" :style="{ height: barHeight(d.usagePoints) }"></div>
                </div>
              </el-tooltip>
            </div>
          </div>
          <div class="bp-chart__x">
            <span v-for="(d, i) in summary.daily" :key="d.date" class="bp-chart__xl">{{ xLabel(d, i) }}</span>
          </div>
        </div>
      </div>

      <div class="bp-daily">
        <h3 class="bp-daily__title">{{ $t('billing.dailyBills') }}</h3>
        <el-table v-if="summary && !summaryError" :data="dailyRows" :empty-text="$t('billing.noData')" max-height="420">
          <el-table-column prop="date" :label="$t('billing.date')" min-width="120">
            <template slot-scope="scope"><span class="xn-num">{{ scope.row.date }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('billing.rechargeAmount')" min-width="110" align="right">
            <template slot-scope="scope"><span class="xn-num">¥{{ formatYuan(scope.row.rechargeAmountCents) }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('billing.rechargePoints')" min-width="110" align="right">
            <template slot-scope="scope"><span class="xn-num">{{ formatPoints(scope.row.rechargePoints) }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('billing.dailyUsage')" min-width="110" align="right">
            <template slot-scope="scope">
              <span v-if="scope.row.usagePoints === null || scope.row.usagePoints === undefined" class="xn-muted">-</span>
              <span v-else class="xn-num">{{ formatPoints(scope.row.usagePoints) }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="$t('billing.netChange')" min-width="110" align="right">
            <template slot-scope="scope">
              <span v-if="scope.row.netChangePoints === null || scope.row.netChangePoints === undefined" class="xn-muted">-</span>
              <span v-else class="xn-num" :class="netChangeClass(scope.row.netChangePoints)">{{ formatSigned(scope.row.netChangePoints) }}</span>
            </template>
          </el-table-column>
        </el-table>
        <p v-else-if="summaryLoading" class="bp-daily__state xn-muted">{{ $t('billing.loading') }}</p>
        <p v-else class="bp-daily__state xn-muted">{{ $t('xn.billing.dailyUnavailable') }}</p>
      </div>
    </section>

    <HardwareCallBills />

    <!-- 演示付款：只在 mock 构建出现，代替跳转支付宝；不会打开任何外部页面 -->
    <el-dialog v-if="mock" :visible.sync="demoPayVisible" width="480px" append-to-body :close-on-click-modal="false"
      custom-class="bp-demo-pay" @close="onDemoPayClose">
      <span slot="title" class="bp-demo-pay__title">{{ $t('xn.billing.demoPayTitle') }} <demo-tag :text="$t('xn.common.simulated')" /></span>
      <el-alert type="warning" :closable="false" show-icon :title="$t('xn.billing.demoPayAlert')" />
      <dl v-if="demoOrder" class="bp-kv">
        <div><dt>{{ $t('billing.orderNo') }}</dt><dd class="xn-num">{{ demoOrder.outTradeNo }}</dd></div>
        <div><dt>{{ $t('billing.packageName') }}</dt><dd>{{ demoOrder.packageName }}</dd></div>
        <div><dt>{{ $t('billing.amount') }}</dt><dd class="xn-num">¥{{ formatYuan(demoOrder.amountCents) }}</dd></div>
        <div><dt>{{ $t('billing.rechargePoints') }}</dt><dd class="xn-num">{{ formatPoints(demoOrder.quotaPoints) }} {{ $t('billing.pointsUnit') }}</dd></div>
      </dl>
      <span slot="footer" class="bp-demo-pay__foot">
        <el-button @click="demoPayVisible = false">{{ $t('xn.common.cancel') }}</el-button>
        <span class="xn-toolbar__grow"></span>
        <el-button type="danger" plain @click="finishDemoPay('fail')">{{ $t('xn.billing.demoPayFail') }}</el-button>
        <el-button type="primary" @click="finishDemoPay('success')">{{ $t('xn.billing.demoPaySuccess') }}</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import HardwareCallBills from '@/components/HardwareCallBills.vue';
import Api from '@/apis/api';
import { isMockMode } from '@/mock/config';

// 构建期常量：real 构建不包含演示付款逻辑
const demoPay = process.env.VUE_APP_DATA_MODE !== 'real' ? require('@/mock/handlers/pay').simulatePayment : null;

export default {
  name: 'BillingPackages',
  components: { HardwareCallBills },
  data() {
    return {
      days: 7,
      summaryLoading: true,
      summaryError: '',
      summary: null,
      summaryRequestId: 0,
      packagesLoading: true,
      packagesFailed: false,
      packages: [],
      selectedId: null,
      submitting: false,
      mock: isMockMode(),
      demoPayVisible: false,
      demoOrder: null,
      demoPayDone: false,
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
    totalUsage() {
      if (!this.summary || !this.summary.daily) return 0;
      return this.summary.daily.reduce((n, d) => n + (Number(d.usagePoints) || 0), 0);
    },
    /** 表格按日期倒序，最近的在上面；图表保持时间正序 */
    dailyRows() {
      return this.summary && this.summary.daily ? this.summary.daily.slice().reverse() : [];
    },
    selectedPackage() {
      return this.packages.find((p) => p.id === this.selectedId) || null;
    },
    /**
     * 余额状态（不在界面上显示余额来源名称）：
     * 读取失败 / balancePoints 为空 / 来源为空或 none → 暂不可用；
     * 来源 cache 或 balanceRealtime === false → 可能不是最新；其余（oneapi、hardware_ledger）→ 正常。
     */
    balanceState() {
      if (this.summaryLoading) return 'loading';
      const s = this.summary;
      if (!s || s.balancePoints === null || s.balancePoints === undefined) return 'unavailable';
      if (!s.balanceSource || s.balanceSource === 'none') return 'unavailable';
      if (s.balanceSource === 'cache' || s.balanceRealtime === false) return 'stale';
      return 'ok';
    },
    usageUnavailableText() {
      const reason = this.summary ? this.summary.consumptionUnavailableReason : null;
      if (reason === 'no_binding') return this.$t('billing.usageUnavailableNoBinding');
      if (reason === 'logs_disabled') return this.$t('billing.usageUnavailableDisabled');
      if (reason === 'logs_unreadable') return this.$t('billing.usageUnavailableUnreadable');
      return this.$t('billing.usageUnavailableGeneric');
    },
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
      return this.$t('xn.billing.trendTip', { date: d.date, n: this.formatPoints(d.usagePoints) });
    },
    goRecharge() {
      const el = this.$refs.packageSection;
      if (el && el.scrollIntoView) {
        el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      }
      const cards = this.$refs.pkgCard || [];
      const idx = this.packages.findIndex((p) => p.id === this.selectedId);
      if (cards[idx] && cards[idx].focus) cards[idx].focus({ preventScroll: true });
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
      this.packagesFailed = false;
      Api.pay.packages((res) => {
        if (res && res.code === 0) {
          this.packages = res.data || [];
          if (this.packages.length > 0 && !this.packages.some((p) => p.id === this.selectedId)) {
            this.selectedId = this.packages[0].id;
          }
        } else {
          this.packages = [];
          this.packagesFailed = true;
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
          if (demoPay) {
            // 演示模式：不渲染支付宝表单、不打开任何外部地址，在页面内模拟付款结果
            this.demoOrder = order;
            this.demoPayDone = false;
            this.demoPayVisible = true;
            return;
          }
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
    },
    /** 演示付款结果：只更新本机演示订单，然后进入结果页（与真实流程的跳转一致） */
    finishDemoPay(result) {
      if (!this.demoOrder || !demoPay) return;
      demoPay(this.demoOrder.outTradeNo, result);
      this.demoPayDone = true;
      this.demoPayVisible = false;
      this.$router.push({ path: '/billing/result', query: { out_trade_no: this.demoOrder.outTradeNo } });
    },
    onDemoPayClose() {
      if (!this.demoPayDone && this.demoOrder) {
        this.$message.info(this.$t('xn.billing.demoPayCancelled'));
      }
    },
  },
};
</script>

<style scoped>
.bp-top { display: grid; grid-template-columns: minmax(260px, 320px) minmax(0, 1fr); gap: 16px; align-items: start; margin-bottom: 16px; }
.bp-top .xn-panel + .xn-panel { margin-top: 0; }

/* 余额 */
.bp-balance { padding: 20px; }
.bp-balance__label { display: flex; align-items: center; gap: 8px; color: var(--xn-ink-3); font-size: 14px; }
.bp-balance__label .xn-icon { font-size: 18px; }
.bp-balance__num { display: flex; align-items: baseline; gap: 6px; margin: 14px 0 10px; font-size: 36px; font-weight: 600; line-height: 1.1; color: var(--xn-ink); word-break: break-all; }
.bp-balance__num.is-loading { height: 40px; }
.bp-balance__unit { font-size: 15px; font-weight: 500; color: var(--xn-ink-3); }
.bp-balance__unavailable { margin: 14px 0 6px; font-size: 20px; font-weight: 600; color: var(--xn-warning); }
.bp-balance__hint { margin: 8px 0 0; font-size: 13px; line-height: 1.6; color: var(--xn-ink-3); }
.bp-balance__actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--xn-line-2); }
.bp-balance__actions .el-button + .el-button { margin-left: 0; }

.bp-skel { display: block; height: 14px; width: 60%; border-radius: 6px; background: var(--xn-mist); }
.bp-balance .bp-skel { height: 36px; width: 70%; }
.bp-skel.w40 { width: 40%; } .bp-skel.w50 { width: 50%; } .bp-skel.w70 { width: 70%; }
.bp-skel.tall { height: 28px; margin: 14px 0; }

/* 套餐 */
.bp-packages:focus { outline: none; }
.bp-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 12px; }
.bp-pkg {
  position: relative; display: flex; flex-direction: column; align-items: flex-start; gap: 4px; min-width: 0;
  padding: 16px 16px 14px; border: 1px solid var(--xn-line); border-radius: var(--xn-r-lg); background: #fff;
  font: inherit; color: var(--xn-ink); text-align: left; cursor: pointer; transition: border-color 0.15s ease, background-color 0.15s ease;
}
.bp-pkg:hover { border-color: #AEBBC8; }
.bp-pkg.is-on { border-color: var(--xn-lake); background: var(--xn-lake-soft); box-shadow: inset 0 0 0 1px var(--xn-lake); }
.bp-pkg.is-skel { cursor: default; }
.bp-pkg__name { font-size: 15px; font-weight: 600; padding-right: 26px; }
.bp-pkg__price { margin-top: 6px; font-size: 28px; font-weight: 600; line-height: 1.2; }
.bp-pkg__cur { margin-right: 2px; font-size: 16px; font-weight: 500; }
.bp-pkg__quota { font-size: 14px; color: var(--xn-ink-2); }
.bp-pkg__desc { margin-top: 4px; font-size: 13px; color: var(--xn-ink-3); }
.bp-pkg__check { position: absolute; top: 14px; right: 14px; display: none; place-items: center; width: 22px; height: 22px; border-radius: 50%; background: var(--xn-lake); color: #fff; font-size: 14px; }
.bp-pkg.is-on .bp-pkg__check { display: grid; }

.bp-pay { display: flex; align-items: center; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-top: 18px; padding-top: 16px; border-top: 1px solid var(--xn-line-2); }
.bp-pay__sum { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.bp-pay__sum strong { font-size: 18px; }
.bp-pay__note { font-size: 13px; }

/* 用量 */
.bp-sub { margin: 2px 0 0; font-size: 13px; }
.bp-chart.is-loading { height: 200px; }
.bp-chart__meta { display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap; margin-bottom: 12px; }
.bp-chart__meta strong { font-size: 20px; font-weight: 600; }
.bp-chart__peak { margin-left: auto; font-size: 13px; }
.bp-chart__plot { position: relative; height: 160px; border-bottom: 1px solid var(--xn-line); }
.bp-chart__grid { position: absolute; left: 0; right: 0; height: 0; border-top: 1px dashed var(--xn-line-2); }
.bp-chart__grid.is-top { top: 0; }
.bp-chart__grid.is-mid { top: 50%; }
.bp-chart__bars { position: relative; display: flex; align-items: flex-end; gap: 2px; height: 100%; }
.bp-chart__col { flex: 1; min-width: 0; height: 100%; display: flex; align-items: flex-end; justify-content: center; border-radius: 4px 4px 0 0; }
.bp-chart__col:hover, .bp-chart__col:focus-visible { background: var(--xn-mist-2); }
.bp-chart__bar { width: 64%; max-width: 28px; min-height: 2px; border-radius: 4px 4px 0 0; background: var(--xn-lake); }
.bp-chart__col:hover .bp-chart__bar { background: var(--xn-lake-ink); }
.bp-chart__x { display: flex; gap: 2px; margin-top: 6px; }
.bp-chart__xl { flex: 1; min-width: 0; overflow: visible; text-align: center; font-size: 12px; color: var(--xn-ink-3); white-space: nowrap; }

.bp-daily { padding: 0 20px 16px; }
.bp-daily__title { margin: 4px 0 8px; font-size: 14px; font-weight: 600; color: var(--xn-ink); }
.bp-daily__state { margin: 0; padding: 24px 0; text-align: center; }
.net-positive { color: var(--xn-success); font-weight: 600; }
.net-negative { color: var(--xn-danger); font-weight: 600; }

/* 演示付款 */
.bp-demo-pay__title { display: inline-flex; align-items: center; gap: 8px; font-size: 18px; font-weight: 600; color: var(--xn-ink); }
.bp-kv { margin: 16px 0 4px; }
.bp-kv div { display: flex; justify-content: space-between; gap: 16px; padding: 9px 0; border-bottom: 1px solid var(--xn-line-2); }
.bp-kv div:last-child { border-bottom: 0; }
.bp-kv dt { color: var(--xn-ink-3); }
.bp-kv dd { margin: 0; color: var(--xn-ink); font-weight: 500; text-align: right; word-break: break-all; }
.bp-demo-pay__foot { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.bp-demo-pay__foot .el-button + .el-button { margin-left: 0; }

@media (max-width: 1100px) {
  .bp-top { grid-template-columns: 1fr; }
}
</style>
