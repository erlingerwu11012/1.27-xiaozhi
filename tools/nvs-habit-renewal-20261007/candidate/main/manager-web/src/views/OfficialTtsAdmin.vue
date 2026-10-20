<template>
  <div class="welcome">
    <HeaderBar />
    <div class="operation-bar">
      <h2 class="page-title">官方 TTS 管理</h2>
    </div>
    <div class="main-wrapper">
      <el-alert
        title="客户售价单位：CNY/计量单位，由网关换算为点数。成本价不得当作售价。已发布版本不可修改，改价必须新建草稿。"
        type="warning"
        show-icon
        :closable="false"
        style="margin-bottom: 12px"
      />
      <el-card shadow="never" style="margin-bottom: 16px">
        <p>增强开关：{{ overview.enhancedFlag }}　灰度用户：{{ overview.allowUsers || '（空）' }}</p>
        <p>音色数 {{ overview.voices }}　任务数 {{ overview.jobs }}　未确定账本 {{ overview.uncertainLedgers }}</p>
        <p class="hint">{{ overview.priceUnitHintSale }}</p>
        <p class="hint">{{ overview.priceUnitHintCost }}</p>
      </el-card>
      <el-card shadow="never" style="margin-bottom: 16px">
        <h3>价格版本</h3>
        <el-table :data="overview.prices || []">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column prop="priceKind" label="种类" width="120" />
          <el-table-column prop="operation" label="操作" width="110" />
          <el-table-column prop="version" label="版本" />
          <el-table-column prop="unit" label="单位" width="140" />
          <el-table-column prop="amount" label="金额(CNY/单位)" width="140" />
          <el-table-column prop="status" label="库状态" width="150" />
          <el-table-column prop="lifecycleStatus" label="生命周期" width="170" />
          <el-table-column label="操作" width="360">
            <template slot-scope="scope">
              <el-button type="text" :disabled="!canEditDraft(scope.row)" @click="editDraft(scope.row)">编辑草稿</el-button>
              <el-button type="text" :disabled="scope.row.priceKind !== 'sale_points'" @click="draftFrom(scope.row)">基于此新建草稿</el-button>
              <el-button type="text" :disabled="!canPublish(scope.row)" @click="publishPrice(scope.row)">发布生效</el-button>
              <el-button type="text" @click="syncPrice(scope.row)">同步网关</el-button>
            </template>
          </el-table-column>
        </el-table>
      </el-card>
      <el-card shadow="never">
        <h3>人工备注（不结算）</h3>
        <p class="hint">只写审计，不改变账单状态、余额或冻结额。</p>
        <el-input v-model="noteJobId" placeholder="任务 ID" style="width: 140px" />
        <el-input v-model="noteReason" placeholder="备注理由" style="width: 240px; margin: 0 8px" />
        <el-input v-model="noteEvidence" placeholder="依据" style="width: 200px; margin-right: 8px" />
        <el-button @click="doNote">添加备注</el-button>
        <h3 style="margin-top: 24px">人工结算 / 释放冻结</h3>
        <p class="hint">最终金额是累计费用，不是本次增量。默认留空。已确认消费不得降到其下。</p>
        <el-input v-model="settleJobId" placeholder="任务 ID" data-testid="official-tts-settle-job" style="width: 140px" />
        <el-button data-testid="official-tts-load-ledger" @click="loadLedger">读取账单</el-button>
        <div v-if="ledger" class="ledger" data-testid="official-tts-ledger">
          <p>任务 {{ ledger.jobId }}　账单 {{ ledger.billId }}　归属用户 {{ ledger.userId }}</p>
          <p>当前状态 {{ ledger.state || ledger.jobStatus }}　已确认扣费 {{ ledger.charged }}　当前冻结 {{ ledger.held }}</p>
          <p>用户额度 {{ ledger.userQuota }}　已用 {{ ledger.userUsedQuota }}　令牌剩余 {{ ledger.tokenRemainQuota }}</p>
          <el-input v-model="finalTotal" placeholder="最终累计费用（留空拒绝）" data-testid="official-tts-final-total" style="width: 240px" />
          <el-checkbox v-model="confirmZero" data-testid="official-tts-confirm-zero">确认将最终累计费用设为 0（全额释放，须无已确认消费）</el-checkbox>
          <el-input v-model="settleReason" placeholder="处理理由" data-testid="official-tts-settle-reason" style="width: 240px; margin: 8px" />
          <el-input v-model="settleEvidence" placeholder="证据" data-testid="official-tts-settle-evidence" style="width: 240px" />
          <p v-if="previewText" data-testid="official-tts-settle-preview">{{ previewText }}</p>
          <el-button type="danger" data-testid="official-tts-settle-submit" @click="doSettle">提交结算（二次确认）</el-button>
        </div>
      </el-card>
    </div>
  </div>
</template>

<script>
import HeaderBar from "@/components/HeaderBar.vue";
import officialTts from "@/apis/module/officialTts";

export default {
  name: "OfficialTtsAdmin",
  components: { HeaderBar },
  data() {
    return {
      overview: {},
      noteJobId: "",
      noteReason: "",
      noteEvidence: "",
      settleJobId: "",
      ledger: null,
      finalTotal: "",
      confirmZero: false,
      settleReason: "",
      settleEvidence: "",
      lastSettleOpId: "",
      lastSettleSig: "",
    };
  },
  computed: {
    previewText() {
      if (!this.ledger || this.finalTotal === "" || this.finalTotal === null) {
        return "最终累计费用未填写，前后端都会拒绝。";
      }
      const finalTotal = Number(this.finalTotal);
      if (Number.isNaN(finalTotal)) {
        return "最终累计费用必须是数字。";
      }
      const charged = Number(this.ledger.charged || 0);
      const held = Number(this.ledger.held || 0);
      if (finalTotal < charged) {
        return "不得把最终金额降到已确认扣费以下。补偿退款须走独立账务流程。";
      }
      const add = finalTotal - charged;
      const release = held - add;
      return `最终累计费用 ${finalTotal}（不是增量）。预计追加扣费 ${add}，预计释放冻结 ${release}。`;
    },
  },
  created() {
    this.reload();
  },
  methods: {
    reload() {
      officialTts.adminOverview((res) => {
        this.overview = (res.data && res.data.data) || {};
      });
    },
    canEditDraft(row) {
      return row.priceKind === "sale_points" && row.status === "draft";
    },
    canPublish(row) {
      return row.priceKind === "sale_points" && (row.status === "draft" || row.status === "publish_ack_pending" || row.status === "publish_failed");
    },
    editDraft(row) {
      this.$prompt("金额（CNY/计量单位）", "编辑草稿，不改变当前生效价").then(({ value }) => {
        officialTts.updatePrice({
          id: row.id,
          priceKind: "sale_points",
          operation: row.operation,
          unit: row.unit,
          amount: value === "" ? null : Number(value),
        }, () => {
          this.$message.success("已保存草稿，当前生效价未变");
          this.reload();
        }, () => this.$message.error("保存草稿失败"));
      }).catch(() => {});
    },
    draftFrom(row) {
      officialTts.draftFromPublished(row.id, () => {
        this.$message.success("已创建新版本草稿，原已发布版本仍生效");
        this.reload();
      }, () => this.$message.error("新建草稿失败"));
    },
    publishPrice(row) {
      this.$prompt("发布理由", "发布到网关并等待 ack").then(({ value }) => {
        officialTts.publishPrice({ id: row.id, reason: value || "admin_publish" }, () => {
          this.$message.success("网关已确认，该版本已生效");
          this.reload();
        }, () => {
          this.$message.error("发布失败或响应丢失，仍使用原生效版本，可点同步网关");
        });
      }).catch(() => {});
    },
    syncPrice(row) {
      officialTts.syncPublished(row.id, () => {
        this.$message.success("已按网关权威状态同步");
        this.reload();
      }, () => this.$message.error("同步失败"));
    },
    doNote() {
      if (!this.noteJobId || !this.noteReason) {
        this.$message.error("任务 ID 和理由必填");
        return;
      }
      const op = (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID() : ("note-" + Date.now());
      officialTts.addNote(this.noteJobId, op, this.noteReason, this.noteEvidence || "console", () => {
        this.$message.success("已添加备注，未结算、未退款、未改冻结");
        this.reload();
      }, () => this.$message.error("添加备注失败"));
    },
    loadLedger() {
      if (!this.settleJobId) {
        this.$message.error("请填写任务 ID");
        return;
      }
      this.finalTotal = "";
      this.confirmZero = false;
      officialTts.jobLedger(this.settleJobId, (res) => {
        this.ledger = (res.data && res.data.data) || {};
      }, () => this.$message.error("读取账单失败"));
    },
    doSettle() {
      if (!this.ledger) {
        this.$message.error("请先读取账单");
        return;
      }
      if (this.finalTotal === "" || this.finalTotal === null) {
        this.$message.error("最终累计费用未填写，已拒绝");
        return;
      }
      const finalTotal = Number(this.finalTotal);
      if (Number.isNaN(finalTotal)) {
        this.$message.error("最终累计费用必须是数字");
        return;
      }
      if (finalTotal === 0 && !this.confirmZero) {
        this.$message.error("零费用结算必须勾选确认");
        return;
      }
      const charged = Number(this.ledger.charged || 0);
      if (finalTotal < charged) {
        this.$message.error("不得降到已确认扣费以下");
        return;
      }
      this.$confirm(this.previewText + " 确认提交？", "二次确认人工结算", {
        type: "warning",
        customClass: "official-tts-settle-confirm",
        confirmButtonText: "确定",
        cancelButtonText: "取消",
      }).then(() => {
        const sig = [this.settleJobId, String(finalTotal), String(this.confirmZero)].join(":");
        if (!this.lastSettleOpId || this.lastSettleSig !== sig) {
          this.lastSettleOpId = (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID() : ("settle-" + Date.now());
          this.lastSettleSig = sig;
        }
        const op = this.lastSettleOpId;
        const body = {
          jobId: Number(this.settleJobId),
          finalTotal,
          confirmZero: this.confirmZero,
          confirmed: true,
          operationId: op,
          reason: this.settleReason,
          evidence: this.settleEvidence,
        };
        officialTts.settle(body, () => {
          this.$message.success("已按最终累计费用结算/释放冻结");
          this.loadLedger();
          this.reload();
        }, () => this.$message.error("结算失败，未改前端展示值"));
      }).catch(() => {});
    },
  },
};
</script>

<style scoped>
.welcome { min-height: 100vh; }
.operation-bar, .main-wrapper { padding: 16px 24px; }
.hint { color: #666; font-size: 13px; }
.ledger { margin-top: 12px; }
</style>
