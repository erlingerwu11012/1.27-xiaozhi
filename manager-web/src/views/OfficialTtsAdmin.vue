<template>
  <div class="xn-page ota">
    <page-header :title="$t('xn.nav.ttsAdmin')" :description="$t('xn.ttsAdmin.desc')">
      <el-button :loading="loading" @click="reload"><xn-icon v-if="!loading" name="refresh" /> {{ $t('xn.billing.refresh') }}</el-button>
    </page-header>

    <el-alert class="ota-rule" type="info" :closable="false" show-icon :title="$t('xn.ttsAdmin.rule')" />

    <xn-empty v-if="failed && !loading" class="xn-panel" error @retry="reload" />

    <template v-else>
      <!-- 概览 -->
      <section class="xn-panel ota-overview" v-loading="loading && !loaded">
        <div class="xn-panel__head">
          <h2 class="xn-panel__title">{{ $t('xn.ttsAdmin.overview') }}</h2>
          <demo-tag />
        </div>
        <div class="xn-panel__body">
          <dl class="ota-stats">
            <div><dt>{{ $t('xn.ttsAdmin.enhancedFlag') }}</dt><dd>{{ show(overview.enhancedFlag) }}</dd></div>
            <div class="is-wide"><dt>{{ $t('xn.ttsAdmin.allowUsers') }}</dt><dd class="xn-clip" :title="overview.allowUsers">{{ overview.allowUsers || $t('xn.ttsAdmin.none') }}</dd></div>
            <div><dt>{{ $t('xn.ttsAdmin.voices') }}</dt><dd class="xn-num">{{ show(overview.voices) }}</dd></div>
            <div><dt>{{ $t('xn.ttsAdmin.jobs') }}</dt><dd class="xn-num">{{ show(overview.jobs) }}</dd></div>
            <div><dt>{{ $t('xn.ttsAdmin.uncertain') }}</dt>
              <dd class="xn-num" :class="{ 'is-warn': Number(overview.uncertainLedgers) > 0 }">{{ show(overview.uncertainLedgers) }}</dd></div>
          </dl>
          <p v-if="overview.priceUnitHintSale" class="ota-hint">{{ overview.priceUnitHintSale }}</p>
          <p v-if="overview.priceUnitHintCost" class="ota-hint">{{ overview.priceUnitHintCost }}</p>
        </div>
      </section>

      <!-- 价格版本 -->
      <section class="xn-panel xn-panel--flush ota-panel">
        <div class="xn-panel__head">
          <div>
            <h2 class="xn-panel__title">{{ $t('xn.ttsAdmin.prices') }}</h2>
            <p class="ota-sub xn-muted">{{ $t('xn.ttsAdmin.pricesDesc') }}</p>
          </div>
        </div>
        <el-table :data="overview.prices || []" v-loading="loading && !loaded" row-key="id">
          <el-table-column prop="id" label="ID" width="70" />
          <el-table-column :label="$t('xn.ttsAdmin.colKind')" min-width="80">
            <template slot-scope="{ row }">{{ kindLabel(row.priceKind) }}</template>
          </el-table-column>
          <el-table-column :label="$t('xn.ttsAdmin.colOperation')" min-width="90">
            <template slot-scope="{ row }">{{ opLabel(row.operation) }}</template>
          </el-table-column>
          <el-table-column prop="version" :label="$t('xn.ttsAdmin.colVersion')" min-width="120" show-overflow-tooltip />
          <el-table-column :label="$t('xn.ttsAdmin.colUnit')" min-width="100">
            <template slot-scope="{ row }">{{ unitLabel(row.unit) }}</template>
          </el-table-column>
          <el-table-column :label="$t('xn.ttsAdmin.colAmount')" min-width="120" align="right">
            <template slot-scope="{ row }"><span class="xn-num">{{ row.amount == null ? '—' : row.amount }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('xn.ttsAdmin.colStatus')" min-width="110">
            <template slot-scope="{ row }"><span class="xn-tag" :class="statusClass(row.status)">{{ statusLabel(row.status) }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('xn.ttsAdmin.colLifecycle')" min-width="100">
            <template slot-scope="{ row }"><span class="xn-tag" :class="row.lifecycleStatus === 'active' ? 'xn-tag--success' : 'xn-tag--muted'">{{ lifecycleLabel(row.lifecycleStatus) }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('xn.ttsAdmin.colActions')" min-width="290" align="right">
            <template slot-scope="{ row }">
              <div class="ota-actions">
                <el-button v-if="canEditDraft(row)" type="text" @click="editDraft(row)">{{ $t('xn.ttsAdmin.editDraft') }}</el-button>
                <el-button v-else type="text" :disabled="row.priceKind !== 'sale_points'" @click="draftFrom(row)">{{ $t('xn.ttsAdmin.draftFrom') }}</el-button>
                <el-button type="text" :disabled="!canPublish(row)" @click="publishPrice(row)">{{ $t('xn.ttsAdmin.publish') }}</el-button>
                <el-button type="text" @click="syncPrice(row)">{{ $t('xn.ttsAdmin.sync') }}</el-button>
              </div>
            </template>
          </el-table-column>
          <template slot="empty">
            <xn-empty icon="receipt" :title="$t('xn.ttsAdmin.noPrices')" />
          </template>
        </el-table>
      </section>

      <div class="ota-grid">
        <!-- 人工备注 -->
        <section class="xn-panel">
          <div class="xn-panel__head">
            <div>
              <h2 class="xn-panel__title">{{ $t('xn.ttsAdmin.noteTitle') }}</h2>
              <p class="ota-sub xn-muted">{{ $t('xn.ttsAdmin.noteDesc') }}</p>
            </div>
          </div>
          <div class="xn-panel__body">
            <el-form ref="noteForm" :model="noteModel" :rules="noteRules" label-position="top" @submit.native.prevent>
              <el-form-item :label="$t('xn.ttsAdmin.jobId')" prop="noteJobId">
                <el-input v-model.trim="noteJobId" :placeholder="$t('xn.ttsAdmin.jobIdPh')" />
              </el-form-item>
              <el-form-item :label="$t('xn.ttsAdmin.reason')" prop="noteReason">
                <el-input v-model="noteReason" maxlength="200" :placeholder="$t('xn.ttsAdmin.reasonPh')" />
              </el-form-item>
              <el-form-item :label="$t('xn.ttsAdmin.evidence')">
                <el-input v-model="noteEvidence" maxlength="200" :placeholder="$t('xn.ttsAdmin.evidencePh')" />
              </el-form-item>
              <div class="ota-form-foot">
                <el-button @click="resetNote">{{ $t('xn.common.reset') }}</el-button>
                <el-button type="primary" @click="submitNote">{{ $t('xn.ttsAdmin.addNote') }}</el-button>
              </div>
            </el-form>
          </div>
        </section>

        <!-- 人工结算 / 释放冻结 -->
        <section class="xn-panel">
          <div class="xn-panel__head">
            <div>
              <h2 class="xn-panel__title">{{ $t('xn.ttsAdmin.settleTitle') }}</h2>
              <p class="ota-sub xn-muted">{{ $t('xn.ttsAdmin.settleDesc') }}</p>
            </div>
          </div>
          <div class="xn-panel__body">
            <div class="ota-load">
              <el-input v-model.trim="settleJobId" :placeholder="$t('xn.ttsAdmin.jobIdPh')" data-testid="official-tts-settle-job"
                @keyup.enter.native="loadLedger" />
              <el-button data-testid="official-tts-load-ledger" :loading="ledgerLoading" @click="loadLedger">{{ $t('xn.ttsAdmin.loadLedger') }}</el-button>
            </div>

            <div v-if="ledger" class="ota-ledger" data-testid="official-tts-ledger">
              <dl class="ota-kv">
                <div><dt>{{ $t('xn.ttsAdmin.jobId') }}</dt><dd class="xn-num">{{ ledger.jobId }}</dd></div>
                <div><dt>{{ $t('xn.ttsAdmin.billId') }}</dt><dd class="xn-num">{{ ledger.billId }}</dd></div>
                <div><dt>{{ $t('xn.ttsAdmin.owner') }}</dt><dd class="xn-num">{{ ledger.userId }}</dd></div>
                <div><dt>{{ $t('xn.ttsAdmin.state') }}</dt><dd>{{ ledger.state || ledger.jobStatus }}</dd></div>
                <div><dt>{{ $t('xn.ttsAdmin.charged') }}</dt><dd class="xn-num">{{ ledger.charged }}</dd></div>
                <div><dt>{{ $t('xn.ttsAdmin.held') }}</dt><dd class="xn-num">{{ ledger.held }}</dd></div>
                <div><dt>{{ $t('xn.ttsAdmin.userQuota') }}</dt><dd class="xn-num">{{ ledger.userQuota }}</dd></div>
                <div><dt>{{ $t('xn.ttsAdmin.userUsed') }}</dt><dd class="xn-num">{{ ledger.userUsedQuota }}</dd></div>
                <div><dt>{{ $t('xn.ttsAdmin.remain') }}</dt><dd class="xn-num">{{ ledger.tokenRemainQuota }}</dd></div>
              </dl>

              <el-form label-position="top" @submit.native.prevent>
                <el-form-item :label="$t('xn.ttsAdmin.finalTotal')" required>
                  <el-input v-model.trim="finalTotal" :placeholder="$t('xn.ttsAdmin.finalTotalPh')" data-testid="official-tts-final-total" />
                </el-form-item>
                <el-checkbox v-model="confirmZero" class="ota-zero" data-testid="official-tts-confirm-zero">{{ $t('xn.ttsAdmin.confirmZero') }}</el-checkbox>
                <div class="ota-row">
                  <el-form-item :label="$t('xn.ttsAdmin.settleReason')">
                    <el-input v-model="settleReason" maxlength="200" data-testid="official-tts-settle-reason" />
                  </el-form-item>
                  <el-form-item :label="$t('xn.ttsAdmin.evidence')">
                    <el-input v-model="settleEvidence" maxlength="200" data-testid="official-tts-settle-evidence" />
                  </el-form-item>
                </div>
              </el-form>
              <p v-if="previewText" class="ota-preview" data-testid="official-tts-settle-preview"><xn-icon name="info" /> {{ previewText }}</p>
              <div class="ota-form-foot">
                <el-button type="danger" plain data-testid="official-tts-settle-submit" @click="doSettle">{{ $t('xn.ttsAdmin.submitSettle') }}</el-button>
              </div>
            </div>
            <p v-else class="ota-sub xn-muted">{{ $t('xn.ttsAdmin.ledgerEmpty') }}</p>
          </div>
        </section>
      </div>
    </template>

    <!-- 编辑草稿 -->
    <el-dialog :title="$t('xn.ttsAdmin.editDraftTitle')" :visible.sync="draftVisible" width="440px" append-to-body :close-on-click-modal="false">
      <p class="ota-sub xn-muted">{{ $t('xn.ttsAdmin.editDraftHelp') }}</p>
      <el-form ref="draftForm" :model="draftModel" :rules="draftRules" label-position="top" @submit.native.prevent>
        <el-form-item :label="$t('xn.ttsAdmin.colAmount')" prop="amount">
          <el-input v-model.trim="draftModel.amount" :placeholder="$t('xn.ttsAdmin.amountPh')" @keyup.enter.native="saveDraft" />
        </el-form-item>
      </el-form>
      <span slot="footer">
        <el-button @click="draftVisible = false">{{ $t('xn.common.cancel') }}</el-button>
        <el-button type="primary" :loading="draftSaving" @click="saveDraft">{{ $t('xn.ttsAdmin.saveDraft') }}</el-button>
      </span>
    </el-dialog>

    <!-- 发布 -->
    <el-dialog :title="$t('xn.ttsAdmin.publishTitle')" :visible.sync="publishVisible" width="440px" append-to-body :close-on-click-modal="false">
      <p class="ota-sub xn-muted">{{ $t('xn.ttsAdmin.publishHelp') }}</p>
      <dl v-if="publishRow" class="ota-kv is-compact">
        <div><dt>{{ $t('xn.ttsAdmin.colOperation') }}</dt><dd>{{ opLabel(publishRow.operation) }}</dd></div>
        <div><dt>{{ $t('xn.ttsAdmin.colVersion') }}</dt><dd>{{ publishRow.version }}</dd></div>
        <div><dt>{{ $t('xn.ttsAdmin.colAmount') }}</dt><dd class="xn-num">{{ publishRow.amount }}</dd></div>
      </dl>
      <el-form label-position="top" @submit.native.prevent>
        <el-form-item :label="$t('xn.ttsAdmin.publishReason')">
          <el-input v-model="publishReason" maxlength="200" :placeholder="$t('xn.ttsAdmin.publishReasonPh')" />
        </el-form-item>
      </el-form>
      <span slot="footer">
        <el-button @click="publishVisible = false">{{ $t('xn.common.cancel') }}</el-button>
        <el-button type="primary" :loading="publishing" @click="confirmPublish">{{ $t('xn.ttsAdmin.publish') }}</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import officialTts from "@/apis/module/officialTts";

/** 请求层对业务错误（code≠0）只弹出提示、不回调页面；超过这个时间仍无响应就显示失败状态，避免一直加载 */
const NO_REPLY_MS = 10000;

const OPS = { synthesize: "语音合成", design: "音色设计", clone: "音色复刻" };
const KINDS = { sale_points: "售价", cost: "成本" };
const UNITS = { weighted_character: "计费字符", audio_second: "秒", official_units: "官方计量单位" };
const STATUS = {
  draft: ["草稿", "xn-tag--lake"],
  published: ["已发布", "xn-tag--success"],
  publish_ack_pending: ["等待确认", "xn-tag--warning"],
  publish_failed: ["发布失败", "xn-tag--danger"],
};
const LIFECYCLE = { active: "生效中", draft: "未生效", superseded: "已被替换", retired: "已停用" };

export default {
  name: "OfficialTtsAdmin",
  data() {
    return {
      overview: {},
      loading: false,
      loaded: false,
      failed: false,
      noteJobId: "",
      noteReason: "",
      noteEvidence: "",
      settleJobId: "",
      ledger: null,
      ledgerLoading: false,
      finalTotal: "",
      confirmZero: false,
      settleReason: "",
      settleEvidence: "",
      lastSettleOpId: "",
      lastSettleSig: "",
      draftVisible: false,
      draftRow: null,
      draftModel: { amount: "" },
      draftSaving: false,
      publishVisible: false,
      publishRow: null,
      publishReason: "",
      publishing: false,
    };
  },
  computed: {
    noteModel() {
      return { noteJobId: this.noteJobId, noteReason: this.noteReason };
    },
    noteRules() {
      return {
        noteJobId: [{ required: true, message: "请填写任务 ID", trigger: "blur" }, { pattern: /^\d+$/, message: "任务 ID 是数字", trigger: "blur" }],
        noteReason: [{ required: true, message: "请填写备注理由", trigger: "blur" }],
      };
    },
    draftRules() {
      return {
        amount: [
          { required: true, message: "请填写金额", trigger: "blur" },
          { validator: (r, v, cb) => (Number.isNaN(Number(v)) || Number(v) <= 0 ? cb(new Error("金额必须是大于 0 的数字")) : cb()), trigger: "blur" },
        ],
      };
    },
    previewText() {
      if (!this.ledger || this.finalTotal === "" || this.finalTotal === null) {
        return "最终累计费用未填写，提交会被拒绝。";
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
  beforeDestroy() {
    clearTimeout(this.guard);
  },
  methods: {
    show(v) { return v === undefined || v === null || v === "" ? "—" : v; },
    opLabel(v) { return OPS[v] || v || "—"; },
    kindLabel(v) { return KINDS[v] || v || "—"; },
    unitLabel(v) { return UNITS[v] || v || "—"; },
    statusLabel(v) { return (STATUS[v] || [v || "—"])[0]; },
    statusClass(v) { return (STATUS[v] || [null, "xn-tag--muted"])[1]; },
    lifecycleLabel(v) { return LIFECYCLE[v] || v || "—"; },
    reload() {
      this.loading = true;
      this.failed = false;
      clearTimeout(this.guard);
      this.guard = setTimeout(() => { if (this.loading) { this.loading = false; this.failed = !this.loaded; } }, NO_REPLY_MS);
      officialTts.adminOverview((res) => {
        clearTimeout(this.guard);
        this.overview = (res.data && res.data.data) || {};
        this.loading = false;
        this.loaded = true;
      }, () => {
        this.loading = false;
        this.failed = true;
      });
    },
    canEditDraft(row) {
      return row.priceKind === "sale_points" && row.status === "draft";
    },
    canPublish(row) {
      return row.priceKind === "sale_points" && (row.status === "draft" || row.status === "publish_ack_pending" || row.status === "publish_failed");
    },
    editDraft(row) {
      this.draftRow = row;
      this.draftModel = { amount: row.amount == null ? "" : String(row.amount) };
      this.draftVisible = true;
      this.$nextTick(() => this.$refs.draftForm && this.$refs.draftForm.clearValidate());
    },
    saveDraft() {
      const row = this.draftRow;
      if (!row) return;
      this.$refs.draftForm.validate((valid) => {
        if (!valid) return;
        const value = this.draftModel.amount;
        this.draftSaving = true;
        officialTts.updatePrice({
          id: row.id,
          priceKind: "sale_points",
          operation: row.operation,
          unit: row.unit,
          amount: value === "" ? null : Number(value),
        }, () => {
          this.draftSaving = false;
          this.draftVisible = false;
          this.$message.success("已保存草稿，当前生效价未变");
          this.reload();
        }, () => {
          this.draftSaving = false;
          this.$message.error("保存草稿失败");
        });
        // 业务错误由请求层提示；稍后复位按钮状态
        setTimeout(() => { this.draftSaving = false; }, 3000);
      });
    },
    draftFrom(row) {
      officialTts.draftFromPublished(row.id, () => {
        this.$message.success("已创建新版本草稿，原已发布版本仍生效");
        this.reload();
      }, () => this.$message.error("新建草稿失败"));
    },
    publishPrice(row) {
      this.publishRow = row;
      this.publishReason = "";
      this.publishVisible = true;
    },
    confirmPublish() {
      const row = this.publishRow;
      if (!row) return;
      this.publishing = true;
      officialTts.publishPrice({ id: row.id, reason: this.publishReason || "admin_publish" }, () => {
        this.publishing = false;
        this.publishVisible = false;
        this.$message.success("已发布，该版本已生效");
        this.reload();
      }, () => {
        this.publishing = false;
        this.$message.error("发布结果未确认，当前仍使用原生效版本；可稍后点“同步状态”");
      });
      setTimeout(() => { this.publishing = false; }, 3000);
    },
    syncPrice(row) {
      officialTts.syncPublished(row.id, () => {
        this.$message.success("已同步生效状态");
        this.reload();
      }, () => this.$message.error("同步失败"));
    },
    resetNote() {
      this.noteJobId = "";
      this.noteReason = "";
      this.noteEvidence = "";
      this.$nextTick(() => this.$refs.noteForm && this.$refs.noteForm.clearValidate());
    },
    submitNote() {
      this.$refs.noteForm.validate((valid) => { if (valid) this.doNote(); });
    },
    doNote() {
      if (!this.noteJobId || !this.noteReason) {
        this.$message.error("任务 ID 和理由必填");
        return;
      }
      const op = (typeof crypto !== "undefined" && crypto.randomUUID) ? crypto.randomUUID() : ("note-" + Date.now());
      officialTts.addNote(this.noteJobId, op, this.noteReason, this.noteEvidence || "console", () => {
        this.$message.success("已添加备注，未结算、未退款、未改冻结");
        this.resetNote();
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
      this.ledgerLoading = true;
      officialTts.jobLedger(this.settleJobId, (res) => {
        this.ledgerLoading = false;
        this.ledger = (res.data && res.data.data) || {};
      }, () => {
        this.ledgerLoading = false;
        this.$message.error("读取账单失败");
      });
      setTimeout(() => { this.ledgerLoading = false; }, 3000);
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
        confirmButtonText: "提交结算",
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
.ota-rule { margin-bottom: 16px; }
.ota-panel { overflow: hidden; margin-top: 16px; }
.ota-sub { margin: 2px 0 0; font-size: 13px; }
.ota-stats { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; margin: 0; }
.ota-stats div { min-width: 0; padding: 12px 14px; border-radius: var(--xn-r); background: var(--xn-mist-2); }
.ota-stats .is-wide { grid-column: span 2; }
.ota-stats dt { font-size: 13px; color: var(--xn-ink-3); }
.ota-stats dd { margin: 4px 0 0; font-size: 18px; font-weight: 600; color: var(--xn-ink); }
.ota-stats dd.is-warn { color: var(--xn-warning); }
.ota-hint { margin: 12px 0 0; font-size: 13px; color: var(--xn-ink-3); }
.ota-actions { display: inline-flex; flex-wrap: nowrap; white-space: nowrap; justify-content: flex-end; gap: 0 12px; }
.ota-actions .el-button + .el-button { margin-left: 0; }
.ota-grid { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1.3fr); gap: 16px; margin-top: 16px; align-items: start; }
.ota-grid .xn-panel + .xn-panel { margin-top: 0; }
.ota-form-foot { display: flex; justify-content: flex-end; gap: 8px; margin-top: 8px; }
.ota-form-foot .el-button + .el-button { margin-left: 0; }
.ota-load { display: flex; gap: 8px; }
.ota-load .el-input { flex: 1; }
.ota-ledger { margin-top: 16px; }
.ota-kv { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 0 16px; margin: 0 0 16px; }
.ota-kv.is-compact { grid-template-columns: 1fr; margin: 8px 0 12px; }
.ota-kv div { display: flex; justify-content: space-between; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--xn-line-2); min-width: 0; font-size: 13px; }
.ota-kv dt { color: var(--xn-ink-3); white-space: nowrap; }
.ota-kv dd { margin: 0; color: var(--xn-ink); font-weight: 500; text-align: right; word-break: break-all; }
.ota-zero { display: flex; margin: -4px 0 14px; white-space: normal; }
.ota-zero ::v-deep .el-checkbox__label { white-space: normal; line-height: 1.5; }
.ota-row { display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px; }
.ota-preview { display: flex; gap: 6px; margin: 0; padding: 10px 12px; border-radius: var(--xn-r); background: var(--xn-warning-soft); color: var(--xn-warning); font-size: 13px; line-height: 1.6; }
.ota-preview .xn-icon { margin-top: 3px; }

@media (max-width: 1180px) {
  .ota-grid { grid-template-columns: 1fr; }
}
@media (max-width: 640px) {
  .ota-kv, .ota-row { grid-template-columns: 1fr; }
  .ota-stats .is-wide { grid-column: auto; }
}
</style>
