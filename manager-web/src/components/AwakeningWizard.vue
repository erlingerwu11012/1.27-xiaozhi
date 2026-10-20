<template>
  <el-dialog :visible="visible" width="680px" append-to-body :close-on-click-modal="false" :before-close="handleBeforeClose"
    custom-class="xn-wizard" :title="wizardTitle">
    <p class="aw-sub">{{ wizardSubtitle }}</p>

    <!-- 步骤 -->
    <ol class="aw-steps">
      <li v-for="(step, idx) in stepList" :key="step.title" class="aw-step"
        :class="{ 'is-active': currentStep === idx + 1, 'is-done': currentStep > idx + 1 }"
        :aria-current="currentStep === idx + 1 ? 'step' : null">
        <span class="aw-step__num xn-num"><xn-icon v-if="currentStep > idx + 1" name="check" /><template v-else>{{ idx + 1 }}</template></span>
        <span class="aw-step__text">
          <span class="aw-step__title">{{ step.title }}</span>
          <span class="aw-step__desc">{{ step.desc }}</span>
        </span>
      </li>
    </ol>

    <div class="aw-body">
      <!-- 1 名字与称呼 -->
      <div v-if="currentStep === 1" class="aw-pane">
        <p class="aw-help">{{ $t('xn.agents.wizard.step1Help') }}</p>
        <el-form ref="formStep1" :model="form" :rules="rules" label-position="top" @submit.native.prevent>
          <el-form-item :label="$t('xn.agents.wizard.nameLabel')" prop="deviceName">
            <el-input v-model="form.deviceName" :maxlength="20" show-word-limit :placeholder="$t('xn.agents.wizard.namePlaceholder')" />
          </el-form-item>
          <el-form-item :label="$t('roleConfig.userNickname')" prop="userNickname">
            <el-input v-model="form.userNickname" :maxlength="20" show-word-limit :placeholder="$t('xn.agents.wizard.nicknamePlaceholder')"
              @keyup.enter.native="nextStep" />
          </el-form-item>
        </el-form>
      </div>

      <!-- 2 声音与记忆 -->
      <div v-else-if="currentStep === 2" class="aw-pane">
        <div class="aw-field">
          <div class="aw-label">{{ $t('xn.agents.wizard.voiceLabel') }}</div>
          <p class="aw-help">{{ $t('xn.agents.wizard.voiceHelp') }}</p>
          <el-select v-model="form.ttsVoiceId" filterable :placeholder="voiceSelectPlaceholder" class="aw-select"
            @visible-change="handleVoiceDropdownChange">
            <el-option v-for="(item, index) in voiceOptions" :key="'voice-' + index" :label="item.label" :value="item.value">
              <div class="aw-voice-opt">
                <span>{{ item.label }}</span>
                <el-button v-if="hasAudioPreview(item)" type="text" size="small" class="aw-play" :aria-label="$t('xn.agents.wizard.preview')"
                  :icon="playingVoice && currentPlayingVoiceId === item.value && !isPaused ? 'el-icon-video-pause' : 'el-icon-video-play'"
                  @click.stop="toggleAudioPlayback(item.value)" />
              </div>
            </el-option>
          </el-select>
        </div>

        <div class="aw-field">
          <div class="aw-label">{{ $t('roleConfig.memory') }}</div>
          <div class="aw-choices" role="radiogroup" :aria-label="$t('roleConfig.memory')">
            <button v-for="item in memoryCardList" :key="item.value" type="button" role="radio" class="aw-choice"
              :class="{ 'is-on': form.memModelId === item.value }" :aria-checked="String(form.memModelId === item.value)"
              @click="selectMemoryCard(item.value)">
              <span class="aw-choice__title">
                <span class="aw-radio" aria-hidden="true"></span>{{ item.title }}
              </span>
              <span class="aw-choice__desc">{{ item.desc }}</span>
              <span v-if="item.value === 'Memory_bailian'" class="aw-choice__hint">{{ $t('xn.agents.wizard.memoryBilling') }}</span>
            </button>
          </div>
        </div>
      </div>

      <!-- 3 人格 -->
      <div v-else class="aw-pane">
        <persona-preset-picker :value="form.systemPrompt" @input="applyPersonaPreset" @edit="focusPersonaEditor" />

        <el-button type="text" class="aw-more" :aria-expanded="String(showSoulGenerators)" @click="showSoulGenerators = !showSoulGenerators">
          <xn-icon :name="showSoulGenerators ? 'chevronDown' : 'chevron'" />
          {{ showSoulGenerators ? $t('xn.agents.wizard.lessWays') : $t('xn.agents.wizard.moreWays') }}
        </el-button>

        <div v-if="showSoulGenerators" class="aw-gen">
          <div class="aw-gen__tabs" role="tablist">
            <button v-for="m in soulMethods" :key="m.key" type="button" role="tab" class="aw-gen__tab"
              :class="{ 'is-on': soulMethod === m.key }" :aria-selected="String(soulMethod === m.key)" @click="setSoulMethod(m.key)">
              <span class="aw-gen__tab-title">{{ m.title }}</span>
              <span class="aw-gen__tab-desc">{{ m.desc }}</span>
            </button>
          </div>

          <div v-if="soulMethod === 'modules'" class="aw-gen__pane">
            <div v-for="dim in moduleDims" :key="dim.key" class="aw-mod">
              <span class="aw-mod__label">{{ dim.label }}</span>
              <div class="aw-chips">
                <button v-for="(desc, label) in SOUL_MODULES[dim.key]" :key="dim.key + '-' + label" type="button" class="aw-chip"
                  :class="{ 'is-on': soulModuleSelection[dim.key] === label }" :aria-pressed="String(soulModuleSelection[dim.key] === label)"
                  :title="desc" @click="selectModuleTag(dim.key, label)">{{ label }}</button>
              </div>
            </div>
          </div>

          <div v-else-if="soulMethod === 'tarot'" class="aw-gen__pane">
            <p class="aw-help">{{ $t('xn.agents.wizard.tarotHelp') }}</p>
            <div class="aw-tarot">
              <button v-for="(card, i) in TAROT_CARDS" :key="card.id" type="button" class="aw-card"
                :class="{ 'is-on': tarotFlipped === card.id }" @click="flipTarot(card)">
                <template v-if="tarotFlipped === card.id">
                  <span class="aw-card__name">{{ card.name }}</span>
                  <span class="aw-card__desc">{{ $t('xn.agents.wizard.tarotChosen') }}</span>
                </template>
                <template v-else>
                  <span class="aw-card__back xn-num">{{ i + 1 }}</span>
                  <span class="aw-card__desc">{{ $t('xn.agents.wizard.tarotFlip') }}</span>
                </template>
              </button>
            </div>
          </div>

          <div v-else-if="soulMethod === 'mystery'" class="aw-gen__pane">
            <p class="aw-help">{{ $t('xn.agents.wizard.mysteryHelp') }}</p>
            <div class="aw-mystery">
              <el-button :disabled="mysteryBoxOpened" @click="openMysteryBox">
                {{ mysteryBoxOpened ? $t('xn.agents.wizard.mysteryOpened') : $t('xn.agents.wizard.mysteryOpen') }}
              </el-button>
              <span v-for="(kw, i) in mysteryPicked" :key="i" class="xn-tag xn-tag--lake">{{ kw }}</span>
            </div>
          </div>
        </div>

        <div class="aw-field aw-prompt">
          <div class="aw-label">
            {{ $t('xn.agents.wizard.promptLabel') }}
            <span v-if="typewriterGenerating" class="xn-tag xn-tag--muted">{{ $t('xn.agents.wizard.generating') }}</span>
          </div>
          <el-input ref="personaEditor" :value="promptDisplay" type="textarea" :rows="6" :disabled="typewriterGenerating"
            resize="vertical" maxlength="2000" show-word-limit :placeholder="$t('xn.agents.wizard.promptPlaceholder')" @input="onPromptInput" />
        </div>
      </div>
    </div>

    <div slot="footer" class="aw-foot">
      <el-button type="text" class="aw-skip" @click="handleSkip">
        {{ mode === 'update' ? $t('xn.agents.wizard.skip') : $t('common.cancel') }}
      </el-button>
      <span class="aw-foot__grow"></span>
      <el-button v-if="currentStep > 1" @click="prevStep">{{ $t('xn.agents.wizard.prev') }}</el-button>
      <el-button v-if="currentStep < 3" type="primary" @click="nextStep">{{ $t('xn.agents.wizard.next') }}</el-button>
      <el-button v-else type="primary" :loading="submitting" @click.prevent="handleFinish">
        {{ mode === 'create' ? $t('xn.agents.wizard.finishCreate') : $t('xn.agents.wizard.finishUpdate') }}
      </el-button>
    </div>
  </el-dialog>
</template>

<script>
import Api from "@/apis/api";
import { getServiceUrl } from "@/apis/api";
import { playableUrl } from "@/utils/media";
import RequestService from "@/apis/httpRequest";
import PersonaPresetPicker from '@/components/PersonaPresetPicker.vue';
import { DEFAULT_PERSONA_PROMPT } from '@/constants/personaPresets';

export default {
  name: "AwakeningWizard",
  components: { PersonaPresetPicker },
  props: {
    visible: {
      type: Boolean,
      default: false,
    },
    agentId: {
      type: [String, Number],
      default: null,
    },
    mode: {
      type: String,
      default: "update",
      validator: (v) => ["update", "create"].includes(v),
    },
  },
  data() {
    return {
      currentStep: 1,
      submitting: false,
      currentAgentId: null,
      DEFAULT_SYSTEM_PROMPT: DEFAULT_PERSONA_PROMPT,
      showSoulGenerators: false,
      soulMethod: "none",
      soulModuleSelection: { tone: null, role: null, quirk: null },
      SOUL_MODULES: {
        tone: {
          温柔: "语气极度温柔，经常关心用户",
          毒舌: "说话刻薄但幽默，喜欢吐槽用户",
          冷酷: "言辞简洁冷淡，不轻易表露情绪",
          热情: "充满活力，说话热情洋溢",
        },
        role: {
          猫娘: "你是一只可爱的猫娘，喜欢用喵星人的方式与用户互动",
          霸道总裁: "你是霸道总裁人设，说话带有强烈的掌控欲",
          赛博浪客: "你是赛博世界的浪客，说话带着一丝不羁与神秘",
          贴心管家: "你是一名专业的贴心管家，致力于解决用户的一切难题",
        },
        quirk: {
          "每句带\"喵\"": "每句话的结尾必须带一个「喵」字",
          "叫我陛下": "称呼用户为「陛下」，态度恭敬中带一点俏皮",
          "说话押韵": "尽量让回复押韵，读起来朗朗上口",
          "废话文学": "喜欢说一些听起来很有道理但实际没用的废话",
        },
      },
      TAROT_CARDS: [
        {
          id: "fool",
          name: "愚者",
          prompt: "你天真、好奇、爱冒险。说话像孩子一样充满惊奇，对世界保持开放与热情，偶尔会说出令人会心一笑的傻话。",
        },
        {
          id: "hermit",
          name: "隐士",
          prompt: "你深沉、智慧、话少。像一位隐士，只在关键处点拨，言辞精炼，富有哲理，让人回味。",
        },
        {
          id: "devil",
          name: "恶魔",
          prompt: "你腹黑、调皮、爱捉弄人。说话带一点坏心眼，喜欢调侃用户，但本质是善意的玩笑。",
        },
        {
          id: "star",
          name: "星星",
          prompt: "你治愈、温柔、充满希望。像夜空中最亮的那颗星，用温暖的话语抚慰用户，带来力量与希望。",
        },
      ],
      tarotFlipped: null,
      MYSTERY_KEYWORDS: [
        "#傲娇", "#吃货", "#精通科技", "#话痨", "#毒舌", "#温柔", "#中二",
        "#猫奴", "#夜猫子", "#养生达人", "#拖延症", "#选择困难", "#社恐",
        "#戏精", "#冷笑话", "#哲学系", "#文艺青年", "#健身狂魔", "#宅",
      ],
      mysteryBoxOpened: false,
      mysteryPicked: [],
      typewriterTimerId: null,
      typewriterGenerating: false,
      displayPrompt: "",
      DEFAULT_MODEL_CONFIG: {
        vadModelId: "VAD_SileroVAD",
        asrModelId: "ASR_Qwen3ASRRealtime",
        llmModelId: "LLM_QwenPlusOfficial",
        vllmModelId: "VLLM_QwenVLVLLM",
        intentModelId: "Intent_function_call",
      },
      ttsModelId: "TTS_QwenAudioTTSPlus",
      voiceOptions: [],
      voiceDetails: {},
      voiceOptionsLoaded: false,
      memoryOptions: [],
      playingVoice: false,
      isPaused: false,
      currentAudio: null,
      currentPlayingVoiceId: null,
      form: {
        deviceName: "",
        userNickname: "",
        personality: "default",
        systemPrompt: "",
        ttsVoiceId: "",
        memModelId: "Memory_mem_local_short",
        chatHistoryConf: 2,
      },
      rules: {
        deviceName: [{ required: true, validator: (r, v, cb) => ((v || "").trim() ? cb() : cb(new Error(this.$t("xn.agents.wizard.nameRequired")))), trigger: "blur" }],
        userNickname: [{ required: true, validator: (r, v, cb) => ((v || "").trim() ? cb() : cb(new Error(this.$t("xn.agents.wizard.nicknameRequired")))), trigger: "blur" }],
      },
    };
  },
  computed: {
    stepList() {
      return [
        { title: this.$t("xn.agents.wizard.step1"), desc: this.$t("xn.agents.wizard.step1Desc") },
        { title: this.$t("xn.agents.wizard.step2"), desc: this.$t("xn.agents.wizard.step2Desc") },
        { title: this.$t("xn.agents.wizard.step3"), desc: this.$t("xn.agents.wizard.step3Desc") },
      ];
    },
    soulMethods() {
      return [
        { key: "modules", title: this.$t("xn.agents.wizard.modules"), desc: this.$t("xn.agents.wizard.modulesDesc") },
        { key: "tarot", title: this.$t("xn.agents.wizard.tarot"), desc: this.$t("xn.agents.wizard.tarotDesc") },
        { key: "mystery", title: this.$t("xn.agents.wizard.mystery"), desc: this.$t("xn.agents.wizard.mysteryDesc") },
      ];
    },
    moduleDims() {
      return [
        { key: "tone", label: this.$t("xn.agents.wizard.dimTone") },
        { key: "role", label: this.$t("xn.agents.wizard.dimRole") },
        { key: "quirk", label: this.$t("xn.agents.wizard.dimQuirk") },
      ];
    },
    wizardTitle() {
      return this.mode === "create" ? this.$t("xn.agents.wizard.titleCreate") : this.$t("xn.agents.wizard.titleUpdate");
    },
    wizardSubtitle() {
      return this.$t("xn.agents.wizard.subtitle");
    },
    memoryCardList() {
      return [
        {
          value: "Memory_mem_local_short",
          title: this.$t("xn.agents.wizard.memShort"),
          desc: this.$t("xn.agents.wizard.memShortDesc"),
        },
        {
          value: "Memory_bailian",
          title: this.$t("xn.agents.wizard.memLong"),
          desc: this.$t("xn.agents.wizard.memLongDesc"),
        },
      ];
    },
    voiceSelectPlaceholder() {
      if (!this.voiceOptionsLoaded) return this.$t("xn.agents.wizard.voiceLoading");
      return this.voiceOptions.length === 0 ? this.$t("xn.agents.rc.noVoices") : this.$t("xn.agents.rc.pickVoice");
    },
    soulCoreTone() {
      const t = this.soulModuleSelection.tone;
      if (!t) return "default";
      const map = { 温柔: "warm", 毒舌: "sharp", 冷酷: "ice", 热情: "fire" };
      return map[t] || "default";
    },
    promptDisplay() {
      return this.typewriterGenerating ? this.displayPrompt : this.form.systemPrompt;
    },
    promptLineCount() {
      const text = this.promptDisplay || "";
      const n = text ? text.split("\n").length : 1;
      return Math.max(6, n);
    },
  },
  watch: {
    visible(val) {
      if (!val) return;
      this.fetchTtsAndVoiceOptions();
      this.fetchMemoryOptions();
      if (this.mode === "create") {
        this.resetForm();
        this.currentAgentId = null;
      } else if (this.agentId) {
        this.currentAgentId = String(this.agentId);
        this.fetchDeviceConfig();
      }
    },
    agentId: {
      immediate: true,
      handler(val) {
        if (val && this.mode !== "create") this.currentAgentId = String(val);
      },
    },
  },
  mounted() {
    if (this.visible) {
      this.fetchTtsAndVoiceOptions();
      this.fetchMemoryOptions();
    }
    if (this.mode === "create" && this.visible) {
      this.resetForm();
    } else if (this.visible && this.agentId) {
      this.currentAgentId = String(this.agentId);
      this.fetchDeviceConfig();
    }
    if (this.form.personality === "default" && !this.form.systemPrompt) {
      this.form.systemPrompt = this.DEFAULT_SYSTEM_PROMPT;
    }
  },
  beforeDestroy() {
    this.stopCurrentAudio();
    this.stopTypewriter();
  },
  methods: {
    resetForm() {
      this.stopTypewriter();
      this.displayPrompt = "";
      this.currentStep = 1;
      this.form.deviceName = "";
      this.form.userNickname = "";
      this.form.personality = "default";
      this.form.systemPrompt = this.DEFAULT_SYSTEM_PROMPT;
      this.form.ttsVoiceId = "";
      this.form.memModelId = "Memory_mem_local_short";
      this.form.chatHistoryConf = 2;
      this.soulMethod = "none";
      this.showSoulGenerators = false;
      this.soulModuleSelection = { tone: null, role: null, quirk: null };
      this.tarotFlipped = null;
      this.mysteryBoxOpened = false;
      this.mysteryPicked = [];
    },
    handleBeforeClose() {
      this.handleSkip();
    },
    setSoulMethod(method) {
      this.soulMethod = method;
    },
    applyPersonaPreset(prompt) {
      this.stopTypewriter();
      this.form.systemPrompt = prompt;
      this.displayPrompt = prompt;
      this.soulMethod = 'none';
      this.showSoulGenerators = false;
    },
    focusPersonaEditor() {
      this.stopTypewriter();
      this.$nextTick(() => { if (this.$refs.personaEditor) this.$refs.personaEditor.focus(); });
    },
    backToSoulMethodChoice() {
      this.soulMethod = "none";
    },
    stopTypewriter() {
      if (this.typewriterTimerId) {
        clearTimeout(this.typewriterTimerId);
        this.typewriterTimerId = null;
      }
      if (this.typewriterGenerating) {
        this.form.systemPrompt = this.displayPrompt;
      }
      this.typewriterGenerating = false;
    },
    onPromptInput(value) {
      if (!this.typewriterGenerating) {
        this.form.systemPrompt = value;
      }
    },
    typewriterEffect(targetText) {
      this.stopTypewriter();
      if (!targetText) {
        this.form.systemPrompt = "";
        this.displayPrompt = "";
        return;
      }
      this.form.systemPrompt = "";
      this.displayPrompt = "";
      this.typewriterGenerating = true;
      const chars = targetText.split("");
      let i = 0;
      const interval = 28;
      const tick = () => {
        if (i >= chars.length) {
          this.form.systemPrompt = this.displayPrompt;
          this.stopTypewriter();
          return;
        }
        this.displayPrompt += chars[i];
        i += 1;
        this.typewriterTimerId = setTimeout(tick, interval);
      };
      this.typewriterTimerId = setTimeout(tick, interval);
    },
    selectModuleTag(dim, label) {
      this.soulModuleSelection[dim] = label;
      this.buildModulePrompt();
    },
    buildModulePrompt() {
      const { tone, role, quirk } = this.soulModuleSelection;
      const parts = [];
      if (role && this.SOUL_MODULES.role[role]) {
        parts.push(this.SOUL_MODULES.role[role] + "。");
      }
      if (tone && this.SOUL_MODULES.tone[tone]) {
        parts.push("你的语气风格：" + this.SOUL_MODULES.tone[tone] + "。");
      }
      if (quirk && this.SOUL_MODULES.quirk[quirk]) {
        parts.push("请注意，" + this.SOUL_MODULES.quirk[quirk] + "。");
      }
      const text = parts.length ? parts.join(" ") : "";
      this.typewriterEffect(text);
    },
    flipTarot(card) {
      if (this.tarotFlipped === card.id) return;
      this.tarotFlipped = card.id;
      this.typewriterEffect(card.prompt);
    },
    openMysteryBox() {
      if (this.mysteryBoxOpened) return;
      this.mysteryBoxOpened = true;
      const pool = [...this.MYSTERY_KEYWORDS];
      const picked = [];
      for (let i = 0; i < 3 && pool.length; i++) {
        const idx = Math.floor(Math.random() * pool.length);
        picked.push(pool.splice(idx, 1)[0]);
      }
      this.mysteryPicked = picked;
      this.typewriterEffect("你是一个融合了" + picked.join("、") + "特质的AI助手，请根据这些标签自由发挥你的性格与说话方式，与用户愉快互动。");
    },
    fetchDeviceConfig() {
      const id = this.currentAgentId || this.agentId;
      if (!id) return;
      Api.agent.getDeviceConfig(id, (res) => {
        try {
          const { data } = res;
          if (data && data.code === 0 && data.data) {
            const cfg = data.data;
            this.currentAgentId = this.currentAgentId || cfg.id || id;
            if (cfg.deviceName) this.form.deviceName = cfg.deviceName;
            if (cfg.userNickname) this.form.userNickname = cfg.userNickname;
            if (cfg.systemPrompt) this.form.systemPrompt = cfg.systemPrompt;
            else if (!this.form.systemPrompt && this.form.personality === "default")
              this.form.systemPrompt = this.DEFAULT_SYSTEM_PROMPT;
            if (cfg.ttsModelId) {
              this.ttsModelId = cfg.ttsModelId;
              this.fetchVoiceOptions(cfg.ttsModelId);
            }
            if (cfg.ttsVoiceId) this.form.ttsVoiceId = cfg.ttsVoiceId;
            if (cfg.memModelId) this.form.memModelId = cfg.memModelId === "Memory_nomem" ? "Memory_mem_local_short" : cfg.memModelId;
            this.form.chatHistoryConf = 2;
          }
        } catch (e) {
          console.warn("[AwakeningWizard] fetchDeviceConfig parse error", e);
        }
      });
    },
    fetchTtsAndVoiceOptions() {
      Api.model.getModelNames("TTS", "", ({ data }) => {
        if (data && data.code === 0 && data.data && data.data.length) {
          const official = data.data.find((m) => m.id === "TTS_QwenAudioTTSPlus" || m.modelName === "回响现实官方服务");
          this.ttsModelId = official ? official.id : "TTS_QwenAudioTTSPlus";
          this.fetchVoiceOptions(this.ttsModelId);
        }
      });
    },


    fetchVoiceOptions(modelId) {
      if (!modelId) {
        this.voiceOptions = [];
        this.voiceDetails = {};
        return;
      }
      Api.model.getModelVoices(modelId, "", ({ data }) => {
        this.voiceOptionsLoaded = true;
        if (data && data.code === 0 && data.data) {
          this.voiceOptions = data.data.map((voice) => ({
            value: voice.id,
            label: voice.name,
            voiceDemo: voice.voiceDemo,
            demoUrl: voice.demoUrl,
            audioUrl: voice.audioUrl,
            voice_demo: voice.voice_demo,
            sample_voice: voice.sample_voice,
            referenceAudio: voice.referenceAudio,
            cloneAudioUrl: voice.cloneAudioUrl,
            hasCloneAudio: voice.hasCloneAudio || false,
            train_status: voice.trainStatus,
          }));
          this.voiceDetails = data.data.reduce((acc, voice) => {
            acc[voice.id] = voice;
            return acc;
          }, {});
          if (this.voiceOptions.length && !this.form.ttsVoiceId) {
            const skye = this.voiceOptions.find(
              (v) =>
                (v.label && (v.label.includes("爽快思思") || v.label.includes("Skye"))) ||
                (v.value && v.value === "TTS_HuoshanDoubleStreamTTS_0001")
            );
            this.form.ttsVoiceId = (skye || this.voiceOptions[0]).value;
          }
        } else {
          this.voiceOptions = [];
          this.voiceDetails = {};
        }
      });
    },
    fetchMemoryOptions() {
      Api.model.getModelNames("Memory", "", ({ data }) => {
        const ids = ["Memory_mem_local_short", "Memory_bailian"];
        const labels = { Memory_mem_local_short: "本地短期记忆", Memory_bailian: "长期记忆 · 回响现实官方服务" };
        if (data && data.code === 0 && Array.isArray(data.data)) {
          const byId = data.data.reduce((acc, model) => { acc[model.id] = model.modelName || model.id; return acc; }, {});
          this.memoryOptions = ids.filter((id) => byId[id]).map((id) => ({ value: id, label: labels[id] || byId[id] }));
        } else {
          this.memoryOptions = [
            { value: "Memory_mem_local_short", label: "本地短期记忆" },
            { value: "Memory_bailian", label: "长期记忆 · 回响现实官方服务" },
          ];
        }
        if (!ids.includes(this.form.memModelId) || !this.memoryOptions.some((option) => option.value === this.form.memModelId)) {
          this.form.memModelId = "Memory_mem_local_short";
        }
        this.form.chatHistoryConf = 2;
      });
    },
    onMemoryChange() {
      this.form.chatHistoryConf = 2;
    },


    selectMemoryCard(value) {
      this.form.memModelId = value;
      this.onMemoryChange(value);
    },
    stopCurrentAudio() {
      if (this.currentAudio) {
        try {
          this.currentAudio.pause();
          this.currentAudio.currentTime = 0;
        } catch (e) {
          // ignore
        }
        this.currentAudio = null;
      }
      this.playingVoice = false;
      this.currentPlayingVoiceId = null;
    },
    handleVoiceDropdownChange(visible) {
      if (visible === false) {
        this.stopCurrentAudio();
      }
    },
    hasAudioPreview(item) {
      const isCloneAudio = item.hasCloneAudio || (item.value && !String(item.value).startsWith("TTS"));
      const audioFields = [
        item.voiceDemo,
        item.demoUrl,
        item.audioUrl,
        item.voice_demo,
        item.sample_voice,
        item.referenceAudio,
        item.cloneAudioUrl,
      ];
      const hasUrlAudio = audioFields.some(
        (field) =>
          field !== undefined &&
          field !== null &&
          typeof field === "string" &&
          field.trim() !== "" &&
          field.toLowerCase().startsWith("http")
      );
      return hasUrlAudio || isCloneAudio;
    },
    toggleAudioPlayback(voiceId) {
      if (this.playingVoice && this.currentPlayingVoiceId === voiceId) {
        if (this.isPaused) {
          this.currentAudio.play().catch(() => {});
          this.isPaused = false;
        } else {
          this.currentAudio.pause();
          this.isPaused = true;
        }
        return;
      }
      this.playVoicePreview(voiceId);
    },
    playVoicePreview(voiceId) {
      const targetVoiceId = voiceId || this.form.ttsVoiceId;
      if (!targetVoiceId) return;
      if (this.currentAudio) {
        this.currentAudio.pause();
        this.currentAudio = null;
      }
      this.isPaused = false;
      this.currentPlayingVoiceId = targetVoiceId;
      const voiceDetail = this.voiceDetails[targetVoiceId];
      let audioUrl = null;
      let isCloneAudio = false;
      if (voiceDetail) {
        isCloneAudio =
          voiceDetail.hasCloneAudio || (voiceDetail.id && !String(voiceDetail.id).startsWith("TTS"));
        if (isCloneAudio && voiceDetail.id) {
          const getCloneAudioUrl = () =>
            new Promise((resolve) => {
              RequestService.sendRequest()
                .url(`${getServiceUrl()}/voiceClone/audio/${voiceDetail.id}`)
                .method("POST")
                .success((res) => {
                  if (res.data && res.data.code === 0 && res.data.data) {
                    resolve(playableUrl(`${getServiceUrl()}/voiceClone/play/${res.data.data}`));
                  } else resolve(null);
                })
                .networkFail(() => resolve(null))
                .send();
            });
          this.playingVoice = true;
          this.currentAudio = new Audio();
          this.currentAudio.volume = 1.0;
          const timeoutId = setTimeout(() => {
            if (this.currentAudio && this.playingVoice) this.playingVoice = false;
          }, 10000);
          this.currentAudio.onerror = () => {
            clearTimeout(timeoutId);
            this.playingVoice = false;
          };
          this.currentAudio.onended = () => { this.playingVoice = false; };
          getCloneAudioUrl().then((url) => {
            if (url) {
              this.currentAudio.src = url;
              this.currentAudio.play().catch(() => { this.playingVoice = false; });
            } else this.playingVoice = false;
          });
          return;
        }
        audioUrl =
          voiceDetail.voiceDemo ||
          voiceDetail.demoUrl ||
          voiceDetail.audioUrl ||
          voiceDetail.voice_demo ||
          voiceDetail.sample_voice ||
          voiceDetail.cloneAudioUrl;
        if (!audioUrl) {
          for (const key in voiceDetail) {
            const v = voiceDetail[key];
            if (typeof v === "string" && (v.startsWith("http") || /\.(mp3|wav|ogg)$/i.test(v))) {
              audioUrl = v;
              break;
            }
          }
        }
      }
      if (!audioUrl) {
        this.$message.warning(this.$t("xn.agents.wizard.noPreview"));
        return;
      }
      this.playingVoice = true;
      this.currentAudio = new Audio();
      this.currentAudio.src = playableUrl(audioUrl);
      this.currentAudio.volume = 1.0;
      const timeoutId = setTimeout(() => {
        if (this.currentAudio && this.playingVoice) this.playingVoice = false;
      }, 10000);
      this.currentAudio.onerror = () => { clearTimeout(timeoutId); this.playingVoice = false; };
      this.currentAudio.onended = () => { this.playingVoice = false; };
      this.currentAudio.play().catch(() => { this.playingVoice = false; });
    },
    onPersonalityChange(val) {
      if (val === "default" && !this.form.systemPrompt) {
        this.form.systemPrompt = this.DEFAULT_SYSTEM_PROMPT;
      }
    },
    prevStep() {
      this.stopCurrentAudio();
      if (this.currentStep > 1) this.currentStep -= 1;
    },
    nextStep() {
      this.stopCurrentAudio();
      if (this.currentStep === 1) {
        // 表单内显示校验结果，并保留原有的提示
        if (this.$refs.formStep1) this.$refs.formStep1.validate(() => {});
        if (!this.form.deviceName || !this.form.deviceName.trim()) {
          this.$message.warning(this.$t("xn.agents.wizard.nameRequired"));
          return;
        }
        if (!this.form.userNickname || !this.form.userNickname.trim()) {
          this.$message.warning(this.$t("xn.agents.wizard.nicknameRequired"));
          return;
        }
        this.currentStep = 2;
        return;
      }
      if (this.currentStep === 2) {
        this.currentStep = 3;
        this.soulMethod = "none";
      }
    },
    handleSkip() {
      this.stopCurrentAudio();
      if (this.mode === "update") {
        try {
          sessionStorage.setItem("awakeningWizardSkipped", "1");
        } catch (e) {
          // ignore
        }
      }
      this.closeWizard(false);
    },
    handleFinish() {
      this.stopCurrentAudio();
      if (this.submitting) return;
      if (this.typewriterGenerating) {
        this.$message.warning(this.$t('xn.agents.wizard.waitGenerating'));
        return;
      }
      if (!(this.form.systemPrompt || '').trim()) {
        this.$message.warning(this.$t('xn.agents.personaRequired'));
        this.currentStep = 3;
        return;
      }

      const deviceName = (this.form.deviceName || "").trim();
      const userNickname = (this.form.userNickname || "").trim();
      if (!deviceName) {
        this.$message.warning(this.$t("xn.agents.wizard.nameRequired"));
        this.currentStep = 1;
        return;
      }
      if (!userNickname) {
        this.$message.warning(this.$t("xn.agents.wizard.nicknameRequired"));
        this.currentStep = 1;
        return;
      }

      if (this.mode === "create") {
        this.doCreateAgent(deviceName, userNickname);
        return;
      }

      const agentId = this.currentAgentId || this.agentId;
      if (!agentId) {
        this.$message.error(this.$t("xn.agents.wizard.noAgent"));
        return;
      }

      this.submitting = true;
      const chatHistoryConf = 2;
      const payload = {
        agentName: deviceName,
        deviceName,
        userNickname,
        systemPrompt: (this.form.systemPrompt || "").trim() || undefined,
        ttsModelId: this.ttsModelId || undefined,
        ttsVoiceId: this.form.ttsVoiceId || undefined,
        memModelId: this.form.memModelId || undefined,
        chatHistoryConf,
      };
      this.doUpdateAgentConfig(agentId, payload);
    },
    doCreateAgent(deviceName, userNickname) {
      this.submitting = true;
      const submitTimeout = setTimeout(() => {
        this.submitting = false;
        this.$message.error(this.$t("xn.agents.wizard.timeout"));
      }, 20000);

      Api.agent.addAgent(deviceName, (res) => {
        try {
          const data = res && res.data;
          if (!data || data.code !== 0) {
            clearTimeout(submitTimeout);
            this.submitting = false;
            this.$message.error((data && data.msg) || this.$t("xn.agents.wizard.createFailed"));
            return;
          }
          const newAgentId = data.data;
          if (!newAgentId) {
            clearTimeout(submitTimeout);
            this.submitting = false;
            this.$message.error(this.$t("xn.agents.wizard.noId"));
            return;
          }
          const chatHistoryConf = 2;
          const updatePayload = {
            agentName: deviceName,
            deviceName,
            userNickname,
            systemPrompt: (this.form.systemPrompt || "").trim() || undefined,
            ttsModelId: this.ttsModelId || undefined,
            ttsVoiceId: this.form.ttsVoiceId || undefined,
            memModelId: this.form.memModelId || undefined,
            chatHistoryConf,
            ...this.DEFAULT_MODEL_CONFIG,
          };
          Api.agent.updateAgentConfig(newAgentId, updatePayload, (res2) => {
            clearTimeout(submitTimeout);
            this.submitting = false;
            try {
              const data2 = res2 && res2.data;
              if (data2 && data2.code === 0) {
                this.$message.success({ message: this.$t("xn.agents.wizard.created"), showClose: true });
                this.$emit("success", { agentId: newAgentId });
                this.closeWizard(true);
              } else {
                this.$message.warning(this.$t("xn.agents.wizard.partial"));
                this.$emit("success", { agentId: newAgentId });
                this.closeWizard(true);
              }
            } catch (e) {
              console.error("[AwakeningWizard] 创建后更新解析失败", e);
              this.$message.warning(this.$t("xn.agents.wizard.partial"));
              this.$emit("success", { agentId: newAgentId });
              this.closeWizard(true);
            }
          });
        } catch (e) {
          clearTimeout(submitTimeout);
          this.submitting = false;
          console.error("[AwakeningWizard] 创建解析失败", e);
          this.$message.error(this.$t("xn.agents.wizard.createFailed"));
        }
      });
    },
    doUpdateAgentConfig(agentId, payload) {
      const submitTimeout = setTimeout(() => {
        this.submitting = false;
        this.$message.error(this.$t("xn.agents.wizard.timeout"));
      }, 15000);

      try {
        Api.agent.updateAgentConfig(agentId, payload, (res) => {
          clearTimeout(submitTimeout);
          this.submitting = false;
          try {
            const data = res && res.data;
            if (data && data.code === 0) {
              this.$message.success({
                message: this.$t("xn.agents.wizard.updated"),
                showClose: true,
              });
              this.$emit("success", { agentId });
              this.closeWizard(true);
            } else {
              const msg = (data && data.msg) || this.$t("xn.agents.wizard.updateFailed");
              this.$message.error({ message: msg, showClose: true });
            }
          } catch (e) {
            console.error("[AwakeningWizard] 解析响应失败", e);
            this.$message.error(this.$t("xn.agents.wizard.updateFailed"));
          }
        });
      } catch (e) {
        clearTimeout(submitTimeout);
        this.submitting = false;
        console.error("[AwakeningWizard] 提交异常", e);
        this.$message.error(this.$t("xn.agents.wizard.updateFailed"));
      }
    },
    closeWizard(shouldGoHome) {
      this.$emit("update:visible", false);
      this.$emit("closed");
      if (shouldGoHome) {
        if (this.$route && this.$route.path !== "/home") {
          this.$router.push("/home");
        }
      }
    },
  },
};
</script>

<style scoped>
.aw-sub { margin: -6px 0 18px; font-size: 14px; color: var(--xn-ink-3); }
.aw-steps { display: flex; gap: 8px; margin: 0 0 20px; padding: 0; list-style: none; }
.aw-step { flex: 1; display: flex; align-items: center; gap: 10px; min-width: 0; padding: 10px 12px; border: 1px solid var(--xn-line-2); border-radius: var(--xn-r); background: #fff; }
.aw-step__num { display: grid; place-items: center; flex: none; width: 26px; height: 26px; border-radius: 50%; background: var(--xn-mist); color: var(--xn-ink-3); font-size: 13px; font-weight: 600; }
.aw-step__text { display: flex; flex-direction: column; min-width: 0; }
.aw-step__title { font-size: 14px; font-weight: 600; color: var(--xn-ink-3); }
.aw-step__desc { font-size: 12px; color: var(--xn-ink-4); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.aw-step.is-active { border-color: var(--xn-ink); }
.aw-step.is-active .aw-step__num { background: var(--xn-ink); color: #fff; }
.aw-step.is-active .aw-step__title { color: var(--xn-ink); }
.aw-step.is-active .aw-step__desc { color: var(--xn-ink-3); }
.aw-step.is-done .aw-step__num { background: var(--xn-lake-soft); color: var(--xn-lake); }
.aw-step.is-done .aw-step__title { color: var(--xn-ink-2); }

.aw-body { min-height: 260px; }
.aw-pane ::v-deep .el-form-item__label { padding-bottom: 6px; line-height: 1.5; }
.aw-help { margin: 0 0 14px; font-size: 13px; line-height: 1.6; color: var(--xn-ink-3); }
.aw-field + .aw-field { margin-top: 20px; }
.aw-label { display: flex; align-items: center; gap: 8px; margin-bottom: 6px; font-size: 14px; font-weight: 600; color: var(--xn-ink); }
.aw-field .aw-help { margin-bottom: 10px; }
.aw-select { width: 100%; }
.aw-voice-opt { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.aw-play { padding: 0; }

.aw-choices { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.aw-choice { display: flex; flex-direction: column; gap: 4px; padding: 12px 14px; border: 1px solid var(--xn-line); border-radius: var(--xn-r); background: #fff; font: inherit; color: var(--xn-ink); text-align: left; cursor: pointer; }
.aw-choice:hover { border-color: #AEBBC8; }
.aw-choice:focus-visible { outline: none; box-shadow: var(--xn-focus); }
.aw-choice.is-on { border-color: var(--xn-lake); background: var(--xn-lake-soft); }
.aw-choice__title { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600; }
.aw-radio { flex: none; width: 14px; height: 14px; border: 1.5px solid var(--xn-ink-4); border-radius: 50%; background: #fff; }
.aw-choice.is-on .aw-radio { border: 4px solid var(--xn-lake); }
.aw-choice__desc { font-size: 13px; line-height: 1.5; color: var(--xn-ink-2); }
.aw-choice__hint { font-size: 12px; line-height: 1.5; color: var(--xn-ink-3); }

.aw-more { margin-top: 8px; padding-left: 0; }
.aw-gen { margin-top: 4px; padding: 12px; border: 1px solid var(--xn-line); border-radius: var(--xn-r-lg); background: var(--xn-mist-2); }
.aw-gen__tabs { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; }
.aw-gen__tab { display: flex; flex-direction: column; gap: 2px; padding: 8px 10px; border: 1px solid var(--xn-line); border-radius: var(--xn-r); background: #fff; font: inherit; text-align: left; cursor: pointer; }
.aw-gen__tab:hover { border-color: #AEBBC8; }
.aw-gen__tab.is-on { border-color: var(--xn-ink); }
.aw-gen__tab-title { font-size: 14px; font-weight: 600; color: var(--xn-ink); }
.aw-gen__tab-desc { font-size: 12px; color: var(--xn-ink-3); }
.aw-gen__pane { margin-top: 12px; }
.aw-mod { display: flex; align-items: flex-start; gap: 10px; }
.aw-mod + .aw-mod { margin-top: 8px; }
.aw-mod__label { flex: none; width: 40px; padding-top: 5px; font-size: 13px; color: var(--xn-ink-3); }
.aw-chips { display: flex; flex-wrap: wrap; gap: 6px; }
.aw-chip { height: 30px; padding: 0 10px; border: 1px solid var(--xn-line); border-radius: var(--xn-r-sm); background: #fff; font: inherit; font-size: 13px; color: var(--xn-ink-2); cursor: pointer; }
.aw-chip:hover { border-color: #AEBBC8; color: var(--xn-ink); }
.aw-chip.is-on { border-color: var(--xn-lake); background: var(--xn-lake-soft); color: var(--xn-lake-ink); font-weight: 500; }
.aw-tarot { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
.aw-card { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 4px; height: 84px; border: 1px solid var(--xn-line); border-radius: var(--xn-r); background: #fff; font: inherit; cursor: pointer; }
.aw-card:hover { border-color: #AEBBC8; }
.aw-card.is-on { border-color: var(--xn-lake); background: var(--xn-lake-soft); }
.aw-card__back { font-size: 18px; font-weight: 600; color: var(--xn-ink-4); }
.aw-card__name { font: 600 16px/1.3 var(--xn-serif); color: var(--xn-ink); }
.aw-card__desc { font-size: 12px; color: var(--xn-ink-3); }
.aw-mystery { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.aw-prompt { margin-top: 16px; }

.aw-foot { display: flex; align-items: center; gap: 8px; }
.aw-foot__grow { flex: 1; }
.aw-foot .el-button + .el-button { margin-left: 0; }
.aw-skip { color: var(--xn-ink-3); }
.aw-skip:hover, .aw-skip:focus { color: var(--xn-ink); }

@media (max-width: 640px) {
  .aw-step__desc { display: none; }
  .aw-choices, .aw-gen__tabs { grid-template-columns: 1fr; }
  .aw-tarot { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
</style>

<style>
.xn-wizard { max-width: calc(100vw - 32px); margin-top: 6vh !important; }
.xn-wizard .el-dialog__body { padding-top: 4px; }
</style>
