<template>
  <div class="ot-page">
  <OfficialTtsStudioShell
    :active-tab="mode"
    :warning="caps ? actionBlockedReason : ''"
    :compact="mode === 'clone' && !!cloneFile"
  >
    <template #hero>{{ heroTitle }}</template>

    <template #composer>
      <template v-if="mode === 'design'">
        <label class="ot-label" for="ot-design-prompt">{{ $t('xn.tts.designLabel') }}</label>
        <el-input
          id="ot-design-prompt"
          type="textarea"
          class="ot-composer__textarea"
          :rows="3"
          v-model="designPrompt"
          resize="none"
          maxlength="500"
          :placeholder="$t('xn.tts.designPlaceholder')"
        />
        <div class="ot-composer__bar">
          <button type="button" class="ot-tool" @click="openPreviewDialog">
            <xn-icon name="edit" />
            <span>{{ $t('xn.tts.previewText') }}</span>
            <span class="ot-tool__val">{{ previewText }}</span>
          </button>
          <span class="xn-toolbar__grow"></span>
          <el-button type="primary" :disabled="!canSubmitDesign || submitting" :loading="submitting" :title="sendTitle" @click="createDesign">
            {{ $t('xn.tts.startDesign') }}
          </el-button>
        </div>
      </template>

      <template v-else>
        <div v-if="recording" class="ot-recorder" role="status">
          <button type="button" class="ot-recorder__stop" :title="$t('xn.tts.stopRecord')" :aria-label="$t('xn.tts.stopRecord')" @click="stopRecord(false)">
            <span class="ot-recorder__stop-square" />
          </button>
          <div class="ot-recorder__wave" aria-hidden="true">
            <span v-for="(h, i) in recordBars" :key="i" class="ot-recorder__bar" :class="{ 'is-active': i <= recordIndex }" :style="{ height: h + '%' }" />
          </div>
          <span class="ot-recorder__time xn-num">{{ recordClock }} / {{ maxRecordClock }}</span>
          <el-button size="small" @click="stopRecord(true)">{{ $t('xn.tts.cancelRecord') }}</el-button>
        </div>

        <template v-else>
          <div v-if="cloneFile" class="ot-clone-file">
            <span class="ot-clone-file__icon" aria-hidden="true"><xn-icon name="voice" /></span>
            <div class="ot-clone-file__main">
              <p class="ot-clone-file__title" :title="cloneFileTooltip">{{ cloneFileTitle }}</p>
              <p class="ot-clone-file__sub xn-num">{{ cloneFileMeta }}</p>
            </div>
            <el-button size="small" @click="clearCloneFile">{{ $t('xn.tts.removeFile') }}</el-button>
          </div>

          <div v-else class="ot-clone-pick">
            <input ref="cloneFileInput" type="file" accept="audio/wav,audio/x-wav,.wav,audio/*" class="ot-clone-pick__hidden" @change="onCloneFilePicked" />
            <button type="button" class="ot-clone-pick__card" :disabled="!actionsEnabled" @click="triggerCloneUpload">
              <xn-icon name="upload" />
              <span class="ot-clone-pick__title">{{ $t('xn.tts.uploadVoice') }}</span>
              <span class="ot-clone-pick__hint">{{ $t('xn.tts.uploadHint') }}</span>
            </button>
            <button type="button" class="ot-clone-pick__card" :disabled="!actionsEnabled" @click="toggleRecord">
              <xn-icon name="mic" />
              <span class="ot-clone-pick__title">{{ $t('xn.tts.recordVoice') }}</span>
              <span class="ot-clone-pick__hint">{{ $t('xn.tts.recordHint', { n: maxRecordSeconds }) }}</span>
            </button>
          </div>

          <div class="ot-composer__bar">
            <span class="ot-composer__note xn-muted">{{ mock ? $t('xn.tts.mockUploadNote') : $t('xn.tts.cloneNote') }}</span>
            <span class="xn-toolbar__grow"></span>
            <el-button type="primary" :disabled="!canSubmitClone || submitting" :loading="submitting" :title="cloneSendTitle" @click="submitClone">
              {{ $t('xn.tts.startClone') }}
            </el-button>
          </div>
        </template>
      </template>
    </template>

    <template #bottom>
      <section class="xn-panel xn-panel--flush ot-list">
        <div class="xn-panel__head">
          <h2 class="xn-panel__title">
            {{ mode === 'design' ? $t('xn.tts.myDesigns') : $t('xn.tts.myClones') }}
            <span class="ot-count xn-num">{{ filteredVoices.length }}</span>
          </h2>
          <span class="ot-list__head-right">
            <span v-if="showGenerating" class="xn-tag xn-tag--lake" role="status"><i class="el-icon-loading"></i>{{ $t('xn.tts.generating') }}</span>
            <demo-tag />
          </span>
        </div>
        <xn-empty v-if="loadFailed && !loading" error @retry="reload()" />
        <el-table v-else :data="filteredVoices" v-loading="loading" row-key="id" class="ot-table">
          <el-table-column :label="$t('xn.tts.colVoice')" min-width="260">
            <template slot-scope="{ row }">
              <div class="ot-voice">
                <button type="button" class="ot-play" :class="{ 'is-on': playingId === row.id && !playPaused }"
                  :disabled="!canPlay(row) || loadingId === row.id"
                  :title="canPlay(row) ? $t('xn.tts.play') : $t('xn.tts.noPreview')"
                  :aria-label="(playingId === row.id && !playPaused ? $t('xn.tts.pause') : $t('xn.tts.play')) + ' ' + voiceTitle(row)"
                  @click="togglePlay(row)">
                  <i v-if="loadingId === row.id" class="el-icon-loading"></i>
                  <svg v-else-if="playingId === row.id && !playPaused" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14M16 5v14" /></svg>
                  <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l10-6.5z" /></svg>
                </button>
                <div class="ot-voice__text">
                  <span class="ot-voice__name xn-clip">{{ voiceTitle(row) }}</span>
                  <span v-if="row.upstreamVoiceId" class="ot-voice__sub xn-muted xn-clip xn-num" :title="row.upstreamVoiceId">{{ $t('xn.tts.voiceId') }} {{ shortVoiceId(row.upstreamVoiceId) }}</span>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column :label="$t('xn.tts.colStatus')" min-width="120">
            <template slot-scope="{ row }">
              <span class="xn-tag" :class="statusClass(row.status)">{{ statusLabel(row.status) }}</span>
              <el-tooltip v-if="row.errorMsg && !String(row.errorMsg).startsWith('task:')" :content="row.errorMsg" placement="top" popper-class="xn-tip-wide">
                <button type="button" class="ot-info" :aria-label="row.errorMsg"><xn-icon name="info" /></button>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column :label="$t('xn.tts.colCreated')" min-width="130">
            <template slot-scope="{ row }"><span class="xn-num">{{ formatTime(row.createdAt) }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('xn.tts.colActions')" min-width="210" align="right">
            <template slot-scope="{ row }">
              <el-button type="text" :disabled="!canGoSynth(row)" :title="canGoSynth(row) ? '' : $t('xn.tts.notReady')" @click="goSynth(row)">{{ $t('xn.tts.goSynth') }}</el-button>
              <el-button type="text" @click="rename(row)">{{ $t('xn.tts.rename') }}</el-button>
              <el-button type="text" class="ot-danger" @click="remove(row)">{{ $t('xn.tts.delete') }}</el-button>
            </template>
          </el-table-column>
          <template slot="empty">
            <xn-empty icon="voice" :title="mode === 'design' ? $t('xn.tts.emptyDesign') : $t('xn.tts.emptyClone')"
              :description="mode === 'design' ? $t('xn.tts.emptyDesignDesc') : $t('xn.tts.emptyCloneDesc')" />
          </template>
        </el-table>
        <audio ref="audioEl" class="ot-audio-el" @timeupdate="onAudioTime" @loadedmetadata="onAudioMeta" @ended="onAudioEnded"
          @pause="playPaused = true" @play="playPaused = false" />
      </section>
    </template>
  </OfficialTtsStudioShell>

    <el-dialog :title="$t('xn.tts.previewDialogTitle')" :visible.sync="previewDialogVisible" width="560px" append-to-body :close-on-click-modal="false">
      <p class="ot-dialog-help">{{ $t('xn.tts.previewDialogHelp') }}</p>
      <el-input type="textarea" v-model="previewDraft" :rows="6" resize="none" maxlength="230" :placeholder="previewPlaceholder" />
      <div class="ot-dialog-count xn-muted xn-num">{{ previewDraftLength }} / 230</div>
      <span slot="footer" class="ot-dialog-foot">
        <el-button type="text" :disabled="!previewDraft" @click="previewDraft = ''">{{ $t('xn.tts.clearText') }}</el-button>
        <span class="xn-toolbar__grow"></span>
        <el-button @click="previewDialogVisible = false">{{ $t('xn.common.cancel') }}</el-button>
        <el-button type="primary" @click="confirmPreviewText">{{ $t('xn.tts.usePreviewText') }}</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import OfficialTtsStudioShell from "@/components/OfficialTtsStudioShell.vue";
import officialTts from "@/apis/module/officialTts";
import { isMockMode } from "@/mock/config";

const DEFAULT_PREVIEW = "欢迎使用文本朗读，这是一段设计的音色。";

const STATUS_LABEL = {
  available: "可用",
  processing: "生成中",
  uncertain: "处理中",
  failed: "失败",
  deleted: "已删除",
  pending_authorization: "待授权",
};

export default {
  name: "OfficialTtsVoices",
  components: { OfficialTtsStudioShell },
  data() {
    return {
      caps: null,
      voices: [],
      loading: false,
      loadFailed: false,
      mock: isMockMode(),
      submitting: false,
      cloneName: "我的音色",
      cloneFile: null,
      cloneFileMeta: "",
      cloneFileTitle: "",
      cloneFileTooltip: "",
      recording: false,
      maxRecordSeconds: 20,
      recordBarCount: 64,
      recordSeconds: 0,
      recordProgress: 0,
      recordLevels: [],
      recordRaf: null,
      recordAnalyser: null,
      recordStartAt: 0,
      recordCtx: null,
      recordStream: null,
      recordProcessor: null,
      recordChunks: null,
      designPrompt: "",
      previewText: DEFAULT_PREVIEW,
      previewDraft: "",
      previewDialogVisible: false,
      agentId: this.$route.query.agentId || "",
      playingId: null,
      playUrl: "",
      playCurrent: 0,
      playDuration: 0,
      playPaused: true,
      loadingId: null,
      pollTimer: null,
    };
  },
  computed: {
    mode() {
      const m = (this.$route.query.mode || "clone").toString();
      return m === "design" ? "design" : "clone";
    },
    heroTitle() {
      return this.mode === "design" ? this.$t("xn.tts.heroDesign") : this.$t("xn.tts.heroClone");
    },
    filteredVoices() {
      return (this.voices || []).filter((v) => {
        if (v.status === "deleted") return false;
        if (this.mode === "design") return v.kind === "design";
        return v.kind === "clone";
      });
    },
    previewPlaceholder() {
      return `请输入预览文本（长度需大于15字符），不输入则播放默认文案：“${DEFAULT_PREVIEW}”`;
    },
    previewDraftLength() {
      return Array.from(this.previewDraft || "").length;
    },
    actionBlockedReason() {
      if (!this.caps) return "当前不可用：正在加载能力状态…";
      if (this.caps.accessStatusText && this.caps.accessStatus !== "ready") {
        return this.caps.accessStatusText;
      }
      if (this.mode === "design" && this.caps.operations && this.caps.operations.design
          && this.caps.operations.design.callable === false) {
        if (this.caps.enhancedEnabled && !this.caps.operations.design.priced) {
          return "音色设计尚未配置有效售价，暂不可用";
        }
        return "音色设计当前不可用";
      }
      if (this.mode === "clone" && this.caps.operations && this.caps.operations.clone
          && this.caps.operations.clone.callable === false) {
        if (this.caps.enhancedEnabled && !this.caps.operations.clone.priced) {
          return "音色复刻尚未配置有效售价，暂不可用";
        }
        return "音色复刻当前不可用";
      }
      if (this.caps.accessStatusText) return this.caps.accessStatus === "ready" ? "" : this.caps.accessStatusText;
      if (this.caps.enhancedEnabled === false) {
        return "官方语音功能尚未对你的账号开放，暂时无法使用。";
      }
      if (this.caps.pricingStatus === "pricing_pending") {
        return "该功能暂未开放计费，暂时无法使用。";
      }
      if (this.caps.customerCallable === false) return "当前不可用";
      if (this.caps.customerCallable !== true) return "当前不可用";
      return "";
    },
    actionsEnabled() {
      if (!this.caps) return false;
      if (this.mode === "design" && this.caps.operations && this.caps.operations.design) {
        return !!this.caps.operations.design.callable;
      }
      if (this.mode === "clone" && this.caps.operations && this.caps.operations.clone) {
        return !!this.caps.operations.clone.callable;
      }
      return !this.actionBlockedReason;
    },
    canSubmitDesign() {
      return this.actionsEnabled && !!this.designPrompt.trim();
    },
    canSubmitClone() {
      return this.actionsEnabled && !!this.cloneFile && !this.recording;
    },
    recordIndex() {
      if (!this.recording && !this.recordProgress) return -1;
      const total = this.recordBarCount;
      const n = Math.floor(this.recordProgress * total);
      return Math.max(0, Math.min(total - 1, n - 1));
    },
    recordBars() {
      const levels = this.recordLevels || [];
      const total = this.recordBarCount;
      const idx = this.recordIndex;
      const bars = [];
      for (let i = 0; i < total; i += 1) {
        if (i > idx) {
          bars.push(12 + (i % 4) * 3);
        } else {
          const lvl = Math.min(1, Math.max(0, levels[i] || 0));
          bars.push(Math.round(16 + lvl * 84));
        }
      }
      return bars;
    },
    recordClock() {
      return this.clockLabel(this.recordSeconds);
    },
    maxRecordClock() {
      return this.clockLabel(this.maxRecordSeconds);
    },
    sendTitle() {
      if (this.actionBlockedReason) return this.actionBlockedReason;
      if (!this.designPrompt.trim()) return "请先输入音色描述";
      return "开始设计";
    },
    cloneSendTitle() {
      if (this.actionBlockedReason) return this.actionBlockedReason;
      if (this.recording) return "请先结束录制";
      if (!this.cloneFile) return "请先上传或录制声音";
      return "开始复刻";
    },
    hasPending() {
      return this.filteredVoices.some((v) => v.status === "processing" || v.status === "uncertain");
    },
    showGenerating() {
      return this.submitting || this.hasPending;
    },
  },
  watch: {
    "$route.query.agentId"(val) {
      this.agentId = val || "";
    },
    "$route.query.mode"() {
      this.stopPlay();
      this.stopRecord(true);
      this.clearCloneFile();
      this.reload();
    },
    hasPending(val) {
      if (val) this.startPoll();
      else this.stopPoll();
    },
  },
  created() {
    this.reload();
  },
  beforeDestroy() {
    this.stopPoll();
    this.stopPlay();
    this.stopRecord(true);
  },
  methods: {
    apiMsg(err, fallback) {
      return (err && err.data && (err.data.msg || err.data.message)) || fallback;
    },
    statusClass(status) {
      if (status === "available") return "xn-tag--success";
      if (status === "failed") return "xn-tag--danger";
      if (status === "pending_authorization") return "xn-tag--warning";
      if (status === "processing" || status === "uncertain") return "xn-tag--lake";
      return "xn-tag--muted";
    },
    statusLabel(status) {
      return STATUS_LABEL[status] || status || "-";
    },
    shortVoiceId(id) {
      if (!id) return "";
      return id.length > 28 ? `${id.slice(0, 14)}…${id.slice(-8)}` : id;
    },
    voiceTitle(row) {
      return row.name || "未命名音色";
    },
    canPlay(row) {
      return !!(row && (row.hasPreview === true || row.hasPreview === "true"));
    },
    canGoSynth(row) {
      return !!(row && row.upstreamVoiceId);
    },
    avatarClass(row, idx) {
      if (row.status === "failed") return "is-amber";
      if (this.playingId === row.id) return "is-playing";
      const list = ["is-blue", "is-pink", "is-amber", "is-green"];
      return list[idx % list.length];
    },
    formatTime(ts) {
      if (!ts) return "-";
      const d = new Date(ts);
      if (Number.isNaN(d.getTime())) return String(ts);
      return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    },
    openPreviewDialog() {
      this.previewDraft = this.previewText === DEFAULT_PREVIEW ? "" : this.previewText;
      this.previewDialogVisible = true;
    },
    confirmPreviewText() {
      const text = (this.previewDraft || "").trim();
      if (!text) {
        this.previewText = DEFAULT_PREVIEW;
        this.previewDialogVisible = false;
        this.$message.success("已使用默认预览文案");
        return;
      }
      const len = Array.from(text).length;
      if (len < 15) {
        this.$message.warning("预览文本长度需大于等于 15 个字符");
        return;
      }
      if (len > 230) {
        this.$message.warning("预览文本不能超过 230 个字符");
        return;
      }
      this.previewText = text;
      this.previewDialogVisible = false;
      this.$message.success("预览文本已更新");
    },
    startPoll() {
      if (this.pollTimer) return;
      this.pollTimer = setInterval(() => this.reload(true), 5000);
    },
    stopPoll() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer);
        this.pollTimer = null;
      }
    },
    reload(silent) {
      if (!silent) this.loading = true;
      officialTts.capabilities((res) => {
        this.caps = (res.data && res.data.data) || res.data || null;
      }, () => { this.caps = this.caps || {}; });
      officialTts.listVoices((res) => {
        this.voices = (res.data && res.data.data) || [];
        this.loading = false;
        this.loadFailed = false;
      }, () => {
        this.loading = false;
        if (!silent) this.loadFailed = true;
      });
    },
    triggerCloneUpload() {
      if (!this.actionsEnabled) {
        this.$message.warning(this.actionBlockedReason);
        return;
      }
      if (this.$refs.cloneFileInput) this.$refs.cloneFileInput.click();
    },
    onCloneFilePicked(ev) {
      const file = ev.target && ev.target.files && ev.target.files[0];
      if (ev.target) ev.target.value = "";
      if (!file) return;
      this.setCloneFile(file);
    },
    setCloneFile(file, opts) {
      this.stopRecord(true);
      this.cloneFile = file;
      const mb = (file.size / (1024 * 1024)).toFixed(2);
      this.cloneFileMeta = `${mb} MB`;
      const rawName = String((opts && opts.name) || file.name || "音频");
      this.cloneFileTitle = rawName.length > 22 ? `${rawName.slice(0, 20)}…` : rawName;
      this.cloneFileTooltip = `${rawName} · ${mb} MB`;
      if (!this.cloneName || this.cloneName === "我的音色") {
        const base = rawName.replace(/\.[^.]+$/, "");
        this.cloneName = base.slice(0, 32) || "我的音色";
      }
    },
    clearCloneFile() {
      this.cloneFile = null;
      this.cloneFileMeta = "";
      this.cloneFileTitle = "";
      this.cloneFileTooltip = "";
    },
    async toggleRecord() {
      if (!this.actionsEnabled) {
        this.$message.warning(this.actionBlockedReason);
        return;
      }
      if (this.recording) {
        await this.stopRecord(false);
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        const Ctx = window.AudioContext || window.webkitAudioContext;
        const ctx = new Ctx({ sampleRate: 24000 });
        const source = ctx.createMediaStreamSource(stream);
        const processor = ctx.createScriptProcessor(4096, 1, 1);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 512;
        const mute = ctx.createGain();
        mute.gain.value = 0;
        const chunks = [];
        processor.onaudioprocess = (e) => {
          const input = e.inputBuffer.getChannelData(0);
          chunks.push(new Float32Array(input));
        };
        source.connect(analyser);
        source.connect(processor);
        processor.connect(mute);
        mute.connect(ctx.destination);
        this.recordStream = stream;
        this.recordCtx = ctx;
        this.recordProcessor = processor;
        this.recordAnalyser = analyser;
        this.recordChunks = chunks;
        this.recording = true;
        this.recordSeconds = 0;
        this.recordProgress = 0;
        this.recordLevels = new Array(this.recordBarCount).fill(0);
        this.recordStartAt = (window.performance && performance.now) ? performance.now() : Date.now();
        this.startRecordMeter();
        this.$message.info(`开始录制，建议 3–${this.maxRecordSeconds} 秒，点击停止结束`);
      } catch (e) {
        this.$message.error("无法访问麦克风，请检查浏览器权限");
      }
    },
    startRecordMeter() {
      const analyser = this.recordAnalyser;
      if (!analyser) return;
      const buf = new Uint8Array(analyser.fftSize);
      const total = this.recordBarCount;
      let lastPaint = 0;
      const tick = () => {
        if (!this.recording) return;
        const elapsed = this.recordElapsed();
        this.recordSeconds = Math.min(this.maxRecordSeconds, Math.floor(elapsed));
        this.recordProgress = Math.min(1, elapsed / this.maxRecordSeconds);
        const now = (window.performance && performance.now) ? performance.now() : Date.now();
        // 约 30fps 刷新波形，降低低端设备重绘压力
        if (now - lastPaint >= 33) {
          lastPaint = now;
          analyser.getByteTimeDomainData(buf);
          let sum = 0;
          for (let i = 0; i < buf.length; i += 1) {
            const v = (buf[i] - 128) / 128;
            sum += v * v;
          }
          const rms = Math.sqrt(sum / buf.length);
          const level = Math.min(1, rms * 3.4);
          const idx = Math.max(0, Math.min(total - 1, Math.floor(this.recordProgress * total) - 1));
          const next = this.recordLevels.slice();
          for (let i = 0; i <= idx; i += 1) {
            if (next[i]) next[i] *= 0.9;
          }
          next[idx] = Math.max(level, next[idx] || 0, 0.08);
          this.recordLevels = next;
        }
        if (elapsed >= this.maxRecordSeconds) {
          this.stopRecord(false);
          return;
        }
        this.recordRaf = requestAnimationFrame(tick);
      };
      this.recordRaf = requestAnimationFrame(tick);
    },
    recordElapsed() {
      const start = this.recordStartAt || 0;
      const now = (window.performance && performance.now) ? performance.now() : Date.now();
      return Math.max(0, (now - start) / 1000);
    },
    clockLabel(sec) {
      const n = Math.max(0, Math.floor(Number(sec) || 0));
      const m = Math.floor(n / 60);
      const s = n % 60;
      return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    },
    async stopRecord(discard) {
      if (this.recordRaf) {
        cancelAnimationFrame(this.recordRaf);
        this.recordRaf = null;
      }
      const wasRecording = this.recording;
      this.recording = false;
      const chunks = this.recordChunks || [];
      const sampleRate = (this.recordCtx && this.recordCtx.sampleRate) || 24000;
      try {
        if (this.recordProcessor) {
          this.recordProcessor.disconnect();
          this.recordProcessor.onaudioprocess = null;
        }
        if (this.recordStream) {
          this.recordStream.getTracks().forEach((t) => t.stop());
        }
        if (this.recordCtx && this.recordCtx.state !== "closed") {
          await this.recordCtx.close();
        }
      } catch (e) {
        // ignore cleanup errors
      }
      this.recordProcessor = null;
      this.recordStream = null;
      this.recordCtx = null;
      this.recordChunks = null;
      this.recordAnalyser = null;
      if (discard || !wasRecording) {
        this.recordLevels = [];
        this.recordProgress = 0;
        this.recordSeconds = 0;
        return;
      }
      if (!chunks.length || this.recordSeconds < 3) {
        this.$message.warning("录制太短，请至少录制 3 秒");
        return;
      }
      const wavBlob = this.encodeWavBlob(chunks, sampleRate);
      const file = new File([wavBlob], `录音-${Date.now()}.wav`, { type: "audio/wav" });
      this.setCloneFile(file, { name: "录音.wav" });
      this.recordLevels = [];
      this.recordProgress = 0;
      this.$message.success("录制完成，可点击右下角提交复刻");
    },
    encodeWavBlob(chunks, sampleRate) {
      let length = 0;
      chunks.forEach((c) => { length += c.length; });
      const samples = new Float32Array(length);
      let offset = 0;
      chunks.forEach((c) => {
        samples.set(c, offset);
        offset += c.length;
      });
      const buffer = new ArrayBuffer(44 + samples.length * 2);
      const view = new DataView(buffer);
      const writeStr = (pos, str) => {
        for (let i = 0; i < str.length; i += 1) view.setUint8(pos + i, str.charCodeAt(i));
      };
      writeStr(0, "RIFF");
      view.setUint32(4, 36 + samples.length * 2, true);
      writeStr(8, "WAVE");
      writeStr(12, "fmt ");
      view.setUint32(16, 16, true);
      view.setUint16(20, 1, true);
      view.setUint16(22, 1, true);
      view.setUint32(24, sampleRate, true);
      view.setUint32(28, sampleRate * 2, true);
      view.setUint16(32, 2, true);
      view.setUint16(34, 16, true);
      writeStr(36, "data");
      view.setUint32(40, samples.length * 2, true);
      let pos = 44;
      for (let i = 0; i < samples.length; i += 1) {
        let s = Math.max(-1, Math.min(1, samples[i]));
        view.setInt16(pos, s < 0 ? s * 0x8000 : s * 0x7fff, true);
        pos += 2;
      }
      return new Blob([buffer], { type: "audio/wav" });
    },
    submitClone() {
      if (!this.canSubmitClone) {
        this.$message.warning(this.cloneSendTitle);
        return;
      }
      this.submitting = true;
      officialTts.uploadClone(this.cloneFile, this.cloneName || "我的音色", () => {
        this.submitting = false;
        this.$message.success("已提交复刻");
        this.clearCloneFile();
        this.reload();
      }, (err) => {
        this.submitting = false;
        this.$message.error(this.apiMsg(err, "复刻上传请求失败"));
        this.reload();
      });
    },
    createDesign() {
      if (!this.canSubmitDesign) {
        this.$message.warning(this.sendTitle);
        return;
      }
      const preview = (this.previewText || DEFAULT_PREVIEW).trim() || DEFAULT_PREVIEW;
      this.submitting = true;
      officialTts.createVoice({
        kind: "design",
        name: this.designPrompt.trim().slice(0, 24),
        prompt: this.designPrompt.trim(),
        previewText: preview,
      }, () => {
        this.submitting = false;
        this.$message.success("已登记设计任务");
        this.designPrompt = "";
        this.reload();
      }, (err) => {
        this.submitting = false;
        this.$message.error(this.apiMsg(err, "设计请求失败"));
      });
    },
    goSynth(row) {
      if (!this.canGoSynth(row)) {
        this.$message.warning("音色尚未生成 ID，请稍后再试");
        return;
      }
      if (row.status !== "available") {
        this.$message.info("音色仍在处理中，已跳转合成页；若合成失败请稍后重试");
      }
      const query = {
        voice: row.upstreamVoiceId,
        text: DEFAULT_PREVIEW,
      };
      const agentId = this.agentId || this.$route.query.agentId;
      if (agentId) query.agentId = agentId;
      this.$router.push({ path: "/official-tts/dubbing", query });
    },
    rename(row) {
      this.$prompt("请输入新的音色名称", "重命名", {
        inputValue: row.name || "",
        inputPattern: /\S+/,
        inputErrorMessage: "名称不能为空",
      }).then(({ value }) => {
        officialTts.renameVoice(row.id, value.trim(), () => {
          this.$message.success("已重命名");
          this.reload();
        }, (err) => this.$message.error(this.apiMsg(err, "重命名失败")));
      }).catch(() => {});
    },
    remove(row) {
      this.$confirm("资产删除后无法找回，请谨慎操作。", "你确认删除该资产吗？", {
        confirmButtonText: "删除",
        cancelButtonText: "取消",
        customClass: "ot-delete-confirm",
        confirmButtonClass: "ot-delete-confirm__danger",
        cancelButtonClass: "ot-delete-confirm__cancel",
      })
        .then(() => {
          officialTts.deleteVoice(row.id, () => {
            if (this.playingId === row.id) this.stopPlay();
            this.$message.success("已删除");
            this.reload();
          }, (err) => this.$message.error(this.apiMsg(err, "删除失败，可能仍在使用")));
        })
        .catch(() => {});
    },
    togglePlay(row) {
      if (!this.canPlay(row)) {
        this.$message.warning("该音色暂无预览音频");
        return;
      }
      if (this.playingId === row.id) {
        const el = this.$refs.audioEl;
        if (!el) return;
        if (el.paused) el.play().catch(() => {});
        else el.pause();
        return;
      }
      this.loadingId = row.id;
      officialTts.fetchVoicePreview(row.id, (blob) => {
        this.loadingId = null;
        this.stopPlay(false);
        this.playUrl = URL.createObjectURL(blob);
        this.playingId = row.id;
        this.$nextTick(() => {
          const el = this.$refs.audioEl;
          if (!el) return;
          el.src = this.playUrl;
          el.play().catch(() => this.$message.error("播放失败"));
        });
      }, () => {
        this.loadingId = null;
        this.$message.error("预览音频加载失败");
      });
    },
    onAudioTime() {
      const el = this.$refs.audioEl;
      if (!el) return;
      this.playCurrent = el.currentTime || 0;
    },
    onAudioMeta() {
      const el = this.$refs.audioEl;
      if (!el) return;
      this.playDuration = el.duration || 0;
    },
    onAudioEnded() {
      this.playPaused = true;
    },
    stopPlay(clearId = true) {
      const el = this.$refs.audioEl;
      if (el) {
        el.pause();
        el.removeAttribute("src");
        el.load();
      }
      if (this.playUrl) URL.revokeObjectURL(this.playUrl);
      this.playUrl = "";
      this.playPaused = true;
      if (clearId) this.playingId = null;
    },
  },
};
</script>
