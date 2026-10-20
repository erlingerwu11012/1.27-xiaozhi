<template>
  <div class="ot-page">
  <OfficialTtsStudioShell active-tab="synth" :warning="caps ? actionBlockedReason : ''">
    <template #hero>{{ $t('xn.tts.heroSynth') }}</template>

    <template #composer>
      <div
        ref="editor"
        class="ot-composer__editor"
        :class="{ 'is-empty': !form.text }"
        contenteditable="true"
        role="textbox"
        aria-multiline="true"
        :aria-label="$t('xn.tts.synthLabel')"
        :data-placeholder="$t('xn.tts.synthPlaceholder')"
        @input="onEditorInput"
        @keydown="onEditorKeydown"
        @paste="onEditorPaste"
        @mouseup="saveEditorRange"
        @keyup="saveEditorRange"
        @focus="saveEditorRange"
      />
      <div class="ot-composer__bar">
        <div class="ot-composer__tools">
          <el-popover v-model="tagMenuVisible" placement="bottom-start" trigger="click" popper-class="ot-tag-popper" :visible-arrow="false">
            <div class="ot-tag-cascade">
              <div class="ot-tag-panel ot-tag-panel--root">
                <div class="ot-tag-panel__title">{{ $t('xn.tts.toneTags') }}</div>
                <button v-for="cat in tagCategories" :key="cat.id" type="button" class="ot-tag-panel__row"
                  :class="{ 'is-active': tagMenuHover === cat.id }" @mouseenter="tagMenuHover = cat.id" @click="tagMenuHover = cat.id">
                  <span>{{ cat.name }}</span>
                  <xn-icon name="chevron" />
                </button>
              </div>
              <div class="ot-tag-panel ot-tag-panel--sub">
                <div class="ot-tag-panel__title">{{ activeTagCategoryName }}</div>
                <div class="ot-tag-panel__scroll">
                  <button v-for="item in activeTagItems" :key="item.code" type="button" class="ot-tag-panel__item" @click="pickToneTag(item)">{{ item.label }}</button>
                </div>
              </div>
            </div>
            <button slot="reference" type="button" class="ot-tool" :class="{ 'is-open': tagMenuVisible }">
              <xn-icon name="plus" /><span>{{ $t('xn.tts.toneTags') }}</span>
            </button>
          </el-popover>

          <button type="button" class="ot-tool" :title="$t('xn.tts.pickVoice')" @click="voiceLibVisible = true">
            <xn-icon name="voice" /><span class="ot-tool__val">{{ currentVoiceLabel }}</span><xn-icon name="chevronDown" class="ot-tool__caret" />
          </button>

          <el-popover v-model="langMenuVisible" placement="bottom-start" trigger="click" popper-class="ot-lang-popper" :visible-arrow="false">
            <div class="ot-lang-menu">
              <div class="ot-lang-col">
                <div class="ot-lang-col__title">{{ $t('xn.tts.language') }}</div>
                <div class="ot-lang-col__scroll">
                  <button v-for="l in languageOptions" :key="l.code" type="button" class="ot-lang-col__item"
                    :class="{ 'is-active': form.lang === l.code }" @click="selectLanguage(l)">
                    <span>{{ l.label }}</span><xn-icon v-if="form.lang === l.code" name="check" />
                  </button>
                </div>
              </div>
              <div v-if="form.lang === 'zh'" class="ot-lang-col ot-lang-col--dialect">
                <div class="ot-lang-col__title">{{ $t('xn.tts.dialect') }}</div>
                <div class="ot-lang-col__scroll">
                  <button v-for="d in dialectOptions" :key="d" type="button" class="ot-lang-col__item"
                    :class="{ 'is-active': form.dialect === d }" @click="selectDialect(d)">
                    <span>{{ d }}</span><xn-icon v-if="form.dialect === d" name="check" />
                  </button>
                </div>
              </div>
            </div>
            <button slot="reference" type="button" class="ot-tool" :class="{ 'is-open': langMenuVisible }">
              <xn-icon name="globe" /><span>{{ langDisplayLabel }}</span><xn-icon name="chevronDown" class="ot-tool__caret" />
            </button>
          </el-popover>

          <el-popover placement="bottom" width="280" trigger="click">
            <div class="ot-popover-row">
              <span>{{ $t('xn.tts.volume') }}</span>
              <el-slider v-model="form.volume" :min="0" :max="100" class="ot-popover-row__slider" />
              <span class="xn-num">{{ form.volume }}</span>
            </div>
            <button slot="reference" type="button" class="ot-tool"><span class="xn-muted">{{ $t('xn.tts.volume') }}</span><span class="xn-num">{{ form.volume }}</span></button>
          </el-popover>

          <el-popover placement="bottom" width="280" trigger="click">
            <div class="ot-popover-row">
              <span>{{ $t('xn.tts.rate') }}</span>
              <el-slider v-model="form.rate" :min="0.5" :max="2" :step="0.1" class="ot-popover-row__slider" />
              <span class="xn-num">{{ form.rate.toFixed(1) }}x</span>
            </div>
            <button slot="reference" type="button" class="ot-tool"><span class="xn-muted">{{ $t('xn.tts.rate') }}</span><span class="xn-num">{{ form.rate.toFixed(1).replace(/\.0$/, "") }}x</span></button>
          </el-popover>

          <el-popover placement="bottom" width="300" trigger="click">
            <div class="ot-popover-row">
              <span>{{ $t('xn.tts.format') }}</span>
              <el-select v-model="form.format" size="small" class="ot-popover-row__select">
                <el-option v-for="f in formats" :key="f" :label="f.toUpperCase()" :value="f" />
              </el-select>
            </div>
            <div v-if="form.format === 'opus'" class="ot-popover-row">
              <span>{{ $t('xn.tts.bitRate') }}</span>
              <el-input-number v-model="form.bitRate" :min="6" :max="510" size="small" />
            </div>
            <p class="ot-popover-note">{{ $t('xn.tts.formatNote') }}</p>
            <button slot="reference" type="button" class="ot-tool"><xn-icon name="download" /><span>{{ form.format.toUpperCase() }}</span></button>
          </el-popover>
        </div>
        <span class="xn-toolbar__grow"></span>
        <span class="ot-count-chars xn-muted xn-num">{{ $t('xn.tts.chars', { n: textLength }) }}</span>
        <el-button type="primary" :disabled="!canSubmit || submitting" :loading="submitting" :title="sendTitle" @click="generate">
          {{ $t('xn.tts.generate') }}
        </el-button>
      </div>
    </template>

    <template #bottom>
      <div class="ot-subtabs" role="tablist">
        <button type="button" role="tab" class="ot-subtabs__tab" :class="{ 'is-active': bottomTab === 'inspire' }"
          :aria-selected="String(bottomTab === 'inspire')" @click="bottomTab = 'inspire'">{{ $t('xn.tts.inspire') }}</button>
        <button type="button" role="tab" class="ot-subtabs__tab" :class="{ 'is-active': bottomTab === 'jobs' }"
          :aria-selected="String(bottomTab === 'jobs')" @click="bottomTab = 'jobs'">
          {{ $t('xn.tts.myJobs') }} <span class="ot-count xn-num">{{ jobs.length }}</span>
        </button>
      </div>

      <div v-if="bottomTab === 'inspire'" class="ot-ideas">
        <button v-for="(item, idx) in inspireCards" :key="idx" type="button" class="ot-idea" @click="applyInspire(item)">
          <span class="ot-idea__title">{{ item.title }}</span>
          <span class="ot-idea__meta">{{ item.meta }}</span>
          <span class="ot-idea__text">{{ item.text }}</span>
          <span class="ot-idea__use">{{ $t('xn.tts.useIdea') }}</span>
        </button>
      </div>

      <section v-else class="xn-panel xn-panel--flush ot-list">
        <div class="xn-panel__head">
          <h2 class="xn-panel__title">{{ $t('xn.tts.myJobs') }}</h2>
          <span class="ot-list__head-right">
            <span v-if="showGenerating" class="xn-tag xn-tag--lake" role="status"><i class="el-icon-loading"></i>{{ $t('xn.tts.generatingN', { n: pendingJobs.length || 1 }) }}</span>
            <demo-tag />
            <el-button type="text" @click="reloadJobs"><xn-icon name="refresh" /> {{ $t('xn.billing.refresh') }}</el-button>
          </span>
        </div>
        <xn-empty v-if="jobsFailed && !jobs.length" error @retry="reloadJobs" />
        <el-table v-else :data="jobs" v-loading="!jobsLoaded" row-key="id" class="ot-table" :row-class-name="jobRowClass">
          <el-table-column :label="$t('xn.tts.colContent')" min-width="240">
            <template slot-scope="{ row }">
              <div class="ot-job">
                <span class="ot-job__title xn-clip" :title="jobTitle(row)">{{ jobTitle(row) }}</span>
                <span class="ot-job__meta xn-muted">
                  <span>{{ voiceLabel(row) }}</span>
                  <span>{{ $t('xn.tts.volume') }} {{ jobVolume(row) }}</span>
                  <span>{{ jobRateLabel(row) }}</span>
                  <span>{{ jobLangLabel(row) }}</span>
                  <span>{{ formatJobTime(row.createdAt) }}</span>
                </span>
              </div>
            </template>
          </el-table-column>
          <el-table-column :label="$t('xn.tts.colStatus')" min-width="100">
            <template slot-scope="{ row }">
              <span class="xn-tag" :class="jobStatusClass(row.status)">{{ jobStatusLabel(row.status) }}</span>
              <el-tooltip v-if="row.errorMsg" :content="row.errorMsg" placement="top" popper-class="xn-tip-wide">
                <button type="button" class="ot-info" :aria-label="row.errorMsg"><xn-icon name="info" /></button>
              </el-tooltip>
            </template>
          </el-table-column>
          <el-table-column :label="$t('xn.tts.colListen')" min-width="230">
            <template slot-scope="{ row }">
              <div class="ot-player" :class="{ 'is-disabled': row.status !== 'done' }" @click.stop>
                <button type="button" class="ot-play" :class="{ 'is-on': playingId === row.id && !playPaused }"
                  :disabled="row.status !== 'done' || loadingId === row.id"
                  :aria-label="playingId === row.id && !playPaused ? $t('xn.tts.pause') : $t('xn.tts.play')"
                  @click="togglePlay(row)">
                  <i v-if="loadingId === row.id" class="el-icon-loading"></i>
                  <svg v-else-if="playingId === row.id && !playPaused" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14M16 5v14" /></svg>
                  <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l10-6.5z" /></svg>
                </button>
                <span class="ot-player__time xn-num">{{ playingId === row.id ? formatClock(playCurrent) : '00:00' }}</span>
                <div class="ot-player__seek" @click="onSeekClick(row, $event)">
                  <div class="ot-player__fill" :style="{ width: playingId === row.id ? playProgress + '%' : '0%' }" />
                </div>
                <span class="ot-player__time xn-num">{{ playingId === row.id ? formatClock(playDuration) : '--:--' }}</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column :label="$t('xn.tts.colActions')" min-width="200" align="right">
            <template slot-scope="{ row }">
              <el-button type="text" :disabled="row.status !== 'done'" @click="download(row)">{{ $t('xn.tts.download') }}</el-button>
              <el-button v-if="isPending(row)" type="text" @click="cancelJob(row)">{{ $t('xn.tts.cancelJob') }}</el-button>
              <el-button v-else type="text" @click="editJob(row)">{{ $t('xn.tts.reuse') }}</el-button>
              <el-button type="text" class="ot-danger" :disabled="isPending(row)" @click="removeJob(row)">{{ $t('xn.tts.delete') }}</el-button>
            </template>
          </el-table-column>
          <template slot="empty">
            <xn-empty icon="mic" :title="$t('xn.tts.emptyJobs')" :description="$t('xn.tts.emptyJobsDesc')" />
          </template>
        </el-table>
        <audio ref="audioEl" class="ot-audio-el" @timeupdate="onAudioTime" @loadedmetadata="onAudioMeta" @ended="onAudioEnded"
          @pause="playPaused = true" @play="playPaused = false" />
      </section>
    </template>
  </OfficialTtsStudioShell>

    <OfficialTtsVoiceLibrary
      :visible.sync="voiceLibVisible"
      :value="form.voice"
      :official-voices="verified"
      @confirm="onVoicePicked"
    />
  </div>
</template>

<script>
import OfficialTtsStudioShell from "@/components/OfficialTtsStudioShell.vue";
import OfficialTtsVoiceLibrary from "@/components/OfficialTtsVoiceLibrary.vue";
import officialTts from "@/apis/module/officialTts";
import { isMockMode } from "@/mock/config";

const JOB_STATUS = {
  queued: ["排队中", "xn-tag--lake"],
  running: ["生成中", "xn-tag--lake"],
  uncertain: ["处理中", "xn-tag--warning"],
  done: ["已完成", "xn-tag--success"],
  failed: ["失败", "xn-tag--danger"],
  error: ["失败", "xn-tag--danger"],
  canceled: ["已取消", "xn-tag--muted"],
  cancelled: ["已取消", "xn-tag--muted"],
};

/** 请求层对业务错误（code≠0）只弹出提示、不回调页面；超过这个时间仍无响应就显示失败状态，避免一直加载 */
const NO_REPLY_MS = 10000;

const DEFAULT_DESIGN_TEXT = "欢迎使用文本朗读，这是一段设计的音色。";

const TAG_LABELS = {
  sad: "悲伤",
  amazed: "惊叹",
  "deep and loud shouting": "深沉大声呐喊",
  trembling: "颤抖",
  angry: "愤怒",
  excited: "兴奋",
  sarcastic: "讽刺",
  curious: "好奇",
  "like dracula": "德古拉风格 (低沉、阴森)",
  bored: "无聊",
  tired: "疲惫",
  scornful: "轻蔑",
  shouting: "呐喊",
  asmr: "ASMR",
  panicked: "惊慌",
  mischievously: "调皮",
  empathetic: "共情",
  whispers: "耳语",
  reluctantly: "不情愿",
  crying: "哭泣",
  serious: "严肃",
  "very slowly": "很慢",
  "very fast": "很快",
  gasp: "倒吸一口气",
  sighing: "叹息",
  "clears throat": "清喉",
  giggles: "咯咯笑",
  laughing: "大笑",
  cough: "咳嗽",
  snorts: "哼声",
};

const EMOTION_TAGS = [
  { code: "sad", label: "悲伤", kind: "emotion" },
  { code: "amazed", label: "惊叹", kind: "emotion" },
  { code: "deep and loud shouting", label: "深沉大声呐喊", kind: "emotion" },
  { code: "trembling", label: "颤抖", kind: "emotion" },
  { code: "angry", label: "愤怒", kind: "emotion" },
  { code: "excited", label: "兴奋", kind: "emotion" },
  { code: "sarcastic", label: "讽刺", kind: "emotion" },
  { code: "curious", label: "好奇", kind: "emotion" },
  { code: "like dracula", label: "德古拉风格 (低沉、阴森)", kind: "emotion" },
  { code: "bored", label: "无聊", kind: "emotion" },
  { code: "tired", label: "疲惫", kind: "emotion" },
  { code: "scornful", label: "轻蔑", kind: "emotion" },
  { code: "shouting", label: "呐喊", kind: "emotion" },
  { code: "asmr", label: "ASMR", kind: "emotion" },
  { code: "panicked", label: "惊慌", kind: "emotion" },
  { code: "mischievously", label: "调皮", kind: "emotion" },
  { code: "empathetic", label: "共情", kind: "emotion" },
  { code: "whispers", label: "耳语", kind: "emotion" },
  { code: "reluctantly", label: "不情愿", kind: "emotion" },
  { code: "crying", label: "哭泣", kind: "emotion" },
  { code: "serious", label: "严肃", kind: "emotion" },
  { code: "very slowly", label: "很慢", kind: "emotion" },
  { code: "very fast", label: "很快", kind: "emotion" },
];

const ACTION_TAGS = [
  { code: "gasp", label: "倒吸一口气", kind: "action" },
  { code: "sighing", label: "叹息", kind: "action" },
  { code: "clears throat", label: "清喉", kind: "action" },
  { code: "giggles", label: "咯咯笑", kind: "action" },
  { code: "laughing", label: "大笑", kind: "action" },
  { code: "cough", label: "咳嗽", kind: "action" },
  { code: "snorts", label: "哼声", kind: "action" },
];

const LABEL_TO_CODE = {};
[...EMOTION_TAGS, ...ACTION_TAGS].forEach((t) => {
  LABEL_TO_CODE[t.label] = t.code;
});
// 兼容旧文案
LABEL_TO_CODE["惊讶"] = "amazed";
LABEL_TO_CODE["笑着说"] = "laughing";
LABEL_TO_CODE["德古拉风格"] = "like dracula";
LABEL_TO_CODE["德古拉风格 (低沉、阴森)"] = "like dracula";

/** language_hints 官方取值 */
const LANGUAGE_OPTIONS = [
  { code: "zh", label: "中文" },
  { code: "en", label: "英语" },
  { code: "ja", label: "日语" },
  { code: "ko", label: "韩语" },
  { code: "ru", label: "俄语" },
  { code: "fr", label: "法语" },
  { code: "de", label: "德语" },
  { code: "pt", label: "葡萄牙语" },
  { code: "th", label: "泰语" },
  { code: "id", label: "印尼语" },
  { code: "vi", label: "越南语" },
  { code: "es", label: "西班牙语" },
  { code: "it", label: "意大利语" },
  { code: "ms", label: "马来语" },
  { code: "fil", label: "菲律宾语" },
  { code: "ar", label: "阿拉伯语" },
];

/** 中文方言：经 instruction「请用X表达」控制（官方约定） */
const DIALECT_OPTIONS = [
  "普通话",
  "广东话",
  "重庆话",
  "东北话",
  "甘肃话",
  "贵州话",
  "浙江话",
  "河北话",
  "河南话",
  "湖北话",
  "湖南话",
  "江西话",
  "宁波话",
  "宁夏话",
  "青岛话",
  "陕西话",
  "山西话",
  "山东话",
  "上海话",
  "四川话",
  "云南话",
];

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** 界面中文【标签】 / 官方 [code] → 合成用官方方括号标签 */
function toOfficialSynthesisText(text) {
  let s = String(text || "");
  s = s.replace(/【([^】]+)】/g, (_, label) => {
    const code = LABEL_TO_CODE[label.trim()];
    return code ? `[${code}]` : "";
  });
  // 已是官方标签则保留；未知中文旁白已剥掉，避免被念出来
  return s.replace(/\u200b/g, "");
}

/** 官方 [code] → 界面展示用【中文】 */
function toDisplayText(text) {
  return String(text || "").replace(/\[([^\]]+)\]/g, (_, code) => {
    const label = TAG_LABELS[code] || TAG_LABELS[code.toLowerCase()];
    return label ? `【${label}】` : `[${code}]`;
  });
}

export default {
  name: "OfficialTtsDubbing",
  components: { OfficialTtsStudioShell, OfficialTtsVoiceLibrary },
  data() {
    return {
      caps: null,
      verified: [
        { code: "longanlingxi", name: "龙安灵汐" },
        { code: "longanqian", name: "龙安千" },
      ],
      myVoiceNames: {},
      voiceLibVisible: false,
      formats: ["wav", "mp3", "pcm", "opus"],
      controlTags: ["sad", "amazed", "angry", "excited", "serious", "laughing"],
      tagMenuVisible: false,
      tagMenuHover: "emotion",
      langMenuVisible: false,
      savedRange: null,
      form: {
        voice: "longanlingxi",
        text: "",
        format: "wav",
        bitRate: 32,
        volume: 50,
        rate: 1,
        lang: "zh",
        dialect: "普通话",
        instruction: "",
      },
      jobs: [],
      jobsLoaded: false,
      jobsFailed: false,
      mock: isMockMode(),
      submitting: false,
      pollTimer: null,
      bottomTab: "inspire",
      playingId: null,
      playUrl: "",
      playCurrent: 0,
      playDuration: 0,
      playPaused: true,
      loadingId: null,
      inspireCards: [
        {
          title: "有声书情感叙事",
          meta: "温柔女声 · 故事旁白",
          swatch: "ot-card__swatch--rose",
          text: "夜色渐深，窗外的风轻轻拂过树梢。她合上书本，轻声说道：明天会更好。",
        },
        {
          title: "智能客服问候",
          meta: "清晰普通话 · 服务场景",
          swatch: "",
          text: "您好，欢迎致电智播台客服中心。请问有什么可以帮您？",
        },
        {
          title: "儿童故事开场",
          meta: "活泼童趣 · 睡前故事",
          swatch: "ot-card__swatch--warm",
          text: "从前有一座会发光的小森林，里面住着会说话的小狐狸和爱唱歌的星星。",
        },
        {
          title: "新闻播报风格",
          meta: "沉稳旁白 · 资讯播报",
          swatch: "ot-card__swatch--cool",
          text: "今日焦点：人工智能语音合成技术持续进步，正广泛应用于教育、娱乐与客服场景。",
        },
        {
          title: "产品介绍短片",
          meta: "专业旁白 · 营销文案",
          swatch: "ot-card__swatch--warm",
          text: "一键生成自然流畅的人声音频，让你的内容更快抵达听众。现在就开始体验吧。",
        },
        {
          title: "诗词朗诵",
          meta: "韵律感 · 文学朗读",
          swatch: "ot-card__swatch--rose",
          text: "床前明月光，疑是地上霜。举头望明月，低头思故乡。",
        },
      ],
    };
  },
  computed: {
    actionBlockedReason() {
      if (!this.caps) return "当前不可用：正在加载能力状态…";
      if (this.caps.accessStatusText) return this.caps.accessStatus === "ready" ? "" : this.caps.accessStatusText;
      if (this.caps.enhancedEnabled === false) {
        return "官方语音功能尚未对你的账号开放，暂时无法使用合成。";
      }
      if (this.caps.pricingStatus === "pricing_pending") {
        return "该功能暂未开放计费，暂时无法使用。";
      }
      if (this.caps.customerCallable === false) return "当前不可用";
      if (this.caps.customerCallable !== true) return "当前不可用";
      return "";
    },
    actionsEnabled() {
      if (this.caps && this.caps.operations && this.caps.operations.synthesize) {
        return !!this.caps.operations.synthesize.callable;
      }
      return !this.actionBlockedReason;
    },
    textLength() {
      return Array.from(String(this.form.text || "").replace(/\[[^\]]+\]/g, "")).length;
    },
    canSubmit() {
      return this.actionsEnabled && !!this.form.text.trim();
    },
    sendTitle() {
      if (this.actionBlockedReason) return this.actionBlockedReason;
      if (!this.form.text.trim()) return "请先输入要合成的文本";
      return "生成配音";
    },
    playProgress() {
      if (!this.playDuration) return 0;
      return Math.min(100, (this.playCurrent / this.playDuration) * 100);
    },
    tagCategories() {
      // 与百炼控制台对齐：展示完整官方 CONTROL_TAGS，不收窄为 capabilities 短名单
      return [
        { id: "emotion", name: "情绪语气", items: EMOTION_TAGS.map((t) => ({ ...t })) },
        { id: "action", name: "声音动作", items: ACTION_TAGS.map((t) => ({ ...t })) },
      ];
    },
    activeTagItems() {
      const cat = this.tagCategories.find((c) => c.id === this.tagMenuHover);
      return (cat && cat.items) || [];
    },
    activeTagCategoryName() {
      const cat = this.tagCategories.find((c) => c.id === this.tagMenuHover);
      return (cat && cat.name) || "情绪语气";
    },
    languageOptions() {
      return LANGUAGE_OPTIONS;
    },
    dialectOptions() {
      return DIALECT_OPTIONS;
    },
    langDisplayLabel() {
      const lang = LANGUAGE_OPTIONS.find((l) => l.code === this.form.lang);
      const langName = (lang && lang.label) || this.form.lang || "中文";
      if (this.form.lang === "zh") {
        return `${langName} | ${this.form.dialect || "普通话"}`;
      }
      return langName;
    },
    currentVoiceLabel() {
      const code = this.form.voice;
      const hit = (this.verified || []).find((v) => v.code === code);
      if (hit) return hit.name;
      if (this.myVoiceNames[code]) return this.myVoiceNames[code];
      if (!code) return "选择音色";
      return code.length > 16 ? `${code.slice(0, 8)}…` : code;
    },
    pendingJobs() {
      const settled = ["done", "failed", "error", "canceled", "cancelled", "deleted"];
      return (this.jobs || []).filter((r) => !settled.includes(String((r && r.status) || "").toLowerCase()));
    },
    showGenerating() {
      return this.submitting || this.pendingJobs.length > 0;
    },
  },
  created() {
    officialTts.capabilities((res) => {
      const data = (res.data && res.data.data) || {};
      this.caps = data;
      if (data.verifiedVoices) this.verified = data.verifiedVoices;
      if (data.formatsExport) this.formats = data.formatsExport;
      if (data.controlTags) this.controlTags = data.controlTags;
      if (data.volume && data.volume.default != null) this.form.volume = data.volume.default;
      if (data.rate && data.rate.default != null) this.form.rate = data.rate.default;
      this.applyRouteVoice();
    }, () => {
      this.caps = this.caps || {};
      this.applyRouteVoice();
    });
    this.loadMyVoiceNames();
    this.reloadJobs();
  },
  watch: {
    "$route.query.voice"() {
      this.applyRouteVoice();
    },
    "$route.query.text"() {
      this.applyRouteVoice();
    },
    pendingJobs(val) {
      if (val.length) this.startPoll();
      else this.stopPoll();
    },
  },
  methods: {
    startPoll() {
      if (this.pollTimer) return;
      this.pollTimer = setInterval(() => this.reloadJobs(), 4000);
    },
    stopPoll() {
      if (this.pollTimer) {
        clearInterval(this.pollTimer);
        this.pollTimer = null;
      }
    },
    applyRouteVoice() {
      const voice = this.$route.query.voice;
      if (voice) {
        this.form.voice = String(voice);
        if (!this.verified.some((v) => v.code === voice) && !this.myVoiceNames[voice]) {
          this.myVoiceNames = { ...this.myVoiceNames, [voice]: "我的音色" };
        }
      }
      const text = this.$route.query.text;
      if (text) {
        this.$nextTick(() => this.setEditorHtmlFromText(String(text)));
      } else if (voice && !this.form.text) {
        this.$nextTick(() => this.setEditorHtmlFromText(DEFAULT_DESIGN_TEXT));
      }
    },
    loadMyVoiceNames() {
      officialTts.listVoices((res) => {
        const rows = (res.data && res.data.data) || [];
        const map = { ...this.myVoiceNames };
        rows.forEach((r) => {
          if (r.upstreamVoiceId) map[r.upstreamVoiceId] = r.name || r.upstreamVoiceId;
        });
        this.myVoiceNames = map;
      }, () => {});
    },
    onVoicePicked(item) {
      if (!item || !item.code) return;
      this.form.voice = item.code;
      if (item.name) {
        this.myVoiceNames = { ...this.myVoiceNames, [item.code]: item.name };
      }
      this.$message.success(`已选择音色：${item.name || item.code}`);
    },
    tagLabel(code) {
      return TAG_LABELS[code] || code;
    },
    saveEditorRange() {
      const sel = window.getSelection();
      if (!sel || sel.rangeCount === 0) return;
      const range = sel.getRangeAt(0);
      const editor = this.$refs.editor;
      if (editor && editor.contains(range.commonAncestorContainer)) {
        this.savedRange = range.cloneRange();
      }
    },
    syncTextFromEditor() {
      const editor = this.$refs.editor;
      if (!editor) return;
      this.form.text = this.buildApiTextFromEditor();
      this.syncInstructionFromText();
    },
    /** 编辑器 → 官方合成文本：芯片变成 [gasp]/ 普通字保留 */
    buildApiTextFromEditor() {
      const editor = this.$refs.editor;
      if (!editor) return "";
      const parts = [];
      const walk = (node) => {
        if (!node) return;
        if (node.nodeType === Node.TEXT_NODE) {
          parts.push((node.nodeValue || "").replace(/\u00a0/g, " ").replace(/\u200b/g, ""));
          return;
        }
        if (node.nodeType !== Node.ELEMENT_NODE) return;
        const el = node;
        if (el.classList && el.classList.contains("ot-tone-chip")) {
          const code = el.getAttribute("data-tag") || LABEL_TO_CODE[(el.textContent || "").replace(/[【】]/g, "").trim()];
          if (code) parts.push(`[${code}]`);
          return;
        }
        if (el.tagName === "BR") {
          parts.push("\n");
          return;
        }
        Array.from(el.childNodes || []).forEach(walk);
      };
      Array.from(editor.childNodes || []).forEach(walk);
      let text = parts.join("");
      if (text === "\n") text = "";
      return toOfficialSynthesisText(text);
    },
    syncInstructionFromText() {
      // 情绪/动作靠文本内官方标签生效，不再把中文标签塞进 instruction（否则无效且易混淆）
      this.form.instruction = "";
    },
    onEditorInput() {
      this.syncTextFromEditor();
      this.saveEditorRange();
    },
    onEditorKeydown() {
      this.$nextTick(() => this.saveEditorRange());
    },
    onEditorPaste(e) {
      e.preventDefault();
      const text = (e.clipboardData || window.clipboardData).getData("text/plain") || "";
      this.insertPlainText(text);
    },
    setEditorHtmlFromText(text) {
      const editor = this.$refs.editor;
      if (!editor) return;
      const apiText = toOfficialSynthesisText(text == null ? "" : String(text));
      if (!apiText) {
        editor.innerHTML = "";
        this.form.text = "";
        this.form.instruction = "";
        return;
      }
      const html = escapeHtml(apiText)
        .replace(/\n/g, "<br>")
        .replace(/\[([^\]]+)\]/g, (_, code) => {
          const label = TAG_LABELS[code] || code;
          return `<span class="ot-tone-chip" data-tag="${escapeHtml(code)}" contenteditable="false">【${escapeHtml(label)}】</span>`;
        });
      editor.innerHTML = html;
      this.form.text = apiText;
      this.form.instruction = "";
    },
    insertPlainText(text) {
      const editor = this.$refs.editor;
      if (!editor) return;
      editor.focus();
      this.restoreEditorRange();
      const sel = window.getSelection();
      if (!sel || sel.rangeCount === 0) {
        editor.appendChild(document.createTextNode(text));
      } else {
        const range = sel.getRangeAt(0);
        range.deleteContents();
        const node = document.createTextNode(text);
        range.insertNode(node);
        range.setStartAfter(node);
        range.collapse(true);
        sel.removeAllRanges();
        sel.addRange(range);
      }
      this.syncTextFromEditor();
      this.saveEditorRange();
    },
    restoreEditorRange() {
      const editor = this.$refs.editor;
      if (!editor) return;
      editor.focus();
      const sel = window.getSelection();
      if (this.savedRange && editor.contains(this.savedRange.commonAncestorContainer)) {
        sel.removeAllRanges();
        sel.addRange(this.savedRange);
        return;
      }
      const range = document.createRange();
      range.selectNodeContents(editor);
      range.collapse(false);
      sel.removeAllRanges();
      sel.addRange(range);
    },
    pickToneTag(item) {
      if (!item || !item.code) {
        this.$message.warning("无效的语气标签");
        return;
      }
      this.insertToneChip(item.code, item.label);
      this.tagMenuVisible = false;
    },
    insertToneChip(code, label) {
      const editor = this.$refs.editor;
      if (!editor) return;
      editor.focus();
      this.restoreEditorRange();
      const chip = document.createElement("span");
      chip.className = "ot-tone-chip";
      chip.contentEditable = "false";
      chip.setAttribute("data-tag", code);
      chip.textContent = `【${label || TAG_LABELS[code] || code}】`;
      const sel = window.getSelection();
      if (!sel || sel.rangeCount === 0) {
        editor.appendChild(chip);
      } else {
        const range = sel.getRangeAt(0);
        range.deleteContents();
        range.insertNode(chip);
        const spacer = document.createTextNode("\u200b");
        if (chip.nextSibling) {
          chip.parentNode.insertBefore(spacer, chip.nextSibling);
        } else {
          chip.parentNode.appendChild(spacer);
        }
        range.setStartAfter(spacer);
        range.collapse(true);
        sel.removeAllRanges();
        sel.addRange(range);
      }
      this.syncTextFromEditor();
      this.saveEditorRange();
    },
    apiMsg(err, fallback) {
      return (err && err.data && (err.data.msg || err.data.message)) || fallback;
    },
    reloadJobs() {
      clearTimeout(this.jobsGuard);
      this.jobsGuard = setTimeout(() => {
        if (!this.jobsLoaded) { this.jobsLoaded = true; this.jobsFailed = true; }
        if (!this.caps) this.caps = {};
      }, NO_REPLY_MS);
      officialTts.listJobs((res) => {
        clearTimeout(this.jobsGuard);
        this.jobs = (res.data && res.data.data) || [];
        this.jobsLoaded = true;
        this.jobsFailed = false;
      }, () => {
        this.jobsLoaded = true;
        this.jobsFailed = true;
      });
    },
    isPending(row) {
      return !["done", "failed", "error", "canceled", "cancelled", "deleted"].includes(String((row && row.status) || "").toLowerCase());
    },
    jobStatusLabel(status) {
      return (JOB_STATUS[status] || [status || "-"])[0];
    },
    jobStatusClass(status) {
      return (JOB_STATUS[status] || [null, "xn-tag--muted"])[1];
    },
    jobRowClass({ row }) {
      return this.playingId === row.id ? "is-playing" : "";
    },
    cancelJob(row) {
      this.$confirm("取消后不会生成音频，已冻结的点数会释放。", "取消这条配音？", {
        confirmButtonText: "取消任务",
        cancelButtonText: "继续生成",
        type: "warning",
      })
        .then(() => {
          officialTts.cancelJob(row.id, (res) => {
            const msg = res && res.data && res.data.msg;
            this.$message.success(msg && msg !== "success" ? msg : "已取消任务");
            this.reloadJobs();
          }, (err) => this.$message.error(this.apiMsg(err, "取消失败")));
        })
        .catch(() => {});
    },
    applyInspire(item) {
      this.setEditorHtmlFromText(item.text);
    },
    displaySynthesisText(text) {
      return toDisplayText(text);
    },
    parseRequest(row) {
      try {
        const req = typeof row.requestJson === "string" ? JSON.parse(row.requestJson) : row.requestJson;
        return req && typeof req === "object" ? req : {};
      } catch (e) {
        return {};
      }
    },
    jobTitle(row) {
      let raw = "";
      if (row.synthesisText) raw = row.synthesisText;
      else if (row.captionText) raw = row.captionText;
      else {
        const req = this.parseRequest(row);
        if (req.text) raw = String(req.text);
      }
      if (!raw) return `任务 #${row.id}`;
      return this.displaySynthesisText(raw);
    },
    shortModel(version) {
      if (!version) return "—";
      const s = String(version);
      const head = s.split("|")[0] || s;
      return head.length > 18 ? `${head.slice(0, 16)}…` : head;
    },
    voiceLabel(row) {
      const code = row.voiceCode || this.parseRequest(row).voice;
      if (!code) return "—";
      const hit = (this.verified || []).find((v) => v.code === code);
      if (hit) return hit.name;
      return this.myVoiceNames[code] || code;
    },
    jobVolume(row) {
      const v = this.parseRequest(row).volume;
      return v != null ? v : 50;
    },
    jobRateLabel(row) {
      const r = Number(this.parseRequest(row).rate);
      if (!r || Number.isNaN(r)) return "1X";
      return `${String(r).replace(/\.0$/, "")}X`;
    },
    jobLangLabel(row) {
      const req = this.parseRequest(row);
      const hints = req.languageHints || req.language_hints;
      const lang = Array.isArray(hints) && hints.length ? hints[0] : req.lang;
      const dialect = req.dialect;
      const langOpt = LANGUAGE_OPTIONS.find((l) => l.code === lang);
      const langName = (langOpt && langOpt.label) || (!lang || lang === "zh" ? "中文" : String(lang));
      if (lang === "zh" || !lang) {
        return dialect && dialect !== "普通话" ? `中文·${dialect}` : "中文";
      }
      return langName;
    },
    selectLanguage(l) {
      this.form.lang = l.code;
      if (l.code === "zh") {
        if (!this.form.dialect) this.form.dialect = "普通话";
      } else {
        this.form.dialect = "";
        this.langMenuVisible = false;
      }
    },
    selectDialect(d) {
      this.form.dialect = d;
      this.langMenuVisible = false;
    },
    dialectInstruction() {
      if (this.form.lang !== "zh") return "";
      const d = (this.form.dialect || "").trim();
      if (!d || d === "普通话") return "";
      return `请用${d}表达。`;
    },
    formatJobTime(val) {
      if (!val) return "";
      const d = new Date(val);
      if (Number.isNaN(d.getTime())) return "";
      return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    },
    formatClock(sec) {
      const n = Math.max(0, Math.floor(Number(sec) || 0));
      const m = Math.floor(n / 60);
      const s = n % 60;
      return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    },
    jobIconClass(row, idx) {
      if (row.status === "failed" || row.status === "error") return "ot-asset__icon--warm";
      const palette = ["", "ot-asset__icon--cool", "ot-asset__icon--rose", "ot-asset__icon--warm"];
      return palette[idx % palette.length];
    },
    jobDotClass(row, idx) {
      const palette = ["is-blue", "is-pink", "is-green", "is-amber"];
      return palette[idx % palette.length];
    },
    generate() {
      if (!this.canSubmit) {
        this.$message.warning(this.sendTitle);
        return;
      }
      this.submitting = true;
      this.bottomTab = "jobs";
      officialTts.createJob(this.jobBody("dubbing"), () => {
        this.submitting = false;
        this.$message.success("已提交配音");
        this.bottomTab = "jobs";
        this.reloadJobs();
      }, (err) => {
        this.submitting = false;
        this.$message.error(this.apiMsg(err, "配音请求失败"));
      });
    },
    jobBody(jobType) {
      // 提交官方标签：【倒吸一口气】→ [gasp]，避免中文括号被原样念出
      const text = toOfficialSynthesisText(this.buildApiTextFromEditor() || this.form.text);
      this.form.text = text;
      const body = {
        jobType,
        voice: this.form.voice,
        text,
        format: this.form.format,
        volume: this.form.volume,
        rate: this.form.rate,
        languageHints: [this.form.lang || "zh"],
      };
      if (this.form.lang === "zh" && this.form.dialect) {
        body.dialect = this.form.dialect;
      }
      const dialectInst = this.dialectInstruction();
      if (dialectInst) {
        body.instruction = dialectInst;
      }
      if (this.form.format === "opus" && this.form.bitRate != null) {
        body.bitRate = this.form.bitRate;
      }
      return body;
    },
    download(row) {
      this.fetchAudio(row, (blob, format) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        // 演示模式下载的是浏览器内生成的 WAV 提示音，扩展名如实写成 wav
        a.download = `official-tts-${row.id}.${this.mock ? "wav" : (format || "wav")}`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 5000);
      });
    },
    editJob(row) {
      const req = this.parseRequest(row);
      let text = "";
      if (req.text) text = String(req.text);
      else if (row.synthesisText) text = row.synthesisText;
      this.setEditorHtmlFromText(text);
      if (req.voice || row.voiceCode) this.form.voice = req.voice || row.voiceCode;
      if (req.volume != null) this.form.volume = Number(req.volume);
      if (req.rate != null) this.form.rate = Number(req.rate);
      if (req.format) this.form.format = String(req.format);
      const hints = req.languageHints || req.language_hints;
      if (Array.isArray(hints) && hints[0]) this.form.lang = hints[0];
      else if (req.lang) this.form.lang = req.lang;
      if (req.dialect) this.form.dialect = String(req.dialect);
      else if (this.form.lang === "zh") this.form.dialect = "普通话";
      else this.form.dialect = "";
      this.$message.success("已填入上方合成区，可修改后重新生成");
      window.scrollTo({ top: 0, behavior: "smooth" });
    },
    removeJob(row) {
      this.$confirm("资产删除后无法找回，请谨慎操作。", "你确认删除该资产吗？", {
        confirmButtonText: "删除",
        cancelButtonText: "取消",
        customClass: "ot-delete-confirm",
        confirmButtonClass: "ot-delete-confirm__danger",
        cancelButtonClass: "ot-delete-confirm__cancel",
      })
        .then(() => {
          officialTts.deleteJob(row.id, () => {
            if (this.playingId === row.id) this.stopPlay();
            this.$message.success("已删除");
            this.reloadJobs();
          }, (err) => this.$message.error(this.apiMsg(err, "删除失败")));
        })
        .catch(() => {});
    },
    togglePlay(row) {
      if (row.status !== "done") return;
      if (this.playingId === row.id) {
        const el = this.$refs.audioEl;
        if (!el) return;
        if (el.paused) el.play().catch(() => {});
        else el.pause();
        return;
      }
      this.startPlay(row);
    },
    onSeekClick(row, ev) {
      if (row.status !== "done") return;
      const bar = ev.currentTarget;
      const rect = bar.getBoundingClientRect();
      const ratio = Math.min(1, Math.max(0, (ev.clientX - rect.left) / rect.width));
      if (this.playingId !== row.id) {
        this.startPlay(row, () => {
          const el = this.$refs.audioEl;
          if (el && el.duration) el.currentTime = el.duration * ratio;
        });
        return;
      }
      const el = this.$refs.audioEl;
      if (el && el.duration) {
        el.currentTime = el.duration * ratio;
        if (el.paused) el.play().catch(() => {});
      }
    },
    startPlay(row, afterLoad) {
      const format = this.jobFormat(row);
      if (format === "pcm" || format === "opus") {
        this.$message.warning("当前格式请下载后用本地播放器试听");
        return;
      }
      this.loadingId = row.id;
      this.fetchAudio(row, (blob) => {
        this.loadingId = null;
        this.stopPlay(false);
        this.playUrl = URL.createObjectURL(blob);
        this.playingId = row.id;
        this.playCurrent = 0;
        this.playDuration = 0;
        this.$nextTick(() => {
          const el = this.$refs.audioEl;
          if (!el) return;
          el.src = this.playUrl;
          el.play()
            .then(() => {
              if (typeof afterLoad === "function") afterLoad();
            })
            .catch(() => this.$message.error("播放失败"));
        });
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
      this.playCurrent = this.playDuration;
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
      this.playCurrent = 0;
      this.playDuration = 0;
      this.playPaused = true;
      if (clearId) this.playingId = null;
    },
    jobFormat(row) {
      const req = this.parseRequest(row);
      if (req.format) return String(req.format).toLowerCase();
      return "wav";
    },
    fetchAudio(row, onOk) {
      if (row.status !== "done") {
        this.$message.warning("任务未完成，暂不可用");
        return;
      }
      officialTts.fetchJobAudio(row.id, (blob) => {
        if (!blob || !(blob instanceof Blob)) {
          this.$message.error("获取音频失败");
          this.loadingId = null;
          return;
        }
        if (blob.type && blob.type.indexOf("application/json") >= 0) {
          const reader = new FileReader();
          reader.onload = () => {
            try {
              const obj = JSON.parse(reader.result);
              this.$message.error(obj.msg || "获取音频失败");
            } catch (e) {
              this.$message.error("获取音频失败");
            }
            this.loadingId = null;
          };
          reader.readAsText(blob);
          return;
        }
        onOk(blob, this.jobFormat(row));
      }, (err) => {
        this.loadingId = null;
        this.$message.error(this.apiMsg(err, "获取音频失败"));
      });
    },
  },
  beforeDestroy() {
    clearTimeout(this.jobsGuard);
    this.stopPoll();
    this.stopPlay();
  },
};
</script>
