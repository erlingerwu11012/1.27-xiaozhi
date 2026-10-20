<template>
  <div class="billing-page">
    <HeaderBar />

    <div class="main-wrapper">
    <div class="billing-container glass-panel">
      <div class="page-header">
        <h2 class="page-title">{{ $t('billing.ordersTitle') }}</h2>
      </div>

      <div class="quota-bar" v-if="quota">
        <span>{{ $t('billing.balance') }}：</span>
        <span class="balance-value">{{ formatPoints(quota.balance) }} {{ $t('billing.pointsUnit') }}</span>
        <el-tag size="mini" :type="balanceTagType" effect="plain" class="balance-tag">{{ balanceSourceText }}</el-tag>
      </div>
      <el-alert v-if="quota && !quota.balanceRealtime" class="mb16" :title="$t('billing.balanceCacheHint')"
        type="warning" :closable="false" show-icon />

      <el-table :data="orders" v-loading="loading" style="width: 100%" :empty-text="$t('billing.noOrders')">
        <el-table-column prop="outTradeNo" :label="$t('billing.orderNo')" min-width="200" />
        <el-table-column prop="packageName" :label="$t('billing.packageName')" min-width="140" />
        <el-table-column :label="$t('billing.amount')" width="120">
          <template slot-scope="scope">¥{{ formatYuan(scope.row.amountCents) }}</template>
        </el-table-column>
        <el-table-column :label="$t('billing.channel')" width="100">
          <template slot-scope="scope">{{ channelText(scope.row.channel) }}</template>
        </el-table-column>
        <el-table-column :label="$t('billing.status')" width="120">
          <template slot-scope="scope">
            <el-tag :type="statusTagType(scope.row.status)" size="small">{{ statusText(scope.row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column :label="$t('billing.createdAt')" width="180">
          <template slot-scope="scope">{{ formatTime(scope.row.createdAt) }}</template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrap" v-if="total > 0">
        <el-pagination background layout="prev, pager, next" :total="total" :page-size="pageSize"
          :current-page.sync="page" @current-change="fetchOrders" />
      </div>
      <h3 style="margin-top:32px">回响现实官方服务费用</h3>
      <el-alert v-if="!memoryAvailable" title="费用暂时无法读取，请稍后刷新" type="info" :closable="false" />
      <el-table :data="memoryBills" v-loading="memoryLoading" style="width:100%" empty-text="暂无记忆服务费用">
        <el-table-column label="时间" min-width="170"><template slot-scope="scope">{{ formatTime(scope.row.createdAt) }}</template></el-table-column>
        <el-table-column label="计费项" min-width="100"><template slot-scope="scope">{{ memoryOperation(scope.row.operation) }}</template></el-table-column>
        <el-table-column label="费用（元）" min-width="130"><template slot-scope="scope">¥{{ formatMemoryAmount(scope.row.amountCny) }}</template></el-table-column>
        <el-table-column label="已扣点数" min-width="100"><template slot-scope="scope">{{ formatPoints(scope.row.chargedPoints) }}</template></el-table-column>
        <el-table-column label="状态" min-width="100"><template slot-scope="scope">{{ memoryState(scope.row.state) }}</template></el-table-column>
      </el-table>
      <div class="pagination-wrap" v-if="memoryTotal>0"><el-pagination background layout="prev, pager, next" :total="memoryTotal" :page-size="10" :current-page.sync="memoryPage" @current-change="fetchMemoryBills" /></div>
    </div>
    </div>
  </div>
</template>

<script>
import HeaderBar from '@/components/HeaderBar.vue';
import Api from '@/apis/api';

export default {
  name: 'BillingOrders',
  components: { HeaderBar },
  data() {
    return {
      loading: false,
      orders: [],
      total: 0,
      page: 1,
      pageSize: 10,
      quota: null,
      memoryBills: [], memoryPage: 1, memoryTotal: 0, memoryAvailable: true, memoryLoading: false
    };
  },
  mounted() {
    this.fetchOrders();
    this.fetchQuota();
    this.fetchMemoryBills();
  },
  computed: {
    balanceSourceText() {
      const source = this.quota ? this.quota.balanceSource : null;
      if (source === 'oneapi') return this.$t('billing.balanceSourceOneapi');
      if (source === 'cache') return this.$t('billing.balanceSourceCache');
      return this.$t('billing.balanceSourceNone');
    },
    balanceTagType() {
      const source = this.quota ? this.quota.balanceSource : null;
      if (source === 'oneapi') return 'success';
      if (source === 'cache') return 'warning';
      return 'info';
    }
  },
  methods: {
    memoryOperation(value) { return ({fact:'事实写入',portrait:'画像抽取',search:'记忆检索',storage:'记忆存储'})[value] || '记忆服务'; },
    memoryState(value) { return ({settled:'已结算',refunded:'已退还',reserved:'处理中',submitted:'处理中',review:'核对中',manual_review:'核对中',pending:'待结算',debt:'待补扣'})[value] || '处理中'; },
    formatMemoryAmount(value) { return Number(value || 0).toFixed(8).replace(/0+$/, '').replace(/\.$/, '.00'); },
    fetchMemoryBills() { this.memoryLoading=true; Api.pay.memoryBills(this.memoryPage,res=>{ this.memoryLoading=false; this.memoryAvailable=!!(res && res.code===0 && res.data && res.data.available); this.memoryBills=this.memoryAvailable ? res.data.list || [] : []; this.memoryTotal=this.memoryAvailable ? res.data.total || 0 : 0; }); },
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
    statusTagType(s) {
      if (s === 'delivered') return 'success';
      if (s === 'paid') return 'warning';
      if (s === 'pending') return 'info';
      return 'danger';
    },
    fetchOrders() {
      this.loading = true;
      Api.pay.orders({ page: this.page, limit: this.pageSize }, (res) => {
        this.loading = false;
        if (res && res.code === 0) {
          const data = res.data || {};
          this.orders = data.list || [];
          this.total = data.total || 0;
        } else {
          this.$message.error(res && res.msg ? res.msg : this.$t('billing.loadFail'));
        }
      });
    },
    fetchQuota() {
      Api.pay.myQuota((res) => {
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
  margin-bottom: 20px;
}
.page-title {
  margin: 0;
  font-size: 24px;
  font-weight: 700;
  color: #1a1a2e;
}
.quota-bar {
  margin-bottom: 16px;
  text-align: right;
  color: #64748b;
  font-size: 14px;
}
.balance-value {
  color: #3b82f6;
  font-weight: 700;
}
.balance-tag {
  margin-left: 8px;
}
.mb16 {
  margin-bottom: 16px;
}
.pagination-wrap {
  margin-top: 20px;
  display: flex;
  justify-content: center;
}
</style>
<style scoped>
@media (max-width: 700px) {
  .main-wrapper { padding: 12px; }
  .billing-container { padding: 16px 12px; min-width: 0; }
  .billing-page ::v-deep .header { min-width: 0; height: auto !important; padding: 0 8px; }
  .billing-page ::v-deep .header-container { flex-wrap: wrap; height: auto; margin: 0; padding: 12px; }
  .billing-page ::v-deep .header-left { min-width: 0; }
  .billing-page ::v-deep .header-right { min-width: 0; flex: 1; }
  .billing-page ::v-deep .header-center { position: static; transform: none; order: 3; width: 100%; overflow-x: auto; gap: 8px; padding-top: 10px; }
}
</style>
