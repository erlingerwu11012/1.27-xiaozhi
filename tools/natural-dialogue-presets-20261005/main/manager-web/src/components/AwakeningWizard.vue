<template>
  <transition name="fade">
    <div v-if="visible" class="awakening-overlay">
      <div class="awakening-backdrop" @click="handleSkip"></div>

      <div class="awakening-container">
        <div class="awakening-card">
              <div class="wizard-header">
                <div class="wizard-title">{{ wizardTitle }}</div>
                <div class="wizard-subtitle">{{ wizardSubtitle }}</div>
              </div>

              <!-- Data Pipeline 步骤条：光点 + 细线 + 等宽小写 -->
              <div class="fui-stepper">
                <template v-for="(step, idx) in stepList">
                  <div
                    v-if="idx > 0"
                    class="fui-stepper-track"
                    :class="{ 'fui-stepper-track--active': currentStep > idx }"
                  />
                  <div
                    class="fui-stepper-node"
                    :class="{
                      'is-active': currentStep === idx + 1,
                      'is-done': currentStep > idx + 1
                    }"
                  >
                    <div class="fui-stepper-marker"></div>
                    <div class="fui-stepper-label">{{ step.title }}</div>
                  </div>
                </template>
              </div>

              <div class="wizard-body">
            <div v-if="currentStep === 1" class="wizard-step">
              <div class="step-label">Step 1 · 赋予身份</div>
              <div class="narrative-quote">
                在无数平行宇宙里，诞生了许多智慧体。而你现在面前的这个，将因为你的命名而「真正存在」。
              </div>

              <el-form
                ref="formStep1"
                :model="form"
                :rules="rules"
                label-position="top"
                class="step-form"
              >
                <el-form-item label="给你的智能体起个名字" prop="deviceName">
                  <el-input
                    v-model="form.deviceName"
                    size="medium"
                    class="terminal-input large-input"
                    :maxlength="20"
                    show-word-limit
                    placeholder="例如：小爱"
                  />
                </el-form-item>
                <el-form-item label="它对我的称呼" prop="userNickname">
                  <el-input
                    v-model="form.userNickname"
                    size="medium"
                    class="terminal-input large-input"
                    :maxlength="20"
                    show-word-limit
                    placeholder="例如：小林，或你喜欢的称呼"
                  />
                </el-form-item>
              </el-form>
            </div>

            <div v-else-if="currentStep === 2" class="wizard-step">
              <div class="step-label">Step 2 · 能力设定</div>
              <div class="narrative-quote">
                声音是灵魂震颤的频率，记忆是时间凝结的琥珀。在此刻，你将决定它如何向世界发声，以及它能为你保留多少时光。
              </div>

              <div class="ability-section">
                <div class="ability-block ability-block--voice">
                  <div class="ability-label">声音音色</div>
                  <p class="ability-hint">已默认使用「回响现实官方服务」，请选择音色并试听。</p>
                  <el-select
                    v-model="form.ttsVoiceId"
                    filterable
                    :placeholder="voiceSelectPlaceholder"
                    :popper-append-to-body="false"
                    class="wizard-select ability-voice-select"
                    @visible-change="handleVoiceDropdownChange"
                  >
                    <el-option
                      v-for="(item, index) in voiceOptions"
                      :key="'voice-' + index"
                      :label="item.label"
                      :value="item.value"
                    >
                      <div class="voice-option-row">
                        <span>{{ item.label }}</span>
                        <template v-if="hasAudioPreview(item)">
                          <el-button
                            type="text"
                            :icon="playingVoice && currentPlayingVoiceId === item.value && !isPaused ? 'el-icon-video-pause' : 'el-icon-video-play'"
                            size="small"
                            class="play-btn-inline"
                            @click.stop="toggleAudioPlayback(item.value)"
                          />
                        </template>
                      </div>
                    </el-option>
                  </el-select>
                </div>

                <div class="ability-block ability-block--memory">
                  <div class="ability-label">记忆模式</div>
                  <div class="memory-cards">
                    <div
                      v-for="item in memoryCardList"
                      :key="item.value"
                      class="memory-card"
                      :class="{ 'memory-card--active': form.memModelId === item.value }"
                      @click="selectMemoryCard(item.value)"
                    >
                      <div class="memory-card__title">{{ item.title }}</div>
                      <div class="memory-card__desc">{{ item.desc }}</div>
                      <div v-if="item.value === 'Memory_bailian'" class="memory-card__hint">
                        按实际用量计费，可在余额和账单中查看费用。
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div v-else class="wizard-step step4-soul">
              <div class="step-label">Step 3 · 人格设定</div>
              <div class="narrative-quote">
                选择你喜欢的聊天性格，也可以写自己的设定。创建后，仍可在角色配置中修改。
              </div>

              <persona-preset-picker :value="form.systemPrompt" @input="applyPersonaPreset" @edit="focusPersonaEditor" />
              <el-button type="text" :aria-expanded="showSoulGenerators" @click="showSoulGenerators = !showSoulGenerators">
                {{ showSoulGenerators ? '收起更多生成方式' : '更多生成方式：模组、塔罗、盲盒' }}
              </el-button>

              <transition v-if="showSoulGenerators" name="soul-slide" mode="out-in">
                <div v-if="soulMethod === 'none'" key="choice" class="soul-choice">
                  <div class="soul-entry-cards">
                    <div class="soul-entry-card" @click="setSoulMethod('modules')">
                      <div class="soul-entry-icon">◇</div>
                      <div class="soul-entry-title">灵魂模组拼装</div>
                      <div class="soul-entry-desc">语气 · 身份 · 癖好，自由组合</div>
                    </div>
                    <div class="soul-entry-card" @click="setSoulMethod('tarot')">
                      <div class="soul-entry-icon">♠</div>
                      <div class="soul-entry-title">命运塔罗牌</div>
                      <div class="soul-entry-desc">翻开一张牌，接受命运</div>
                    </div>
                    <div class="soul-entry-card" @click="setSoulMethod('mystery')">
                      <div class="soul-entry-icon">◎</div>
                      <div class="soul-entry-title">关键词盲盒</div>
                      <div class="soul-entry-desc">随机抓取，惊喜合成</div>
                    </div>
                  </div>
                </div>

                <div v-else key="method" class="soul-method-panel">
                  <el-button type="text" class="soul-back-btn" @click="backToSoulMethodChoice">
                    ← 返回选择
                  </el-button>

                  <div v-if="soulMethod === 'modules'" class="soul-modules">
                    <div class="soul-module-row">
                      <span class="soul-module-label">语气</span>
                      <div class="soul-tag-wall">
                        <span
                          v-for="(desc, label) in SOUL_MODULES.tone"
                          :key="'tone-' + label"
                          class="fui-data-chip soul-tag"
                          :class="{ 'fui-data-chip--active soul-tag--active': soulModuleSelection.tone === label }"
                          @click="selectModuleTag('tone', label)"
                        >{{ label }}</span>
                      </div>
                    </div>
                    <div class="soul-module-row">
                      <span class="soul-module-label">身份</span>
                      <div class="soul-tag-wall">
                        <span
                          v-for="(desc, label) in SOUL_MODULES.role"
                          :key="'role-' + label"
                          class="fui-data-chip soul-tag"
                          :class="{ 'fui-data-chip--active soul-tag--active': soulModuleSelection.role === label }"
                          @click="selectModuleTag('role', label)"
                        >{{ label }}</span>
                      </div>
                    </div>
                    <div class="soul-module-row">
                      <span class="soul-module-label">癖好</span>
                      <div class="soul-tag-wall">
                        <span
                          v-for="(desc, label) in SOUL_MODULES.quirk"
                          :key="'quirk-' + label"
                          class="fui-data-chip soul-tag"
                          :class="{ 'fui-data-chip--active soul-tag--active': soulModuleSelection.quirk === label }"
                          @click="selectModuleTag('quirk', label)"
                        >{{ label }}</span>
                      </div>
                    </div>
                  </div>

                  <div v-else-if="soulMethod === 'tarot'" class="soul-tarot">
                    <div class="tarot-cards">
                      <div
                        v-for="card in TAROT_CARDS"
                        :key="card.id"
                        class="tarot-card"
                        :class="{ 'tarot-card--flipped': tarotFlipped === card.id }"
                        @click="flipTarot(card)"
                      >
                        <div class="tarot-card-inner">
                          <div class="tarot-card-back">?</div>
                          <div class="tarot-card-front">
                            <div class="tarot-card-name">{{ card.name }}</div>
                            <div class="tarot-card-prompt">{{ card.prompt }}</div>
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div v-else-if="soulMethod === 'mystery'" class="soul-mystery">
                    <div class="mystery-box-wrap" :class="{ 'mystery-box-wrap--opened': mysteryBoxOpened }">
                      <button type="button" class="mystery-box-btn" :disabled="mysteryBoxOpened" @click="openMysteryBox">
                        {{ mysteryBoxOpened ? '已开启' : '开启盲盒' }}
                      </button>
                    </div>
                    <div v-if="mysteryBoxOpened" class="mystery-keywords">
                      <span v-for="(kw, i) in mysteryPicked" :key="i" class="mystery-kw-tag">{{ kw }}</span>
                    </div>
                  </div>
                </div>
              </transition>

              <div class="soul-preview-block">
                <div class="fui-terminal-caption-row">
                  <span class="soul-preview-caption">人格设定（可编辑）</span>
                  <span v-if="typewriterGenerating" class="typewriter-indicator">Generating...</span>
                </div>
                <div class="fui-terminal-editor">
                  <div class="fui-terminal-gutter">
                    <span v-for="n in promptLineCount" :key="n" class="fui-terminal-line-num">{{ n }}</span>
                  </div>
                  <el-input
                    ref="personaEditor"
                    :value="promptDisplay"
                    type="textarea"
                    :rows="6"
                    :disabled="typewriterGenerating"
                    resize="none"
                    class="fui-terminal-textarea soul-preview-textarea"
                    placeholder="写下你希望它具有的性格、说话方式和兴趣..."
                    @input="onPromptInput"
                  />
                </div>
              </div>
            </div>
          </div>

          <div class="wizard-footer">
            <div class="left-actions">
              <el-button v-if="mode === 'update'" type="text" class="skip-btn" @click="handleSkip">
                跳过本次唤醒（可在角色配置中修改）
              </el-button>
              <el-button v-else type="text" class="skip-btn" @click="handleSkip">
                取消
              </el-button>
            </div>

            <div class="right-actions">
              <el-button v-if="currentStep > 1" @click="prevStep">上一步</el-button>
              <el-button v-if="currentStep < 3" type="primary" class="holo-btn-primary" @click="nextStep">
                下一步
              </el-button>
              <el-button v-else type="primary" class="holo-btn-primary" :loading="submitting" @click.prevent="handleFinish">
                {{ mode === 'create' ? '完成创建' : '完成唤醒' }}
              </el-button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </transition>
</template>

<script>
import Api from "@/apis/api";
import { getServiceUrl } from "@/apis/api";
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
        deviceName: [{ required: true, message: "请给你的智能体起一个名字", trigger: "blur" }],
        userNickname: [{ required: true, message: "请设置它对你的称呼", trigger: "blur" }],
      },
    };
  },
  computed: {
    stepList() {
      return [
        { title: "赋予身份", desc: "确立 TA 的名字与契约称呼" },
        { title: "能力设定", desc: "声音与记忆" },
        { title: "人格设定", desc: "选择模板或自定义" },
      ];
    },
    wizardTitle() {
      return this.mode === "create" ? "创建新的智能体" : "新用户唤醒向导";
    },
    wizardSubtitle() {
      return this.mode === "create"
        ? "为你的智能体注入「名字、羁绊与性格」"
        : "为你的智能体注入「名字、羁绊与性格」";
    },
    memoryCardList() {
      return [
        {
          value: "Memory_mem_local_short",
          title: "本地短期记忆",
          desc: "拥有短暂的记忆力，能流畅进行多轮对话，记得住上下文。",
        },
        {
          value: "Memory_bailian",
          title: "长期记忆 · 回响现实官方服务",
          desc: "赋予 TA 长期记忆能力，能记住你的喜好与习惯，越聊越懂你。",
        },
      ];
    },
    voiceSelectPlaceholder() {
      if (!this.voiceOptionsLoaded) return "加载中...";
      return this.voiceOptions.length === 0 ? "无可用音色" : "请选择音色";
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
                    resolve(`${getServiceUrl()}/voiceClone/play/${res.data.data}`);
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
        this.$message.warning("该音色暂无可预览的音频");
        return;
      }
      this.playingVoice = true;
      this.currentAudio = new Audio();
      this.currentAudio.src = audioUrl;
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
        if (!this.form.deviceName || !this.form.deviceName.trim()) {
          this.$message.warning("请给你的智能体起一个名字");
          return;
        }
        if (!this.form.userNickname || !this.form.userNickname.trim()) {
          this.$message.warning("请设置它对你的称呼");
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
        this.$message.warning('请等人格文字生成完成后再保存');
        return;
      }
      if (!(this.form.systemPrompt || '').trim()) {
        this.$message.warning('请选择人格模板，或填写自定义人格');
        this.currentStep = 3;
        return;
      }

      const deviceName = (this.form.deviceName || "").trim();
      const userNickname = (this.form.userNickname || "").trim();
      if (!deviceName) {
        this.$message.warning("请给你的智能体起一个名字");
        this.currentStep = 1;
        return;
      }
      if (!userNickname) {
        this.$message.warning("请设置它对你的称呼");
        this.currentStep = 1;
        return;
      }

      if (this.mode === "create") {
        this.doCreateAgent(deviceName, userNickname);
        return;
      }

      const agentId = this.currentAgentId || this.agentId;
      if (!agentId) {
        this.$message.error("无法确定当前智能体，请刷新页面后重试");
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
      console.log("[AwakeningWizard] 更新数据 agentId:", agentId, "payload:", payload);
      this.doUpdateAgentConfig(agentId, payload);
    },
    doCreateAgent(deviceName, userNickname) {
      this.submitting = true;
      const submitTimeout = setTimeout(() => {
        this.submitting = false;
        this.$message.error("请求超时，请检查网络后重试");
      }, 20000);

      Api.agent.addAgent(deviceName, (res) => {
        try {
          const data = res && res.data;
          if (!data || data.code !== 0) {
            clearTimeout(submitTimeout);
            this.submitting = false;
            this.$message.error((data && data.msg) || "创建智能体失败");
            return;
          }
          const newAgentId = data.data;
          if (!newAgentId) {
            clearTimeout(submitTimeout);
            this.submitting = false;
            this.$message.error("创建成功但未返回智能体 ID");
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
          console.log("[AwakeningWizard] 创建后更新配置 agentId:", newAgentId, "payload:", updatePayload);
          Api.agent.updateAgentConfig(newAgentId, updatePayload, (res2) => {
            clearTimeout(submitTimeout);
            this.submitting = false;
            try {
              const data2 = res2 && res2.data;
              if (data2 && data2.code === 0) {
                this.$message.success({ message: "智能体创建成功！", showClose: true });
                this.$emit("success", { agentId: newAgentId });
                this.closeWizard(true);
              } else {
                this.$message.warning("智能体已创建，但部分配置保存失败，可在角色配置中修改");
                this.$emit("success", { agentId: newAgentId });
                this.closeWizard(true);
              }
            } catch (e) {
              console.error("[AwakeningWizard] 创建后更新解析失败", e);
              this.$message.warning("智能体已创建，请稍后在角色配置中完善");
              this.$emit("success", { agentId: newAgentId });
              this.closeWizard(true);
            }
          });
        } catch (e) {
          clearTimeout(submitTimeout);
          this.submitting = false;
          console.error("[AwakeningWizard] 创建解析失败", e);
          this.$message.error("创建失败：" + (e && e.message ? e.message : "未知错误"));
        }
      });
    },
    doUpdateAgentConfig(agentId, payload) {
      const submitTimeout = setTimeout(() => {
        this.submitting = false;
        this.$message.error("请求超时，请检查网络后重试");
      }, 15000);

      try {
        Api.agent.updateAgentConfig(agentId, payload, (res) => {
          clearTimeout(submitTimeout);
          this.submitting = false;
          try {
            const data = res && res.data;
            if (data && data.code === 0) {
              this.$message.success({
                message: "唤醒完成，欢迎加入新的旅程！",
                showClose: true,
              });
              this.$emit("success", { agentId });
              this.closeWizard(true);
            } else {
              const msg = (data && data.msg) || "唤醒失败，请稍后重试";
              this.$message.error({ message: msg, showClose: true });
            }
          } catch (e) {
            console.error("[AwakeningWizard] 解析响应失败", e);
            this.$message.error("唤醒失败：响应解析异常");
          }
        });
      } catch (e) {
        clearTimeout(submitTimeout);
        this.submitting = false;
        console.error("[AwakeningWizard] 提交异常", e);
        this.$message.error("唤醒失败：" + (e && e.message ? e.message : "未知错误"));
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

<style scoped lang="scss">
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.35s ease;
}
.fade-enter,
.fade-leave-to {
  opacity: 0;
}

.awakening-overlay {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: auto;
}

/* 遮罩：bg-slate-900/20 backdrop-blur-sm 轻盈半透明 */
.awakening-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(15, 23, 42, 0.15);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

/* 主容器：max-w-2xl mx-auto 单栏居中 */
.awakening-container {
  position: relative;
  max-width: 672px;
  width: 90%;
  margin-left: auto;
  margin-right: auto;
  z-index: 51;
}

/* 主卡片：高级悬浮阴影 ring-slate-900/5 */
.awakening-card {
  position: relative;
  border-radius: 24px;
  padding: 28px 32px 24px;
  background: #fff;
  box-shadow: 0 20px 60px -15px rgba(0, 0, 0, 0.1);
  border: 1px solid rgba(15, 23, 42, 0.05);
}

/* 极简步骤条：当前 text-blue-600，未激活 text-slate-400 */
.fui-stepper {
  display: flex;
  align-items: flex-start;
  margin: 22px 0 20px;
  gap: 0;
}

.fui-stepper-track {
  flex: 1;
  height: 2px;
  min-width: 20px;
  max-width: 40px;
  margin-top: 7px;
  background: #e2e8f0;
  border-radius: 1px;
  transition: background 0.25s ease;
}

.fui-stepper-track--active {
  background: #2563eb;
}

.fui-stepper-node {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}

.fui-stepper-marker {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #cbd5e1;
  transition: all 0.25s ease;
}

.fui-stepper-node.is-active .fui-stepper-marker {
  width: 10px;
  height: 10px;
  background: #2563eb;
}

.fui-stepper-node.is-done .fui-stepper-marker {
  background: #2563eb;
}

.fui-stepper-label {
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.02em;
  color: #94a3b8;
  max-width: 56px;
  text-align: center;
  line-height: 1.3;
}

.fui-stepper-node.is-active .fui-stepper-label {
  color: #2563eb;
  font-weight: 600;
}

.fui-stepper-node.is-done .fui-stepper-label {
  color: #64748b;
}

/* 说明文案 */
.step-log {
  font-size: 12px;
  color: #64748b;
  margin: 0 0 10px;
}

/* 叙事引言：光束背景 + 粗竖线，醒目不放大 */
.narrative-quote {
  padding: 12px 16px 12px 24px;
  margin: 24px 0;
  background: linear-gradient(to right, rgba(238, 242, 255, 0.8), transparent);
  border-left: 4px solid #6366f1;
  border-radius: 0 12px 12px 0;
  font-size: 14px;
  font-style: italic;
  font-weight: 500;
  color: #334155;
  letter-spacing: 0.025em;
  line-height: 1.75;
  text-align: left;
}

.terminal-desc {
  font-size: 14px;
  font-weight: 400;
  color: #64748b;
  line-height: 1.8;
  margin: 0 0 20px;
  letter-spacing: 0.02em;
}

/* 输入框：丝滑磨砂质感，ring 勾勒，hover/focus 状态 */
.terminal-input.large-input ::v-deep .el-input__inner {
  height: 48px;
  font-size: 15px;
  padding: 12px 16px;
  border-radius: 12px;
  background: rgba(248, 250, 252, 0.5);
  border: none;
  box-shadow: 0 0 0 1px #e2e8f0;
  color: #0f172a;
  transition: background 0.25s ease, box-shadow 0.25s ease;
}

.terminal-input.large-input ::v-deep .el-input__inner:hover {
  background: #f8fafc;
}

.terminal-input.large-input ::v-deep .el-input__inner::placeholder {
  color: #94a3b8;
}

.terminal-input.large-input ::v-deep .el-input__inner:focus,
.terminal-input.large-input ::v-deep .el-input.is-focus .el-input__inner {
  background: #fff;
  outline: none;
  box-shadow: 0 0 0 2px #3b82f6;
  transition: background 0.25s ease, box-shadow 0.25s ease;
}

.terminal-input.large-input ::v-deep .el-input__count {
  color: #94a3b8;
  font-size: 12px;
}

.wizard-footer {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid #f1f5f9;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
}

/* 取消：幽灵按钮 */
.skip-btn {
  color: #64748b !important;
  border-radius: 8px !important;
}
.skip-btn:hover {
  color: #475569 !important;
  background: #f1f5f9 !important;
}

/* 下一步/完成：实心纯蓝 bg-blue-600 hover:bg-blue-700 */
.holo-btn-primary {
  background: #2563eb !important;
  border: none !important;
  border-radius: 8px !important;
  color: #fff !important;
  font-weight: 600 !important;
  padding: 8px 24px !important;
  box-shadow: none !important;
  transition: background 0.2s ease !important;
}
.holo-btn-primary:hover {
  background: #1d4ed8 !important;
  box-shadow: none !important;
  transform: none;
}

.wizard-header {
  margin-bottom: 18px;
  text-align: left;
}

.wizard-title {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
  letter-spacing: 0.02em;
}

.wizard-subtitle {
  margin-top: 6px;
  font-size: 13px;
  font-weight: 400;
  color: #64748b;
  letter-spacing: 0.02em;
}

.wizard-body {
  margin-top: 12px;
  min-height: 280px;
}

.wizard-step {
  text-align: left;
}

.step-form ::v-deep .el-form-item {
  margin-bottom: 28px;
}

.step-form ::v-deep .el-form-item__label {
  display: inline-flex;
  align-items: center;
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  letter-spacing: 0.02em;
}

.step-form ::v-deep .el-form-item.is-required .el-form-item__label::before {
  color: #f43f5e;
  vertical-align: middle;
}

.step-form ::v-deep .el-form-item__error {
  margin-top: 6px;
  padding-top: 2px;
}

.step-label {
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.02em;
  color: #0f172a;
  margin-bottom: 8px;
}

.step-title {
  font-size: 20px;
  font-weight: 700;
  color: #0f172a;
  margin: 0 0 12px;
}

.step-desc {
  font-size: 14px;
  font-weight: 400;
  color: #64748b;
  line-height: 1.8;
  margin: 0 0 18px;
  letter-spacing: 0.02em;
}

.highlight-name {
  color: #2563eb;
  font-weight: 600;
}

/* large-input 已由 terminal-input 统一为填充风格 */

.personality-title {
  font-family: "Consolas", "JetBrains Mono", ui-monospace, monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #64748b;
  margin-bottom: 8px;
}

.personality-group {
  margin-bottom: 10px;
}

.ability-section {
  display: flex;
  flex-direction: column;
  gap: 40px;
}

.ability-block {
  margin-bottom: 0;
}

.ability-block--memory {
  margin-top: 0;
}

.ability-label {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 10px;
}

.ability-hint {
  font-size: 12px;
  color: #94a3b8;
  margin: 0 0 12px;
  letter-spacing: 0.01em;
}

.wizard-select.ability-voice-select {
  width: 100%;
}
.wizard-select ::v-deep .el-input__inner {
  background: rgba(248, 250, 252, 0.5);
  border: none;
  box-shadow: 0 0 0 1px #e2e8f0;
  border-radius: 12px;
  color: #334155;
  height: 48px;
  transition: background 0.25s ease, box-shadow 0.25s ease;
}
.wizard-select ::v-deep .el-input__inner:hover {
  background: #f8fafc;
}
.wizard-select ::v-deep .el-input__inner:focus,
.wizard-select ::v-deep .el-input.is-focus .el-input__inner {
  background: #fff;
  box-shadow: 0 0 0 2px #3b82f6;
}

.voice-option-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  width: 100%;
}

.play-btn-inline {
  color: #2563eb !important;
  padding: 4px;
}

.memory-cards {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.memory-card {
  padding: 14px 16px;
  border-radius: 12px;
  border: 1px solid #e2e8f0;
  background: #fff;
  cursor: pointer;
  transition: border-color 0.2s ease, background 0.2s ease, box-shadow 0.2s ease;
}

.memory-card:hover {
  border-color: #93c5fd;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}

.memory-card--active {
  background: rgba(239, 246, 255, 0.3);
  border: none;
  box-shadow: 0 0 0 2px #3b82f6, 0 4px 14px rgba(59, 130, 246, 0.1);
}

.memory-card__title {
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
  margin-bottom: 6px;
}

.memory-card__desc {
  font-size: 13px;
  color: #64748b;
  line-height: 1.5;
}

.memory-card__hint {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: rgba(234, 88, 12, 0.9);
  background: #fff7ed;
  border-radius: 8px;
  padding: 8px 12px;
  margin-top: 12px;
  line-height: 1.5;
}

.personality-note {
  ::v-deep .el-textarea__inner {
    background: #fff;
    border-radius: 12px;
    border: 1px solid #e2e8f0;
    color: #0f172a;
    font-size: 13px;
  }
}

/* ========== Step 4 灵魂召唤 ========== */
.step4-soul .wizard-body {
  min-height: 320px;
}

.soul-slide-enter-active,
.soul-slide-leave-active {
  transition: all 0.3s ease;
}
.soul-slide-enter {
  opacity: 0;
  transform: translateX(20px);
}
.soul-slide-leave-to {
  opacity: 0;
  transform: translateX(-20px);
}

.soul-choice {
  margin-bottom: 16px;
}

.soul-entry-cards {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

.soul-entry-card {
  padding: 24px 20px;
  border-radius: 16px;
  border: none;
  box-shadow: 0 0 0 1px #e2e8f0;
  background: rgba(248, 250, 252, 0.5);
  cursor: pointer;
  transition: all 0.3s ease;
  text-align: center;
}

.soul-entry-card:hover {
  background: #fff;
  box-shadow: 0 0 0 2px #a5b4fc, 0 10px 25px -5px rgba(99, 102, 241, 0.1);
}

.soul-entry-icon {
  font-size: 28px;
  color: #2563eb;
  margin-bottom: 10px;
  line-height: 1;
}

.soul-entry-title {
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
  margin-bottom: 6px;
}

.soul-entry-desc {
  font-size: 12px;
  color: #64748b;
}

.soul-method-panel {
  margin-bottom: 16px;
  padding: 12px 0;
}

.soul-back-btn {
  color: #64748b !important;
  font-size: 13px;
  margin-bottom: 14px;
  padding: 0;
}
.soul-back-btn:hover {
  color: #2563eb !important;
}

.soul-modules {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.soul-module-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.soul-module-label {
  flex-shrink: 0;
  width: 48px;
  font-family: ui-monospace, "Cascadia Code", "JetBrains Mono", monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: #64748b;
}

.soul-tag-wall {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.soul-tag {
  padding: 6px 12px;
  font-family: ui-monospace, "Cascadia Code", "JetBrains Mono", monospace;
  font-size: 12px;
  letter-spacing: 0.04em;
  color: #2563eb;
  background: transparent;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s, color 0.2s;
}

.soul-tag:hover {
  border-color: #3b82f6;
  color: #1d4ed8;
  background: #eff6ff;
}

.soul-tag--active {
  background: #eff6ff;
  border-color: #3b82f6;
  color: #1d4ed8;
}

.soul-tarot {
  padding: 10px 0;
}

.tarot-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.tarot-card {
  aspect-ratio: 2/3;
  perspective: 800px;
  cursor: pointer;
}

.tarot-card-inner {
  position: relative;
  width: 100%;
  height: 100%;
  transition: transform 0.5s ease;
  transform-style: preserve-3d;
}

.tarot-card--flipped .tarot-card-inner {
  transform: rotateY(180deg);
}

.tarot-card-back,
.tarot-card-front {
  position: absolute;
  inset: 0;
  backface-visibility: hidden;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 12px;
  text-align: center;
}

.tarot-card-back {
  background: linear-gradient(135deg, #eff6ff, #f0f9ff);
  border: 1px solid #e2e8f0;
  font-size: 28px;
  color: #64748b;
  font-weight: 700;
}

.tarot-card-front {
  background: #fff;
  border: 1px solid #e2e8f0;
  transform: rotateY(180deg);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.08);
}

.tarot-card-name {
  font-size: 16px;
  font-weight: 600;
  color: #0f172a;
  margin-bottom: 8px;
}

.tarot-card-prompt {
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
  overflow-y: auto;
}

.soul-mystery {
  text-align: center;
  padding: 20px 0;
}

.mystery-box-wrap {
  margin-bottom: 16px;
}

.mystery-box-wrap--opened .mystery-box-btn {
  opacity: 0.6;
  cursor: default;
  animation: mystery-shake 0.5s ease;
}

.mystery-box-btn {
  padding: 16px 48px;
  font-size: 18px;
  font-weight: 600;
  color: #fff;
  background: #2563eb;
  border: none;
  border-radius: 999px;
  cursor: pointer;
  transition: background 0.2s, transform 0.2s;
}

.mystery-box-btn:hover:not(:disabled) {
  background: #1d4ed8;
  transform: scale(1.02);
}

.mystery-box-btn:active:not(:disabled) {
  animation: mystery-shake 0.4s ease;
}

@keyframes mystery-shake {
  0%, 100% { transform: translateX(0); }
  20% { transform: translateX(-4px); }
  40% { transform: translateX(4px); }
  60% { transform: translateX(-2px); }
  80% { transform: translateX(2px); }
}

.mystery-keywords {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 10px;
}

.mystery-kw-tag {
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 14px;
  color: #2563eb;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
}

.soul-preview-block {
  margin-top: 20px;
  padding-top: 20px;
  border-top: 1px solid #e2e8f0;
}

.fui-terminal-caption-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.soul-preview-caption {
  font-size: 14px;
  font-weight: 600;
  color: #1e293b;
}

.fui-terminal-caption {
  font-family: "Consolas", "JetBrains Mono", ui-monospace, monospace;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.1em;
  color: #64748b;
}

.typewriter-indicator {
  font-size: 10px;
  color: #94a3b8;
  animation: typewriter-blink 1s ease-in-out infinite;
}

@keyframes typewriter-blink {
  0%, 100% { opacity: 0.6; }
  50% { opacity: 1; }
}

.fui-terminal-editor {
  display: flex;
  border: none;
  box-shadow: 0 0 0 1px #e2e8f0;
  background: #f8fafc;
  border-radius: 12px;
  min-height: 140px;
  transition: box-shadow 0.25s ease, background 0.25s ease;
}

.fui-terminal-editor:focus-within {
  box-shadow: 0 0 0 2px #6366f1;
  background: #fff;
}

.fui-terminal-gutter {
  flex-shrink: 0;
  padding: 10px 8px 10px 12px;
  background: transparent;
  border-right: 1px solid #e2e8f0;
  font-family: "JetBrains Mono", "Consolas", ui-monospace, monospace;
  font-size: 12px;
  color: #cbd5e1;
  line-height: 1.6;
  user-select: none;
  text-align: right;
}

.fui-terminal-line-num {
  display: block;
}

.fui-terminal-textarea.soul-preview-textarea {
  flex: 1;
  margin-top: 0;
}
.fui-terminal-textarea.soul-preview-textarea ::v-deep .el-textarea__inner {
  font-family: "JetBrains Mono", "Consolas", ui-monospace, monospace;
  font-size: 14px;
  line-height: 1.6;
  background: transparent !important;
  border: none !important;
  border-radius: 0;
  color: #475569;
  padding: 10px 12px;
  resize: none;
}
.fui-terminal-textarea.soul-preview-textarea ::v-deep .el-textarea__inner::placeholder {
  color: #94a3b8;
}

.soul-preview-textarea {
  margin-top: 8px;
}

.right-actions {
  display: flex;
  align-items: center;
  gap: 10px;
}
</style>
