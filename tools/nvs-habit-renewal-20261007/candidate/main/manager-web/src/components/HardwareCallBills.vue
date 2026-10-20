<template>
  <section v-if="available || error" class="hardware-bills">
    <div class="section-toolbar">
      <span class="section-title">调用明细</span>
      <el-button type="text" icon="el-icon-refresh" :loading="loading" @click="load">刷新</el-button>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <el-table v-else :data="rows" v-loading="loading" empty-text="暂无调用账单" style="width:100%">
      <el-table-column type="expand">
        <template slot-scope="scope">
          <el-descriptions :column="2" size="small" border>
            <el-descriptions-item label="输入 token">{{ known(scope.row.inputTokens) }}</el-descriptions-item>
            <el-descriptions-item label="输出 token">{{ known(scope.row.outputTokens) }}</el-descriptions-item>
            <el-descriptions-item label="缓存命中 token">{{ known(scope.row.cachedTokens) }}</el-descriptions-item>
            <el-descriptions-item label="其他用量">{{ scope.row.units == null ? '—' : scope.row.units + ' ' + unitLabel(scope.row.unit) }}</el-descriptions-item>
            <el-descriptions-item label="旧余额扣点">{{ amount(scope.row.legacyPoints) }}</el-descriptions-item>
            <el-descriptions-item label="预留点数">{{ amount(scope.row.reservedPoints) }}</el-descriptions-item>
            <el-descriptions-item label="调用编号" :span="2">{{ scope.row.id }}</el-descriptions-item>
          </el-descriptions>
        </template>
      </el-table-column>
      <el-table-column label="时间" min-width="165">
        <template slot-scope="scope">{{ date(scope.row.createdAt) }}</template>
      </el-table-column>
      <el-table-column label="功能" min-width="95">
        <template slot-scope="scope">{{ operationLabel(scope.row.operation) }}</template>
      </el-table-column>
      <el-table-column prop="model" label="模型" min-width="160" />
      <el-table-column label="扣点" min-width="100">
        <template slot-scope="scope">{{ amount(scope.row.points) }}</template>
      </el-table-column>
      <el-table-column label="新付费余额费用" min-width="130">
        <template slot-scope="scope">{{ scope.row.paidAmountCny == null ? '—' : '¥' + amount(scope.row.paidAmountCny) }}</template>
      </el-table-column>
      <el-table-column label="状态" min-width="105">
        <template slot-scope="scope"><el-tag size="mini" :type="scope.row.state === 'settled' ? 'success' : 'info'">{{ stateLabel(scope.row.state) }}</el-tag></template>
      </el-table-column>
    </el-table>
    <el-pagination v-if="total > pageSize" class="bill-pagination" layout="prev, pager, next" :total="total"
      :page-size="pageSize" :current-page="page" @current-change="changePage" />
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
        if (!res || res.code !== 0) { this.error = (res && res.msg) || '调用账单读取失败'; return; }
        const data = res.data || {};
        this.available = data.available === true;
        this.rows = Array.isArray(data.list) ? data.list : [];
        this.total = Number(data.total) || 0;
      });
    },
    changePage(page) { this.page = page; this.load(); },
    known(value) { return value == null ? '未知' : value; },
    amount(value) {
      if (value == null) return '—';
      const n = Number(value);
      if (!Number.isFinite(n)) return '未知';
      if (n > 0 && n < 0.000001) return '<0.000001';
      return n.toFixed(6).replace(/\.?0+$/, '') || '0';
    },
    date(seconds) { return seconds ? new Date(Number(seconds) * 1000).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false }) : '—'; },
    unitLabel(unit) { return ({ weighted_character: '计费字符', audio_second: '秒', official_units: '官方计量单位' })[unit] || unit; },
    stateLabel(state) { return ({ settled: '已结算', pending: '待核对', outstanding: '待补缴', reserved: '已预留', refunded: '已退款', cancelled: '已释放' })[state] || state; },
    operationLabel(op) { return ({ llm: '对话', summary: '压缩摘要', habit: '习惯分析', vision: '视觉理解', asr: '语音识别', tts: '语音合成', fact_add: '事实写入', portrait_add: '画像抽取', search: '记忆检索', storage_item_hour: '记忆存储' })[op] || op; }
  }
};
</script>

<style scoped>
.hardware-bills { margin-top: 24px; }
.section-toolbar { display:flex; align-items:center; justify-content:space-between; margin:18px 0 12px; }
.section-title { font-size:16px; font-weight:600; }
.bill-pagination { margin-top:16px; text-align:right; }
</style>
