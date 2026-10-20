<template>
  <div class="ot-page">
  <OfficialTtsStudioShell
    :active-tab="mode"
    :warning="actionBlockedReason"
    :compact="mode === 'clone' && !!cloneFile"
  >
    <template #hero>
      <h1>{{ heroTitle }}</h1>
    </template>

    <template #composer>
      <template v-if="mode === 'design'">
        <el-input
          type="textarea"
          class="ot-composer__textarea"
          :rows="2"
          v-model="designPrompt"
          resize="none"
          placeholder="描述你想要的音色，例如：温柔女声，语速适中，适合有声书旁白"
        />
        <div class="ot-composer__toolbar">
          <div class="ot-composer__tools">
            <button type="button" class="ot-tool" @click="openPreviewDialog">
              <i class="el-icon-document" />
              <span>文本预览</span>
            </button>
          </div>
          <div class="ot-composer__actions">
            <button
              type="button"
              class="ot-btn-send"
              :class="{ 'is-ready': canSubmitDesign }"
              :disabled="!canSubmitDesign || submitting"
              :title="sendTitle"
              @click="createDesign"
            >
              <i class="el-icon-top" />
            </button>
          </div>
        </div>
      </template>

      <template v-else>
        <div v-if="recording" class="ot-recorder">
          <button type="button" class="ot-recorder__stop" title="结束录制" @click="stopRecord(false)">
            <span class="ot-recorder__stop-square" />
          </button>
          <div class="ot-recorder__wave">
            <span
              v-for="(h, i) in recordBars"
              :key="i"
              class="ot-recorder__bar"
              :class="{ 'is-active': i <= recordIndex }"
              :style="{ height: h + '%' }"
            />
          </div>
          <span class="ot-recorder__time">{{ recordClock }} / {{ maxRecordClock }}</span>
          <button type="button" class="ot-recorder__close" title="取消录制" @click="stopRecord(true)">
            <i class="el-icon-close" />
          </button>
        </div>

        <template v-else>
          <div v-if="cloneFile" class="ot-clone-file">
            <div class="ot-clone-file__thumb">
              <span class="ot-clone-file__bar is-1" />
              <span class="ot-clone-file__bar is-2" />
              <span class="ot-clone-file__bar is-3" />
              <span class="ot-clone-file__bar is-4" />
              <span class="ot-clone-file__bar is-5" />
            </div>
            <div class="ot-clone-file__main">
              <p class="ot-clone-file__title" :title="cloneFileTooltip">{{ cloneFileTitle }}</p>
              <p class="ot-clone-file__sub">音频</p>
            </div>
            <button
              type="button"
              class="ot-clone-file__clear"
              title="移除后重新上传或录制"
              @click="clearCloneFile"
            >
              <i class="el-icon-close" />
            </button>
          </div>

          <div v-else class="ot-clone-pick">
            <input
              ref="cloneFileInput"
              type="file"
              accept="audio/wav,audio/x-wav,.wav,audio/*"
              class="ot-clone-pick__hidden"
              @change="onCloneFilePicked"
            />
            <button
              type="button"
              class="ot-clone-pick__card"
              :disabled="!actionsEnabled"
              @click="triggerCloneUpload"
            >
              <i class="el-icon-upload2" />
              <span>上传声音</span>
            </button>
            <span class="ot-clone-pick__or">or</span>
            <button
              type="button"
              class="ot-clone-pick__card"
              :disabled="!actionsEnabled"
              @click="toggleRecord"
            >
              <i class="el-icon-microphone" />
              <span>录制声音</span>
            </button>
          </div>

          <div class="ot-composer__toolbar">
            <div class="ot-composer__tools">
              <button type="button" class="ot-tool" @click="openPreviewDialog">
                <i class="el-icon-document" />
                <span>文本预览</span>
              </button>
            </div>
            <div class="ot-composer__actions">
              <button
                type="button"
                class="ot-btn-send"
                :class="{ 'is-ready': canSubmitClone }"
                :disabled="!canSubmitClone || submitting"
                :title="cloneSendTitle"
                @click="submitClone"
              >
                <i class="el-icon-top" />
              </button>
            </div>
          </div>
        </template>
      </template>
    </template>

    <template #bottom>
      <div class="ot-bottom__bar">
        <div class="ot-bottom__tabs ot-bottom__tabs--text">
          <button type="button" class="ot-bottom__tab is-active">资产</button>
        </div>
      </div>

      <div v-if="showGenerating" class="ot-generating" role="status" aria-live="polite">
        <span class="ot-generating__text">
          <i class="el-icon-loading" />
          生成中，请等待…
        </span>
      </div>

      <div class="ot-voice-asset-list" v-loading="loading">
        <div v-if="!loading && !filteredVoices.length && !showGenerating" class="ot-empty">
          {{ mode === "design" ? "暂无音色设计资产" : "暂无音色复刻资产" }}
        </div>
        <div
          v-for="(row, idx) in filteredVoices"
          :key="row.id"
          class="ot-voice-asset"
        >
          <button
            type="button"
            class="ot-voice-asset__avatar"
            :class="avatarClass(row, idx)"
            :disabled="!canPlay(row) || loadingId === row.id"
            :title="canPlay(row) ? '试听' : '暂无预览'"
            @click="togglePlay(row)"
          >
            <i :class="playingId === row.id && !playPaused ? 'el-icon-video-pause' : 'el-icon-video-play'" />
          </button>
          <div class="ot-voice-asset__main">
            <p class="ot-voice-asset__title">
              {{ voiceTitle(row) }}
              <i
                v-if="row.errorMsg && !String(row.errorMsg).startsWith('task:')"
                class="el-icon-info"
                :title="row.errorMsg"
              />
            </p>
            <p class="ot-voice-asset__sub">
              {{ row.kind === "clone" ? "我的复刻" : "我的设计" }}
              <template v-if="row.upstreamVoiceId"> · 音色 ID {{ shortVoiceId(row.upstreamVoiceId) }}</template>
              <template v-if="row.status !== 'available'"> · {{ statusLabel(row.status) }}</template>
            </p>
          </div>
          <div class="ot-voice-asset__right">
            <span class="ot-voice-asset__time">{{ formatTime(row.createdAt) }}</span>
            <div class="ot-voice-asset__actions">
              <button
                type="button"
                class="ot-voice-asset__icon-btn"
                :disabled="!canGoSynth(row)"
                :title="canGoSynth(row) ? '去合成' : '音色尚未就绪'"
                aria-label="去合成"
                @click="goSynth(row)"
              >
                <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
                  <path d="M2 9.3V6.7M5 12V4M8 10.4V5.6M11 12V4M14 9.3V6.7" />
                </svg>
              </button>
              <button
                type="button"
                class="ot-voice-asset__icon-btn"
                title="重命名"
                aria-label="重命名"
                @click="rename(row)"
              >
                <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
                  <path d="M11.1 2.4l2.5 2.5-7.9 7.9-2.9.7.7-2.9 7.6-8.2z" />
                  <path d="M9.7 3.8l2.5 2.5" />
                </svg>
              </button>
              <button
                type="button"
                class="ot-voice-asset__icon-btn is-danger"
                title="删除"
                aria-label="删除"
                @click="remove(row)"
              >
                <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
                  <path d="M2.8 4.4h10.4" />
                  <path d="M6.1 4.4V2.9h3.8v1.5" />
                  <path d="M4.2 4.4l.6 8.6h6.4l.6-8.6" />
                  <path d="M6.7 6.9v3.7M9.3 6.9v3.7" />
                </svg>
              </button>
            </div>
          </div>
        </div>
        <p v-if="filteredVoices.length" class="ot-voice-asset__more">没有更多了</p>
        <audio
          ref="audioEl"
          class="ot-asset__audio-el"
          @timeupdate="onAudioTime"
          @loadedmetadata="onAudioMeta"
          @ended="onAudioEnded"
          @pause="playPaused = true"
          @play="playPaused = false"
        />
      </div>
    </template>
  </OfficialTtsStudioShell>

    <el-dialog
      title="预览文本"
      :visible.sync="previewDialogVisible"
      width="560px"
      custom-class="ot-preview-text-dialog"
      append-to-body
      :close-on-click-modal="false"
    >
      <el-input
        type="textarea"
        v-model="previewDraft"
        :rows="8"
        resize="none"
        maxlength="230"
        :placeholder="previewPlaceholder"
      />
      <div class="ot-preview-text-dialog__bar">
        <span>{{ previewDraftLength }}/230字符</span>
        <button type="button" class="ot-preview-text-dialog__clear" title="清空" @click="previewDraft = ''">
          <i class="el-icon-delete" />
        </button>
      </div>
      <span slot="footer">
        <button type="button" class="ot-preview-text-dialog__ok" @click="confirmPreviewText">确认</button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import OfficialTtsStudioShell from "@/components/OfficialTtsStudioShell.vue";
import officialTts from "@/apis/module/officialTts";

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
      return this.mode === "design"
        ? "欢迎体验音色设计，今天想创造什么声音？"
        : "欢迎体验音色复刻，今天想复刻什么？";
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
        return "官方增强功能尚未启用（总开关关闭或未加入灰度名单），因此无法试用。";
      }
      if (this.caps.pricingStatus === "pricing_pending") {
        return "该操作尚未配置并发布有效售价，无法发起收费/试用调用。";
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
      }, () => { this.loading = false; });
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
