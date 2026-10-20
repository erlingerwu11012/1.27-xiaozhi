<template>
  <section v-if="available || error" class="xn-panel hcb">
    <div class="xn-panel__head">
      <div>
        <h2 class="xn-panel__title">{{ $t('xn.billing.callsTitle') }}</h2>
        <p class="hcb-sub xn-muted">{{ $t('xn.billing.callsDesc') }}</p>
      </div>
      <el-button type="text" :loading="loading" @click="load"><xn-icon v-if="!loading" name="refresh" /> {{ $t('xn.billing.refresh') }}</el-button>
    </div>
    <xn-empty v-if="error" error :description="error" @retry="load" />
    <template v-else>
      <el-table :data="rows" v-loading="loading" row-key="id" class="hcb-table">
        <el-table-column type="expand">
          <template slot-scope="scope">
            <dl class="hcb-detail">
              <div><dt>{{ $t('xn.billing.inputTokens') }}</dt><dd class="xn-num">{{ known(scope.row.inputTokens) }}</dd></div>
              <div><dt>{{ $t('xn.billing.outputTokens') }}</dt><dd class="xn-num">{{ known(scope.row.outputTokens) }}</dd></div>
              <div><dt>{{ $t('xn.billing.cachedTokens') }}</dt><dd class="xn-num">{{ known(scope.row.cachedTokens) }}</dd></div>
              <div><dt>{{ $t('xn.billing.otherUnits') }}</dt><dd class="xn-num">{{ scope.row.units == null ? '—' : scope.row.units + ' ' + unitLabel(scope.row.unit) }}</dd></div>
              <div><dt>{{ $t('xn.billing.legacyPoints') }}</dt><dd class="xn-num">{{ amount(scope.row.legacyPoints) }}</dd></div>
              <div><dt>{{ $t('xn.billing.reservedPoints') }}</dt><dd class="xn-num">{{ amount(scope.row.reservedPoints) }}</dd></div>
              <div class="is-wide"><dt>{{ $t('xn.billing.callId') }}</dt><dd class="xn-num">{{ scope.row.id }}</dd></div>
            </dl>
          </template>
        </el-table-column>
        <el-table-column :label="$t('xn.billing.colTime')" min-width="165">
          <template slot-scope="scope"><span class="xn-num">{{ date(scope.row.createdAt) }}</span></template>
        </el-table-column>
        <el-table-column :label="$t('xn.billing.colFeature')" min-width="95">
          <template slot-scope="scope">{{ operationLabel(scope.row.operation) }}</template>
        </el-table-column>
        <el-table-column prop="model" :label="$t('xn.billing.colModel')" min-width="160" show-overflow-tooltip />
        <el-table-column :label="$t('xn.billing.colPoints')" min-width="100" align="right">
          <template slot-scope="scope"><span class="xn-num">{{ amount(scope.row.points) }}</span></template>
        </el-table-column>
        <el-table-column :label="$t('xn.billing.colPaidAmount')" min-width="130" align="right">
          <template slot-scope="scope"><span class="xn-num">{{ scope.row.paidAmountCny == null ? '—' : '¥' + amount(scope.row.paidAmountCny) }}</span></template>
        </el-table-column>
        <el-table-column :label="$t('xn.billing.colState')" min-width="105">
          <template slot-scope="scope"><span class="xn-tag" :class="stateClass(scope.row.state)">{{ stateLabel(scope.row.state) }}</span></template>
        </el-table-column>
        <template slot="empty">
          <xn-empty icon="receipt" :title="$t('xn.billing.callsEmpty')" :description="$t('xn.billing.callsEmptyDesc')" />
        </template>
      </el-table>
      <el-pagination v-if="total > pageSize" class="hcb-pagination" background layout="total, prev, pager, next" :total="total"
        :page-size="pageSize" :current-page="page" @current-change="changePage" />
    </template>
  </section>
</template>

<script>
import Api from '@/apis/api';

export default {
  name: 'HardwareCallBills',
  data() { return { available: false, loading: false, error: '', rows: [], total: 0, page: 1, pageSize: 20, sequence: 0 }; },
  mounted() { this.load(); },
  beforeDestroy() { this.sequence++; },
  methods: {
    load() {
      const seq = ++this.sequence;
      this.loading = true;
      this.error = '';
      this.rows = [];
      Api.pay.hardwareCalls(this.page, this.pageSize, res => {
        if (seq !== this.sequence) return;
        this.loading = false;
        if (!res || res.code !== 0) { this.error = (res && res.msg) || this.$t('xn.billing.callsLoadFail'); return; }
        const data = res.data || {};
        this.available = data.available === true;
        this.rows = Array.isArray(data.list) ? data.list : [];
        this.total = Number(data.total) || 0;
      });
    },
    changePage(page) { this.page = page; this.load(); },
    known(value) { return value == null ? this.$t('xn.billing.unknown') : value; },
    amount(value) {
      if (value == null) return '—';
      const n = Number(value);
      if (!Number.isFinite(n)) return this.$t('xn.billing.unknown');
      if (n > 0 && n < 0.000001) return '<0.000001';
      return n.toFixed(6).replace(/\.?0+$/, '') || '0';
    },
    date(seconds) { return seconds ? new Date(Number(seconds) * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '—'; },
    unitLabel(unit) {
      const key = ({ weighted_character: 'unitChar', audio_second: 'unitSecond', official_units: 'unitOfficial' })[unit];
      return key ? this.$t('xn.billing.' + key) : unit;
    },
    stateLabel(state) {
      const key = ({ settled: 'stSettled', pending: 'stPending', outstanding: 'stOutstanding', reserved: 'stReserved', refunded: 'stRefunded', cancelled: 'stCancelled' })[state];
      return key ? this.$t('xn.billing.' + key) : state;
    },
    stateClass(state) {
      if (state === 'settled') return 'xn-tag--success';
      if (state === 'outstanding') return 'xn-tag--warning';
      if (state === 'pending' || state === 'reserved') return 'xn-tag--lake';
      return 'xn-tag--muted';
    },
    operationLabel(op) {
      const key = ({ llm: 'opLlm', summary: 'opSummary', habit: 'opHabit', vision: 'opVision', asr: 'opAsr', tts: 'opTts', fact_add: 'opFact', portrait_add: 'opPortrait', search: 'opSearch', storage_item_hour: 'opStorage' })[op];
      return key ? this.$t('xn.billing.' + key) : op;
    },
  },
};
</script>

<style scoped>
.hcb-sub { margin: 2px 0 0; font-size: 13px; }
.hcb-table { border-radius: 0 0 var(--xn-r-lg) var(--xn-r-lg); }
.hcb-detail { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 8px 24px; margin: 0; padding: 4px 8px; }
.hcb-detail div { display: flex; justify-content: space-between; gap: 12px; padding: 6px 0; border-bottom: 1px dashed var(--xn-line-2); font-size: 13px; }
.hcb-detail .is-wide { grid-column: 1 / -1; }
.hcb-detail dt { color: var(--xn-ink-3); }
.hcb-detail dd { margin: 0; color: var(--xn-ink); word-break: break-all; text-align: right; }
.hcb-pagination { padding: 14px 20px; text-align: right; }
</style>
