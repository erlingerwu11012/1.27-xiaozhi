<template>
  <div class="ot-page">
  <OfficialTtsStudioShell active-tab="synth" :warning="actionBlockedReason">
    <template #hero>
      <h1>欢迎体验语音合成，今天想合成什么？</h1>
    </template>

    <template #composer>
      <div
        ref="editor"
        class="ot-composer__editor"
        :class="{ 'is-empty': !form.text }"
        contenteditable="true"
        role="textbox"
        data-placeholder="输入你要合成的语音文本内容"
        @input="onEditorInput"
        @keydown="onEditorKeydown"
        @paste="onEditorPaste"
        @mouseup="saveEditorRange"
        @keyup="saveEditorRange"
        @focus="saveEditorRange"
      />
      <div class="ot-composer__toolbar">
        <div class="ot-composer__tools">
          <el-popover
            v-model="tagMenuVisible"
            placement="top-start"
            trigger="click"
            popper-class="ot-tag-popper"
            :visible-arrow="false"
          >
            <div class="ot-tag-cascade">
              <div class="ot-tag-panel ot-tag-panel--root">
                <div class="ot-tag-panel__title">语气标签</div>
                <button
                  v-for="cat in tagCategories"
                  :key="cat.id"
                  type="button"
                  class="ot-tag-panel__row"
                  :class="{ 'is-active': tagMenuHover === cat.id }"
                  @mouseenter="tagMenuHover = cat.id"
                >
                  <span>{{ cat.name }}</span>
                  <i class="el-icon-arrow-right" />
                </button>
              </div>
              <div class="ot-tag-panel ot-tag-panel--sub">
                <div class="ot-tag-panel__title">{{ activeTagCategoryName }}</div>
                <div class="ot-tag-panel__scroll">
                  <button
                    v-for="item in activeTagItems"
                    :key="item.code"
                    type="button"
                    class="ot-tag-panel__item"
                    @click="pickToneTag(item)"
                  >
                    {{ item.label }}
                  </button>
                </div>
              </div>
            </div>
            <button
              slot="reference"
              type="button"
              class="ot-tool"
              :class="{ 'is-open': tagMenuVisible }"
            >
              <span>/ 语气标签</span>
            </button>
          </el-popover>

          <button
            type="button"
            class="ot-tool ot-tool--voice"
            @click="voiceLibVisible = true"
          >
            <i class="el-icon-sort" />
            <span>{{ currentVoiceLabel }}</span>
            <i class="el-icon-arrow-down" style="font-size: 12px; margin-left: 2px" />
          </button>

          <el-popover
            v-model="langMenuVisible"
            placement="top-start"
            trigger="click"
            popper-class="ot-lang-popper"
            :visible-arrow="false"
          >
            <div class="ot-lang-menu">
              <div class="ot-lang-col">
                <div class="ot-lang-col__title">语言</div>
                <div class="ot-lang-col__scroll">
                  <button
                    v-for="l in languageOptions"
                    :key="l.code"
                    type="button"
                    class="ot-lang-col__item"
                    :class="{ 'is-active': form.lang === l.code }"
                    @click="selectLanguage(l)"
                  >
                    <span>{{ l.label }}</span>
                    <i v-if="form.lang === l.code" class="el-icon-check" />
                  </button>
                </div>
              </div>
              <div v-if="form.lang === 'zh'" class="ot-lang-col ot-lang-col--dialect">
                <div class="ot-lang-col__title">方言</div>
                <div class="ot-lang-col__scroll">
                  <button
                    v-for="d in dialectOptions"
                    :key="d"
                    type="button"
                    class="ot-lang-col__item"
                    :class="{ 'is-active': form.dialect === d }"
                    @click="selectDialect(d)"
                  >
                    <span>{{ d }}</span>
                    <i v-if="form.dialect === d" class="el-icon-check" />
                  </button>
                </div>
              </div>
            </div>
            <button
              slot="reference"
              type="button"
              class="ot-tool"
              :class="{ 'is-open': langMenuVisible }"
            >
              <span>{{ langDisplayLabel }}</span>
              <i class="el-icon-arrow-down" style="font-size: 12px; margin-left: 2px" />
            </button>
          </el-popover>

          <el-popover placement="top" width="260" trigger="click">
            <div class="ot-popover-row">
              <span>音量</span>
              <el-slider v-model="form.volume" :min="0" :max="100" style="width: 140px; margin: 0 8px" />
              <span>{{ form.volume }}</span>
            </div>
            <button slot="reference" type="button" class="ot-tool">
              <i class="el-icon-microphone" />
              <span>{{ form.volume }}</span>
            </button>
          </el-popover>

          <el-popover placement="top" width="240" trigger="click">
            <div class="ot-popover-row">
              <span>语速</span>
              <el-slider
                v-model="form.rate"
                :min="0.5"
                :max="2"
                :step="0.1"
                style="width: 140px; margin: 0 8px"
              />
              <span>{{ form.rate.toFixed(1) }}X</span>
            </div>
            <button slot="reference" type="button" class="ot-tool">
              <i class="el-icon-timer" />
              <span>{{ form.rate.toFixed(1).replace(/\.0$/, "") }}X</span>
            </button>
          </el-popover>

          <el-popover placement="top" width="280" trigger="click">
            <div class="ot-popover-row">
              <span>导出格式</span>
              <el-select v-model="form.format" size="mini" style="width: 120px">
                <el-option v-for="f in formats" :key="f" :label="f.toUpperCase()" :value="f" />
              </el-select>
            </div>
            <div v-if="form.format === 'opus'" class="ot-popover-row">
              <span>码率 kbps</span>
              <el-input-number v-model="form.bitRate" :min="6" :max="510" size="mini" />
            </div>
            <p style="margin: 8px 0 0; color: #86909c; font-size: 12px; line-height: 1.5">
              仅影响配音下载，不影响设备实时播放。
            </p>
            <button slot="reference" type="button" class="ot-tool">
              <i class="el-icon-setting" />
              <span>导出设定</span>
            </button>
          </el-popover>
        </div>

        <div class="ot-composer__actions">
          <button
            type="button"
            class="ot-btn-send"
            :class="{ 'is-ready': canSubmit }"
            :disabled="!canSubmit"
            :title="sendTitle"
            @click="generate"
          >
            <i class="el-icon-top" />
          </button>
        </div>
      </div>
    </template>

    <template #bottom>
      <div class="ot-bottom__bar">
        <div class="ot-bottom__tabs ot-bottom__tabs--text">
          <button
            type="button"
            class="ot-bottom__tab"
            :class="{ 'is-active': bottomTab === 'inspire' }"
            @click="bottomTab = 'inspire'"
          >
            灵感
          </button>
          <button
            type="button"
            class="ot-bottom__tab"
            :class="{ 'is-active': bottomTab === 'jobs' }"
            @click="bottomTab = 'jobs'"
          >
            资产
          </button>
        </div>
      </div>

      <div v-if="bottomTab === 'inspire'" class="ot-card-grid">
        <button
          v-for="(item, idx) in inspireCards"
          :key="idx"
          type="button"
          class="ot-card"
          @click="applyInspire(item)"
        >
          <div class="ot-card__swatch" :class="item.swatch" />
          <div class="ot-card__body">
            <p class="ot-card__title">{{ item.title }}</p>
            <p class="ot-card__meta">{{ item.meta }}</p>
          </div>
        </button>
      </div>

      <div v-else class="ot-asset-list">
        <div v-if="showGenerating" class="ot-generating" role="status" aria-live="polite">
          <span class="ot-generating__text">
            <i class="el-icon-loading" />
            生成中，请等待…
          </span>
        </div>
        <div v-if="!jobs.length && !showGenerating" class="ot-empty">暂无合成资产</div>
        <div
          v-for="(row, idx) in jobs"
          :key="row.id"
          class="ot-asset"
          :class="{ 'is-playing': playingId === row.id }"
        >
          <div class="ot-asset__icon" :class="jobIconClass(row, idx)">
            <i class="el-icon-document" />
          </div>
          <div class="ot-asset__main">
            <p class="ot-asset__title" :title="jobTitle(row)">{{ jobTitle(row) }}</p>
            <div class="ot-asset__meta">
              <span class="ot-asset__dot" :class="jobDotClass(row, idx)" />
              <span>{{ voiceLabel(row) }}</span>
              <span class="ot-asset__sep"><i class="el-icon-microphone" />{{ jobVolume(row) }}</span>
              <span class="ot-asset__sep"><i class="el-icon-timer" />{{ jobRateLabel(row) }}</span>
              <span class="ot-asset__sep">{{ jobLangLabel(row) }}</span>
              <span class="ot-asset__sep">{{ formatJobTime(row.createdAt) }}</span>
              <span v-if="row.status && row.status !== 'done'" class="ot-asset__status">{{ row.status }}</span>
            </div>
          </div>
          <div class="ot-asset__player" @click.stop>
            <span class="ot-asset__time">{{ playingId === row.id ? formatClock(playCurrent) : '00:00' }}</span>
            <div
              class="ot-asset__seek"
              :class="{ 'is-disabled': row.status !== 'done' }"
              @click="onSeekClick(row, $event)"
            >
              <div
                class="ot-asset__seek-fill"
                :style="{ width: playingId === row.id ? playProgress + '%' : '0%' }"
              />
              <div
                class="ot-asset__seek-thumb"
                :style="{ left: playingId === row.id ? playProgress + '%' : '0%' }"
              />
            </div>
            <span class="ot-asset__time">{{ playingId === row.id ? formatClock(playDuration) : (row.status === 'done' ? '--:--' : '--:--') }}</span>
            <button
              type="button"
              class="ot-asset__play-btn"
              :disabled="row.status !== 'done' || loadingId === row.id"
              :title="playingId === row.id && !playPaused ? '暂停' : '播放'"
              @click="togglePlay(row)"
            >
              <i :class="playingId === row.id && !playPaused ? 'el-icon-video-pause' : 'el-icon-video-play'" />
            </button>
          </div>
          <div class="ot-asset__actions">
            <button
              type="button"
              class="ot-asset__action"
              :disabled="row.status !== 'done'"
              title="下载"
              @click="download(row)"
            >
              <i class="el-icon-download" />
            </button>
            <button type="button" class="ot-asset__action" title="编辑" @click="editJob(row)">
              <i class="el-icon-edit" />
            </button>
            <button
              type="button"
              class="ot-asset__action"
              title="删除"
              @click="removeJob(row)"
            >
              <i class="el-icon-delete" />
            </button>
          </div>
        </div>
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
        return "官方增强功能尚未启用（总开关关闭或未加入灰度名单），因此无法试用合成。";
      }
      if (this.caps.pricingStatus === "pricing_pending") {
        return "该操作尚未配置并发布有效售价，无法发起收费/试用调用。";
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
      officialTts.listJobs((res) => {
        this.jobs = (res.data && res.data.data) || [];
      });
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
        a.download = `official-tts-${row.id}.${format || "wav"}`;
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
      this.$message.success("已填入合成区，可修改后重新生成");
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
    this.stopPoll();
    this.stopPlay();
  },
};
</script>
