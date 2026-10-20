<template>
  <div class="xn-page rc">
    <page-header :title="form.agentName || $t('roleConfig.title')" back="/home" :back-label="$t('xn.agents.rc.back')"
      :description="$t('xn.agents.rc.desc')">
      <template v-if="agentId && ready">
        <el-button :disabled="!hasUnsavedChanges" @click="discardChanges">{{ $t('xn.agents.rc.discard') }}</el-button>
        <el-button @click="resetToDefaults"><xn-icon name="refresh" /> {{ $t('xn.agents.rc.resetDefaults') }}</el-button>
        <el-button type="primary" :disabled="!hasUnsavedChanges" @click="saveConfig"><xn-icon name="check" /> {{ $t('roleConfig.saveConfig') }}</el-button>
      </template>
    </page-header>

    <!-- 没有指定智能体 -->
    <div v-if="!agentId" class="xn-panel">
      <xn-empty icon="agent" :title="$t('xn.agents.rc.noAgentTitle')" :description="$t('xn.agents.rc.noAgentDesc')">
        <el-button type="primary" @click="goToHome">{{ $t('xn.agents.rc.back') }}</el-button>
      </xn-empty>
    </div>

    <!-- 加载失败 -->
    <div v-else-if="loadFailed" class="xn-panel">
      <xn-empty error :description="loadFailedMsg || $t('xn.common.loadFailedDesc')" @retry="reload">
        <el-button @click="goToHome">{{ $t('xn.agents.rc.back') }}</el-button>
        <el-button type="primary" @click="reload"><xn-icon name="refresh" /> {{ $t('xn.common.retry') }}</el-button>
      </xn-empty>
    </div>

    <template v-else>
      <div v-if="hasUnsavedChanges" class="rc-notice" role="status">
        <xn-icon name="info" /> <span>{{ $t('xn.agents.rc.unsaved') }}{{ $t('roleConfig.restartNotice') }}</span>
      </div>

      <el-form ref="form" :model="form" :rules="rules" label-position="top" class="rc-grid" v-loading="!ready"
        @submit.native.prevent>
        <!-- 角色设定 -->
        <section class="xn-panel">
          <header class="xn-panel__head">
            <div>
              <h2 class="xn-panel__title">{{ $t('xn.agents.rc.personaTitle') }}</h2>
              <p class="rc-sub">{{ $t('xn.agents.rc.personaDesc') }}</p>
            </div>
          </header>
          <div class="xn-panel__body">
            <el-form-item :label="$t('roleConfig.userNickname')" class="rc-nick">
              <el-input v-model="form.userNickname" :placeholder="$t('xn.agents.rc.nicknamePlaceholder')" maxlength="20" show-word-limit />
            </el-form-item>
            <el-form-item :label="$t('roleConfig.roleIntroduction')" prop="systemPrompt">
              <persona-preset-picker v-model="form.systemPrompt" class="rc-presets" @edit="focusPersonaEditor" />
              <el-input
                ref="personaEditor"
                type="textarea"
                :rows="9"
                resize="vertical"
                :placeholder="$t('xn.agents.rc.promptPlaceholder')"
                v-model="form.systemPrompt"
                maxlength="2000"
                show-word-limit
                class="rc-prompt"
              />
            </el-form-item>
          </div>
        </section>

        <!-- 模型与声音 -->
        <section class="xn-panel">
          <header class="xn-panel__head">
            <div>
              <h2 class="xn-panel__title">{{ $t('xn.agents.rc.modelTitle') }}</h2>
              <p class="rc-sub">{{ $t('xn.agents.rc.modelDesc') }}</p>
            </div>
          </header>
          <div class="xn-panel__body">
            <!-- ASR 独立占一行（VAD 已移除） -->
            <el-form-item :label="$t('roleConfig.asr')">
              <el-select v-model="form.model.asrModelId" filterable :placeholder="$t('roleConfig.pleaseSelect')"
                class="rc-select" @change="handleModelChange('ASR', $event)">
                <el-option v-for="(item, optionIndex) in modelOptions['ASR']" :key="`option-asr-${optionIndex}`"
                  :label="item.label" :value="item.value" />
              </el-select>
            </el-form-item>

            <el-form-item v-for="(model, index) in displayModels" :key="`model-${index}`"
              :label="$t('roleConfig.' + model.type.toLowerCase())">
              <el-select v-model="form.model[model.key]" filterable :placeholder="$t('roleConfig.pleaseSelect')"
                class="rc-select" @change="handleModelChange(model.type, $event)">
                <el-option v-for="(item, optionIndex) in optionsFor(model.type)" :key="`option-${index}-${optionIndex}`"
                  :label="item.label" :value="item.value" />
              </el-select>

              <!-- 功能管理：LLM 行 -->
              <div v-if="model.type === 'LLM'" class="rc-fn">
                <div class="rc-fn__tags">
                  <span class="xn-muted rc-fn__label">{{ $t('xn.agents.rc.functions') }}</span>
                  <template v-if="currentFunctions.length">
                    <span v-for="f in currentFunctions" :key="f.id" class="xn-tag xn-tag--lake">{{ f.name }}</span>
                  </template>
                  <span v-else class="xn-muted">{{ $t('xn.agents.rc.noFunctions') }}</span>
                </div>
                <el-button size="small" @click="openFunctionDialog"><xn-icon name="tune" /> {{ $t('roleConfig.editFunctions') }}</el-button>
              </div>

              <!-- 记忆模式：聊天记录上报方式 -->
              <div v-if="model.type === 'Memory'" class="rc-sub-field">
                <span class="rc-sub-field__label">{{ $t('xn.agents.rc.chatReport') }}</span>
                <el-radio-group v-model="form.chatHistoryConf" size="small" @change="updateChatHistoryConf">
                  <el-radio-button :label="1">{{ $t('roleConfig.reportText') }}</el-radio-button>
                  <el-radio-button :label="2">{{ $t('roleConfig.reportTextVoice') }}</el-radio-button>
                </el-radio-group>
                <p v-if="form.model.memModelId === 'Memory_bailian'" class="rc-hint">{{ $t('xn.agents.wizard.memoryBilling') }}</p>
              </div>
            </el-form-item>

            <el-form-item :label="$t('roleConfig.voiceType')">
              <el-select v-model="form.ttsVoiceId" filterable :placeholder="$t('roleConfig.pleaseSelect')"
                :no-data-text="$t('xn.agents.rc.noVoices')" class="rc-select" @visible-change="onVoiceDropdown">
                <el-option v-for="(item, index) in voiceOptions" :key="`voice-${index}`" :label="item.label" :value="item.value">
                  <div class="rc-voice-opt">
                    <span>{{ item.label }}</span>
                    <el-button v-if="hasAudioPreview(item)" type="text" size="small" class="rc-play"
                      :icon="playingVoice && currentPlayingVoiceId === item.value && !isPaused ? 'el-icon-video-pause' : 'el-icon-video-play'"
                      :aria-label="$t('xn.agents.wizard.preview')"
                      @click.stop="toggleAudioPlayback(item.value)" />
                  </div>
                </el-option>
              </el-select>
            </el-form-item>
          </div>
        </section>
      </el-form>
    </template>

    <function-dialog
      v-if="agentId"
      v-model="showFunctionDialog"
      :functions="currentFunctions"
      :all-functions="allFunctions"
      :agent-id="agentId"
      @update-functions="handleUpdateFunctions"
      @dialog-closed="handleDialogClosed"
    />
  </div>
</template>

<script>
import Api from "@/apis/api";
import FunctionDialog from "@/components/FunctionDialog.vue";
import i18n from "@/i18n";
import PersonaPresetPicker from '@/components/PersonaPresetPicker.vue';
import { playableUrl } from '@/utils/media';

// 与 AwakeningWizard / TemplateQuickConfig / OfficialServiceDefaults 一致的默认模型值
const ROLE_CONFIG_DEFAULTS = {
  vadModelId: "VAD_SileroVAD",
  asrModelId: "ASR_Qwen3ASRRealtime",
  llmModelId: "LLM_QwenPlusOfficial",
  vllmModelId: "VLLM_QwenVLVLLM",
  ttsModelId: "TTS_QwenAudioTTSPlus",
  ttsVoiceId: "TTS_QwenAudioTTSPlus_0001",
  memModelId: "Memory_mem_local_short",
  chatHistoryConf: 2,
  intentModelId: "Intent_function_call",
  deviceName: "小智",
  userNickname: "主人",
};
// 页面上可选的记忆模式（原页面同样只显示这两项）
const MEMORY_CHOICES = ['Memory_mem_local_short', 'Memory_bailian'];

export default {
  name: "RoleConfigPage",
  components: { FunctionDialog, PersonaPresetPicker },
  data() {
    return {
      form: {
        agentCode: "",
        agentName: "",
        deviceName: ROLE_CONFIG_DEFAULTS.deviceName,
        userNickname: ROLE_CONFIG_DEFAULTS.userNickname,
        ttsVoiceId: "",
        chatHistoryConf: 0,
        systemPrompt: "",
        summaryMemory: "",
        langCode: "",
        language: "",
        sort: "",
        model: {
          ttsModelId: "",
          vadModelId: ROLE_CONFIG_DEFAULTS.vadModelId,
          asrModelId: "",
          llmModelId: "",
          vllmModelId: "",
          memModelId: "",
          intentModelId: ROLE_CONFIG_DEFAULTS.intentModelId,
        },
      },
      rules: {
        systemPrompt: [{
          validator: (rule, value, cb) => ((value || '').trim() ? cb() : cb(new Error(this.$t('xn.agents.personaRequired')))),
          trigger: 'blur',
        }],
      },
      // 显式控制渲染顺序：ASR 单独行，其余 LLM/VLM/Memory/TTS 依次（无 VAD、无 Intent）
      displayModels: [
        { label: this.$t("roleConfig.llm"), key: "llmModelId", type: "LLM" },
        { label: this.$t("roleConfig.vllm"), key: "vllmModelId", type: "VLLM" },
        { label: this.$t("roleConfig.memory"), key: "memModelId", type: "Memory" },
        { label: this.$t("roleConfig.tts"), key: "ttsModelId", type: "TTS" },
      ],
      // fetchModelOptions 遍历用（不含 Intent，不再加载 Intent 选项）
      models: [
        { label: this.$t("roleConfig.asr"), key: "asrModelId", type: "ASR" },
        { label: this.$t("roleConfig.llm"), key: "llmModelId", type: "LLM" },
        { label: this.$t("roleConfig.vllm"), key: "vllmModelId", type: "VLLM" },
        { label: this.$t("roleConfig.memory"), key: "memModelId", type: "Memory" },
        { label: this.$t("roleConfig.tts"), key: "ttsModelId", type: "TTS" },
      ],
      llmModeTypeMap: new Map(),
      modelOptions: {},
      voiceOptions: [],
      voiceDetails: {},
      showFunctionDialog: false,
      currentFunctions: [],
      allFunctions: [],
      originalFunctions: [],
      functionsBaselineSnapshot: [],
      playingVoice: false,
      isPaused: false,
      currentAudio: null,
      currentPlayingVoiceId: null,
      initializedSnapshot: null,
      initializationReady: false,
      loadFailed: false,
      loadFailedMsg: '',
    };
  },
  computed: {
    agentId() {
      return this.$route.query.agentId || '';
    },
    ready() {
      return this.initializationReady;
    },
    hasUnsavedChanges() {
      if (!this.initializationReady || !this.initializedSnapshot) return false;
      const f = this.form;
      const s = this.initializedSnapshot;
      return (
        f.deviceName !== s.deviceName ||
        f.userNickname !== s.userNickname ||
        f.systemPrompt !== s.systemPrompt ||
        f.summaryMemory !== s.summaryMemory ||
        f.ttsVoiceId !== s.ttsVoiceId ||
        f.chatHistoryConf !== s.chatHistoryConf ||
        f.model.asrModelId !== s.model.asrModelId ||
        f.model.llmModelId !== s.model.llmModelId ||
        f.model.vllmModelId !== s.model.vllmModelId ||
        f.model.ttsModelId !== s.model.ttsModelId ||
        f.model.memModelId !== s.model.memModelId ||
        !this.functionsEqual(this.currentFunctions, this.functionsBaselineSnapshot)
      );
    },
  },
  methods: {
    optionsFor(type) {
      return (this.modelOptions[type] || []).filter((item) => !item.isHidden && (type !== 'Memory' || MEMORY_CHOICES.includes(item.value)));
    },
    focusPersonaEditor() {
      this.$nextTick(() => { if (this.$refs.personaEditor) this.$refs.personaEditor.focus(); });
    },
    goToHome() {
      this.$router.push("/home");
    },
    reload() {
      this.loadFailed = false;
      this.loadFailedMsg = '';
      this.initializationReady = false;
      this.fetchAgentConfig(this.agentId);
      this.fetchModelOptions();
    },

    takeSnapshot() {
      const f = this.form;
      this.initializedSnapshot = {
        deviceName: f.deviceName,
        userNickname: f.userNickname,
        systemPrompt: f.systemPrompt,
        summaryMemory: f.summaryMemory,
        ttsVoiceId: f.ttsVoiceId,
        chatHistoryConf: f.chatHistoryConf,
        model: {
          asrModelId: f.model.asrModelId,
          llmModelId: f.model.llmModelId,
          vllmModelId: f.model.vllmModelId,
          ttsModelId: f.model.ttsModelId,
          memModelId: f.model.memModelId,
        },
      };
      this.functionsBaselineSnapshot = JSON.parse(JSON.stringify(this.currentFunctions));
      this.initializationReady = true;
    },

    /** 放弃未保存的修改：回到最近一次加载 / 保存时的状态 */
    discardChanges() {
      const s = this.initializedSnapshot;
      if (!s) return;
      this.form.deviceName = s.deviceName;
      this.form.userNickname = s.userNickname;
      this.form.systemPrompt = s.systemPrompt;
      this.form.summaryMemory = s.summaryMemory;
      this.form.chatHistoryConf = s.chatHistoryConf;
      Object.assign(this.form.model, s.model);
      this.currentFunctions = JSON.parse(JSON.stringify(this.functionsBaselineSnapshot));
      this.originalFunctions = JSON.parse(JSON.stringify(this.functionsBaselineSnapshot));
      // 切换语音合成模型会触发清空音色的 watcher，等它执行完再恢复音色
      this.$nextTick(() => {
        this.form.ttsVoiceId = s.ttsVoiceId;
        if (this.$refs.form) this.$refs.form.clearValidate();
      });
    },

    functionsEqual(a, b) {
      if (a.length !== b.length) return false;
      for (let i = 0; i < a.length; i++) {
        if (a[i].id !== b[i].id || JSON.stringify(a[i].params) !== JSON.stringify(b[i].params)) return false;
      }
      return true;
    },

    saveConfig() {
      if (!(this.form.systemPrompt || '').trim()) {
        this.$message.warning(this.$t('xn.agents.personaRequired'));
        if (this.$refs.form) this.$refs.form.validateField('systemPrompt');
        this.focusPersonaEditor();
        return;
      }
      const configData = {
        agentCode: this.form.agentCode,
        agentName: this.form.agentName,
        deviceName: this.form.deviceName,
        userNickname: this.form.userNickname,
        asrModelId: this.form.model.asrModelId,
        vadModelId: this.form.model.vadModelId,
        llmModelId: this.form.model.llmModelId,
        vllmModelId: this.form.model.vllmModelId,
        ttsModelId: this.form.model.ttsModelId,
        ttsVoiceId: this.form.ttsVoiceId,
        chatHistoryConf: this.form.chatHistoryConf,
        memModelId: this.form.model.memModelId,
        intentModelId: this.form.model.intentModelId,
        systemPrompt: this.form.systemPrompt,
        summaryMemory: this.form.summaryMemory,
        langCode: this.form.langCode,
        language: this.form.language,
        sort: this.form.sort,
        functions: this.currentFunctions.map((item) => {
          return {
            pluginId: item.id,
            paramInfo: item.params,
          };
        }),
      };
      Api.agent.updateAgentConfig(this.agentId, configData, ({ data }) => {
        if (data.code === 0) {
          this.$message.success({
            message: i18n.t("roleConfig.saveSuccess"),
            showClose: true,
          });
          this.takeSnapshot();
        } else {
          this.$message.error({
            message: data.msg || i18n.t("roleConfig.saveFailed"),
            showClose: true,
          });
        }
      });
    },

    fetchAgentConfig(agentId) {
      Api.agent.getDeviceConfig(agentId, ({ data }) => {
        if (data.code === 0) {
          this.form = {
            ...this.form,
            ...data.data,
            chatHistoryConf: data.data.memModelId === "Memory_nomem" ? 2 : (data.data.chatHistoryConf == null ? 2 : data.data.chatHistoryConf),
            model: {
              ttsModelId: data.data.ttsModelId,
              vadModelId: data.data.vadModelId || ROLE_CONFIG_DEFAULTS.vadModelId,
              asrModelId: data.data.asrModelId,
              llmModelId: data.data.llmModelId,
              vllmModelId: data.data.vllmModelId,
              memModelId: data.data.memModelId === "Memory_nomem" ? "Memory_mem_local_short" : data.data.memModelId,
              intentModelId: ROLE_CONFIG_DEFAULTS.intentModelId,
            },
          };
          const savedMappings = data.data.functions || [];

          const ensureFuncs = this.allFunctions.length
            ? Promise.resolve()
            : this.fetchAllFunctions();

          ensureFuncs.then(() => {
            this.currentFunctions = savedMappings.map((mapping) => {
              const meta = this.allFunctions.find((f) => f.id === mapping.pluginId);
              if (!meta) {
                return { id: mapping.pluginId, name: mapping.pluginId, params: {} };
              }
              return {
                id: mapping.pluginId,
                name: meta.name,
                params: mapping.paramInfo || { ...meta.params },
                fieldsMeta: meta.fieldsMeta,
              };
            });
            this.originalFunctions = JSON.parse(JSON.stringify(this.currentFunctions));
            // 等音色列表的 watcher 处理完，再记录初始状态，避免误判为“有未保存的修改”
            this.$nextTick(() => this.takeSnapshot());
          }).catch(() => {
            this.loadFailed = true;
          });
        } else {
          this.loadFailed = true;
          this.$message.error(data.msg || i18n.t("roleConfig.fetchConfigFailed"));
        }
      }, (info) => {
        // 业务错误（如智能体不存在、无权查看）：显示失败状态
        this.loadFailed = true;
        this.loadFailedMsg = (info && info.data && info.data.msg) || '';
      });
    },

    fetchModelOptions() {
      this.models.forEach((model) => {
        if (model.type != "LLM") {
          Api.model.getModelNames(model.type, "", ({ data }) => {
            if (data.code === 0) {
              this.$set(
                this.modelOptions,
                model.type,
                data.data.map((item) => ({
                  value: item.id,
                  label: item.modelName,
                  isHidden: false,
                }))
              );
            } else {
              this.$message.error(data.msg || i18n.t("roleConfig.fetchModelsFailed"));
            }
          });
        } else {
          Api.model.getLlmModelCodeList("", ({ data }) => {
            if (data.code === 0) {
              let LLMdata = [];
              data.data.forEach((item) => {
                LLMdata.push({
                  value: item.id,
                  label: item.modelName,
                  isHidden: false,
                });
                this.llmModeTypeMap.set(item.id, item.type);
              });
              this.$set(this.modelOptions, model.type, LLMdata);
            } else {
              this.$message.error(data.msg || i18n.t("roleConfig.fetchModelsFailed"));
            }
          });
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
        if (data.code === 0 && data.data) {
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
        } else {
          this.voiceOptions = [];
          this.voiceDetails = {};
        }
      });
    },

    handleModelChange(type) {
      if (type === "Memory") {
        this.form.chatHistoryConf = 2;
      }
    },

    fetchAllFunctions() {
      return new Promise((resolve, reject) => {
        Api.model.getPluginFunctionList(null, ({ data }) => {
          if (data.code === 0) {
            this.allFunctions = data.data.map((item) => {
              const meta = JSON.parse(item.fields || "[]");
              const params = meta.reduce((m, f) => {
                m[f.key] = f.default;
                return m;
              }, {});
              return { ...item, fieldsMeta: meta, params };
            });
            resolve();
          } else {
            this.$message.error(data.msg || i18n.t("roleConfig.fetchPluginsFailed"));
            reject();
          }
        });
      });
    },

    openFunctionDialog() {
      if (this.allFunctions.length === 0) {
        this.fetchAllFunctions().then(() => (this.showFunctionDialog = true)).catch(() => {});
      } else {
        this.showFunctionDialog = true;
      }
    },

    handleUpdateFunctions(selected) {
      this.currentFunctions = selected;
    },

    handleDialogClosed(saved) {
      if (!saved) {
        this.currentFunctions = JSON.parse(JSON.stringify(this.originalFunctions));
      } else {
        this.originalFunctions = JSON.parse(JSON.stringify(this.currentFunctions));
      }
      this.showFunctionDialog = false;
    },

    resetToDefaults() {
      this.$confirm(
        this.$t("roleConfig.confirmReset"),
        this.$t("xn.agents.rc.resetDefaults"),
        {
          confirmButtonText: this.$t("xn.agents.rc.resetDefaults"),
          cancelButtonText: this.$t("common.cancel"),
          type: "warning",
        }
      ).then(() => {
        // 保留智能体身份(agentCode/agentName)、提示词、记忆内容和已有功能映射
        this.form.model.asrModelId = ROLE_CONFIG_DEFAULTS.asrModelId;
        this.form.model.llmModelId = ROLE_CONFIG_DEFAULTS.llmModelId;
        this.form.model.vllmModelId = ROLE_CONFIG_DEFAULTS.vllmModelId;
        this.form.model.ttsModelId = ROLE_CONFIG_DEFAULTS.ttsModelId;
        this.form.model.memModelId = ROLE_CONFIG_DEFAULTS.memModelId;
        this.form.model.vadModelId = ROLE_CONFIG_DEFAULTS.vadModelId;
        this.form.model.intentModelId = ROLE_CONFIG_DEFAULTS.intentModelId;
        this.form.deviceName = ROLE_CONFIG_DEFAULTS.deviceName;
        this.form.userNickname = ROLE_CONFIG_DEFAULTS.userNickname;
        this.form.chatHistoryConf = ROLE_CONFIG_DEFAULTS.chatHistoryConf;
        this.form.ttsVoiceId = ROLE_CONFIG_DEFAULTS.ttsVoiceId;
        this.$message.info(this.$t('xn.agents.rc.resetDone'));
      }).catch(() => {});
    },

    updateChatHistoryConf() {
      if (this.form.model.memModelId === "Memory_nomem") {
        this.form.model.memModelId = "Memory_mem_local_short";
        this.form.chatHistoryConf = 2;
      }
    },

    // ====== 音色预览相关 ======
    onVoiceDropdown(open) {
      if (!open && this.currentAudio) {
        this.currentAudio.pause();
        this.playingVoice = false;
      }
    },
    hasAudioPreview(item) {
      const isCloneAudio =
        item.hasCloneAudio || (item.value && !item.value.startsWith("TTS"));
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
          this.currentAudio.play().catch((error) => {
            console.error("恢复播放失败:", error);
            this.$message.warning(this.$t('xn.agents.wizard.playFailed'));
          });
          this.isPaused = false;
        } else {
          this.currentAudio.pause();
          this.isPaused = true;
        }
        return;
      }
      this.playVoicePreview(voiceId);
    },

    playVoicePreview(voiceId = null) {
      const targetVoiceId = voiceId || this.form.ttsVoiceId;
      if (!targetVoiceId) {
        this.$message.warning(this.$t('xn.agents.rc.pickVoice'));
        return;
      }
      if (this.currentAudio) {
        this.currentAudio.pause();
        this.currentAudio = null;
      }
      this.isPaused = false;
      this.currentPlayingVoiceId = targetVoiceId;
      try {
        const voiceDetail = this.voiceDetails[targetVoiceId];
        let audioUrl = null;
        if (voiceDetail) {
          audioUrl =
            voiceDetail.voiceDemo ||
            voiceDetail.demoUrl ||
            voiceDetail.audioUrl ||
            voiceDetail.voice_demo ||
            voiceDetail.sample_voice;
          if (!audioUrl) {
            for (const key in voiceDetail) {
              const value = voiceDetail[key];
              if (
                typeof value === "string" &&
                (value.startsWith("http://") ||
                  value.startsWith("https://") ||
                  value.endsWith(".mp3") ||
                  value.endsWith(".wav") ||
                  value.endsWith(".ogg"))
              ) {
                audioUrl = value;
                break;
              }
            }
          }
        }
        if (!audioUrl) {
          this.$message.warning(this.$t('xn.agents.wizard.noPreview'));
          return;
        }
        const isCloneAudio =
          voiceDetail &&
          (voiceDetail.hasCloneAudio || (targetVoiceId && !targetVoiceId.startsWith("TTS")));
        if (!isCloneAudio) {
          this.playingVoice = true;
          this.currentAudio = new Audio();
          this.currentAudio.src = playableUrl(audioUrl);
          this.currentAudio.volume = 1.0;
          const timeoutId = setTimeout(() => {
            if (this.currentAudio && this.playingVoice) {
              this.$message.warning(this.$t('xn.agents.wizard.playSlow'));
              this.playingVoice = false;
            }
          }, 10000);
          this.currentAudio.onerror = () => {
            clearTimeout(timeoutId);
            this.$message.warning(this.$t('xn.agents.wizard.playFailed'));
            this.playingVoice = false;
          };
          this.currentAudio.onplay = () => {
            clearTimeout(timeoutId);
          };
          this.currentAudio.onended = () => {
            this.playingVoice = false;
          };
          this.currentAudio.play().catch(() => {
            clearTimeout(timeoutId);
            this.$message.warning(this.$t('xn.agents.wizard.playFailed'));
            this.playingVoice = false;
          });
        }
      } catch (error) {
        console.error("播放音频过程出错:", error);
        this.$message.error(this.$t('xn.agents.wizard.playFailed'));
        this.playingVoice = false;
      }
    },
  },

  watch: {
    "form.model.ttsModelId": {
      handler(newVal, oldVal) {
        if (oldVal && newVal !== oldVal) {
          this.form.ttsVoiceId = "";
          this.fetchVoiceOptions(newVal);
        } else {
          this.fetchVoiceOptions(newVal);
        }
      },
      immediate: true,
    },
    voiceOptions: {
      handler(newVal) {
        if (newVal && newVal.length > 0 && !this.form.ttsVoiceId) {
          this.form.ttsVoiceId = newVal[0].value;
        }
      },
      immediate: true,
    },
    // 同一页面切换到另一个智能体（例如从浏览器历史返回）
    agentId(id, old) {
      if (id && id !== old) this.reload();
    },
  },

  mounted() {
    const agentId = this.agentId;
    if (agentId) {
      this.fetchAgentConfig(agentId);
      this.fetchAllFunctions().catch(() => {});
    }
    this.fetchModelOptions();
  },

  beforeDestroy() {
    if (this.currentAudio) this.currentAudio.pause();
  },
};
</script>

<style scoped>
.rc-notice {
  display: flex; align-items: center; gap: 8px; margin: -4px 0 16px; padding: 10px 14px;
  border-radius: var(--xn-r); background: var(--xn-warning-soft); color: var(--xn-warning); font-size: 14px;
}
.rc-grid { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr); gap: 16px; align-items: start; min-height: 240px; }
.rc-grid .xn-panel + .xn-panel { margin-top: 0; }
.rc-sub { margin: 4px 0 0; font-size: 13px; color: var(--xn-ink-3); }
.rc-nick { max-width: 360px; }
.rc-presets { margin-bottom: 12px; }
.rc-prompt ::v-deep .el-textarea__inner { line-height: 1.7; }
.rc-grid ::v-deep .el-form-item__label { padding-bottom: 6px; line-height: 1.5; }
.rc-grid ::v-deep .el-form-item:last-child { margin-bottom: 0; }
.rc-select { width: 100%; }
.rc-fn { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-top: 10px; padding: 10px 12px; border-radius: var(--xn-r); background: var(--xn-mist-2); }
.rc-fn__tags { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; min-width: 0; font-size: 13px; line-height: 1.5; }
.rc-fn__label { margin-right: 2px; }
.rc-sub-field { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; margin-top: 10px; }
.rc-sub-field__label { font-size: 13px; color: var(--xn-ink-3); }
.rc-hint { flex-basis: 100%; margin: 0; font-size: 13px; line-height: 1.5; color: var(--xn-ink-3); }
.rc-voice-opt { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.rc-play { padding: 0; }
@media (max-width: 1180px) {
  .rc-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
