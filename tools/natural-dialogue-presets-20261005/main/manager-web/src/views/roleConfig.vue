<template>
  <div class="welcome">
    <HeaderBar />

    <div class="operation-bar">
      <h2 class="page-title">{{ $t("roleConfig.title") }}</h2>
    </div>

    <div class="main-wrapper">
      <div class="content-panel">
        <div class="content-area">
          <el-card class="config-card" shadow="never">
            <div class="config-header">
              <div class="header-icon">
                <img loading="lazy" src="@/assets/home/setting-user.png" alt="" />
              </div>
              <span class="header-title">{{ form.agentName }}</span>
              <div class="header-actions" v-if="hasUnsavedChanges">
                <div class="hint-text" v-if="hasUnsavedChanges">
                  <img loading="lazy" src="@/assets/home/info.png" alt="" />
                  <span>{{ $t("roleConfig.restartNotice") }}</span>
                </div>
                <el-button type="primary" class="save-btn" @click="saveConfig" :disabled="!hasUnsavedChanges">
                  {{ $t("roleConfig.saveConfig") }}
                </el-button>
                <button class="custom-close-btn" @click="resetToDefaults">×</button>
              </div>
            </div>
            <div class="divider"></div>

            <el-form ref="form" :model="form" label-width="120px">
              <div class="form-content">
                <div class="form-grid">
                  <div class="form-column">
                    <el-form-item :label="$t('roleConfig.userNickname') + '：'">
                      <el-input
                        v-model="form.userNickname"
                        class="form-input"
                        :placeholder="$t('roleConfig.userNickname')"
                        maxlength="20"
                      />
                    </el-form-item>
                    <el-form-item :label="$t('roleConfig.roleIntroduction') + '：'">
                      <persona-preset-picker v-model="form.systemPrompt" @edit="focusPersonaEditor" />
                      <el-input
                        ref="personaEditor"
                        type="textarea"
                        rows="9"
                        resize="none"
                        :placeholder="$t('roleConfig.pleaseEnterContent')"
                        v-model="form.systemPrompt"
                        maxlength="2000"
                        show-word-limit
                        class="form-textarea"
                      />
                    </el-form-item>

                    <el-form-item
                      :label="$t('roleConfig.languageCode') + '：'"
                      style="display: none"
                    >
                      <el-input
                        v-model="form.langCode"
                        :placeholder="$t('roleConfig.pleaseEnterLangCode')"
                        maxlength="10"
                        show-word-limit
                        class="form-input"
                      />
                    </el-form-item>
                    <el-form-item
                      :label="$t('roleConfig.interactionLanguage') + '：'"
                      style="display: none"
                    >
                      <el-input
                        v-model="form.language"
                        :placeholder="$t('roleConfig.pleaseEnterLangName')"
                        maxlength="10"
                        show-word-limit
                        class="form-input"
                      />
                    </el-form-item>
                  </div>
                  <div class="form-column">
                    <!-- ASR 独立占一行（VAD 已移除） -->
                    <el-form-item :label="$t('roleConfig.asr')" class="model-item">
                      <div class="model-select-wrapper">
                        <el-select
                          v-model="form.model.asrModelId"
                          filterable
                          :placeholder="$t('roleConfig.pleaseSelect')"
                          class="form-select"
                          @change="handleModelChange('ASR', $event)"
                        >
                          <el-option
                            v-for="(item, optionIndex) in modelOptions['ASR']"
                            :key="`option-asr-${optionIndex}`"
                            :label="item.label"
                            :value="item.value"
                          />
                        </el-select>
                      </div>
                    </el-form-item>
                    <el-form-item
                      v-for="(model, index) in displayModels"
                      :key="`model-${index}`"
                      :label="$t('roleConfig.' + model.type.toLowerCase())"
                      class="model-item"
                    >
                      <div class="model-select-wrapper">
                        <el-select
                          v-model="form.model[model.key]"
                          filterable
                          :placeholder="$t('roleConfig.pleaseSelect')"
                          class="form-select"
                          @change="handleModelChange(model.type, $event)"
                        >
                          <el-option
                            v-for="(item, optionIndex) in modelOptions[model.type]"
                            v-if="!item.isHidden && (model.type !== 'Memory' || ['Memory_mem_local_short', 'Memory_bailian'].includes(item.value))"
                            :key="`option-${index}-${optionIndex}`"
                            :label="item.label"
                            :value="item.value"
                          />
                        </el-select>
                        <!-- 功能管理按钮：LLM 行显示 -->
                        <div v-if="model.type === 'LLM'" class="function-icons">
                          <el-button
                            class="edit-function-btn"
                            @click="openFunctionDialog"
                            :class="{ 'active-btn': showFunctionDialog }"
                          >
                            {{ $t("roleConfig.editFunctions") }}
                          </el-button>
                        </div>
                        <div
                          v-if="model.type === 'Memory'"
                          class="chat-history-options"
                        >
                          <el-radio-group
                            v-model="form.chatHistoryConf"
                            @change="updateChatHistoryConf"
                          >
                            <el-radio-button :label="1">{{
                              $t("roleConfig.reportText")
                            }}</el-radio-button>
                            <el-radio-button :label="2">{{
                              $t("roleConfig.reportTextVoice")
                            }}</el-radio-button>
                          </el-radio-group>
                        </div>
                      </div>
                    </el-form-item>
                    <el-form-item :label="$t('roleConfig.voiceType')">
                      <el-select
                        v-model="form.ttsVoiceId"
                        filterable
                        :placeholder="$t('roleConfig.pleaseSelect')"
                        class="form-select"
                      >
                        <el-option
                          v-for="(item, index) in voiceOptions"
                          :key="`voice-${index}`"
                          :label="item.label"
                          :value="item.value"
                        >
                          <div
                            style="
                              display: flex;
                              justify-content: space-between;
                              align-items: center;
                            "
                          >
                            <span>{{ item.label }}</span>
                            <template v-if="hasAudioPreview(item)">
                              <el-button
                                type="text"
                                :icon="
                                  playingVoice &&
                                  currentPlayingVoiceId === item.value &&
                                  !isPaused
                                    ? 'el-icon-video-pause'
                                    : 'el-icon-video-play'
                                "
                                size="small"
                                @click.stop="toggleAudioPlayback(item.value)"
                                :loading="false"
                                class="play-button"
                              />
                            </template>
                          </div>
                        </el-option>
                      </el-select>
                    </el-form-item>
                  </div>
                </div>
              </div>
            </el-form>
          </el-card>
        </div>
      </div>
    </div>
    <function-dialog
      v-model="showFunctionDialog"
      :functions="currentFunctions"
      :all-functions="allFunctions"
      :agent-id="$route.query.agentId"
      @update-functions="handleUpdateFunctions"
      @dialog-closed="handleDialogClosed"
    />
  </div>
</template>

<script>
import Api from "@/apis/api";
import RequestService from "@/apis/httpRequest";
import FunctionDialog from "@/components/FunctionDialog.vue";
import HeaderBar from "@/components/HeaderBar.vue";
import i18n from "@/i18n";
import PersonaPresetPicker from '@/components/PersonaPresetPicker.vue';

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

export default {
  name: "RoleConfigPage",
  components: { HeaderBar, FunctionDialog, PersonaPresetPicker },
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
    };
  },
  computed: {
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
    focusPersonaEditor() {
      this.$nextTick(() => { if (this.$refs.personaEditor) this.$refs.personaEditor.focus(); });
    },
    goToHome() {
      this.$router.push("/home");
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

    functionsEqual(a, b) {
      if (a.length !== b.length) return false;
      for (let i = 0; i < a.length; i++) {
        if (a[i].id !== b[i].id || JSON.stringify(a[i].params) !== JSON.stringify(b[i].params)) return false;
      }
      return true;
    },

    saveConfig() {
      if (!(this.form.systemPrompt || '').trim()) {
        this.$message.warning('请选择人格模板，或填写自定义人格');
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
      Api.agent.updateAgentConfig(this.$route.query.agentId, configData, ({ data }) => {
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
            this.takeSnapshot();
          });
        } else {
          this.$message.error(data.msg || i18n.t("roleConfig.fetchConfigFailed"));
        }
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
              this.$message.error(data.msg || "获取LLM模型列表失败");
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

    handleModelChange(type, value) {
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
        this.fetchAllFunctions().then(() => (this.showFunctionDialog = true));
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
        this.$t("common.tip"),
        {
          confirmButtonText: this.$t("common.confirm"),
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
      }).catch(() => {});
    },

    updateChatHistoryConf() {
      if (this.form.model.memModelId === "Memory_nomem") {
        this.form.model.memModelId = "Memory_mem_local_short";
        this.form.chatHistoryConf = 2;
      }
    },

    // ====== 音色预览相关 ======
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
            this.$message.warning("无法恢复播放音频");
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
        this.$message.warning("请先选择一个音色");
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
          this.$message.warning("该音色暂无可预览的音频");
          return;
        }
        const isCloneAudio =
          voiceDetail &&
          (voiceDetail.hasCloneAudio || (targetVoiceId && !targetVoiceId.startsWith("TTS")));
        if (!isCloneAudio) {
          this.playingVoice = true;
          this.currentAudio = new Audio();
          this.currentAudio.src = audioUrl;
          this.currentAudio.volume = 1.0;
          const timeoutId = setTimeout(() => {
            if (this.currentAudio && this.playingVoice) {
              this.$message.warning("音频加载时间较长，请稍后重试");
              this.playingVoice = false;
            }
          }, 10000);
          this.currentAudio.onerror = () => {
            clearTimeout(timeoutId);
            console.error("音频播放错误");
            this.$message.warning("音频播放失败");
            this.playingVoice = false;
          };
          this.currentAudio.onplay = () => {
            clearTimeout(timeoutId);
          };
          this.currentAudio.onended = () => {
            this.playingVoice = false;
          };
          this.currentAudio.play().catch((error) => {
            clearTimeout(timeoutId);
            console.error("播放失败:", error);
            this.$message.warning("无法播放音频");
            this.playingVoice = false;
          });
        }
      } catch (error) {
        console.error("播放音频过程出错:", error);
        this.$message.error("播放音频过程出错");
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
  },

  mounted() {
    const agentId = this.$route.query.agentId;
    if (agentId) {
      this.fetchAgentConfig(agentId);
      this.fetchAllFunctions();
    }
    this.fetchModelOptions();
  },
};
</script>

<style scoped>
.welcome {
  min-width: 900px;
  height: 100vh;
  display: flex;
  position: relative;
  flex-direction: column;
  background: transparent;
  overflow: hidden;
}

.operation-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 1.5vh 24px;
}

.page-title {
  font-size: 24px;
  margin: 0;
  color: #0f172a;
}

.main-wrapper {
  margin: 1vh 22px;
  border-radius: 24px;
  height: calc(100vh - 24vh);
  box-shadow: 0 10px 40px -10px rgba(59, 130, 246, 0.16);
  position: relative;
  background: rgba(255, 255, 255, 0.45);
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  border: 1px solid rgba(255, 255, 255, 0.7);
  display: flex;
  flex-direction: column;
}

.content-panel {
  flex: 1;
  display: flex;
  overflow: hidden;
  height: 100%;
  border-radius: 20px;
  background: transparent;
}

.content-area {
  flex: 1;
  height: 100%;
  min-width: 600px;
  overflow: auto;
  background-color: transparent;
  display: flex;
  flex-direction: column;
}

.config-card {
  background: transparent;
  border: none;
  box-shadow: none;
  display: flex;
  flex-direction: column;
  flex: 1;
  overflow-y: auto;
}

.config-header {
  position: relative;
  display: flex;
  align-items: center;
  gap: 13px;
  padding: 0 0 5px 0;
  font-weight: 700;
  font-size: 19px;
  color: #0f172a;
}

.header-icon {
  width: 37px;
  height: 37px;
  background: linear-gradient(135deg, #3b82f6 0%, #6366f1 100%);
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
}

.header-icon img {
  width: 19px;
  height: 19px;
}

.divider {
  height: 1px;
  background: #e8f0ff;
}

.form-content {
  padding: 2vh 0;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

.form-column {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.form-input {
  width: 100%;
}

.form-select {
  width: 100%;
  height: 36px;
}

.play-button {
  color: #409eff;
  transition: color 0.3s;
}

.play-button:hover {
  color: #66b1ff;
}

.play-button.is-loading {
  color: #909399;
}

.form-textarea {
  width: 100%;
}

.voice-select-wrapper {
  display: flex;
  align-items: center;
  gap: 10px;
}

.template-container {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.template-item {
  height: 4vh;
  min-width: 60px;
  padding: 0 12px;
  border-radius: 8px;
  line-height: 4vh;
  font-weight: 400;
  font-size: 11px;
  text-align: center;
  background: rgba(37, 99, 235, 0.08);
  color: #2563eb;
  cursor: pointer;
  transition: background-color 0.3s ease;
  white-space: nowrap;
}

.template-item:hover {
  background-color: rgba(37, 99, 235, 0.16);
}

.model-select-wrapper {
  display: flex;
  align-items: center;
  width: 100%;
}

.model-row {
  display: flex;
  gap: 20px;
  margin-bottom: 6px;
}

.model-row .model-item {
  flex: 1;
  margin-bottom: 0;
}

.model-row .el-form-item__label {
  font-size: 12px !important;
  color: #3d4566 !important;
  font-weight: 400;
  line-height: 22px;
  padding-bottom: 2px;
}

.function-icons {
  display: flex;
  align-items: center;
  margin-left: auto;
  padding-left: 10px;
}

::v-deep .el-form-item__label {
  font-size: 12px !important;
  color: #3d4566 !important;
  font-weight: 400;
  line-height: 22px;
  padding-bottom: 2px;
}

::v-deep .el-textarea .el-input__count {
  color: #909399;
  background: none;
  position: absolute;
  font-size: 12px;
  right: 3%;
}

.custom-close-btn {
  position: absolute;
  top: 25%;
  right: 0;
  transform: translateY(-50%);
  width: 35px;
  height: 35px;
  border-radius: 50%;
  border: 2px solid #cfcfcf;
  background: none;
  font-size: 30px;
  font-weight: lighter;
  color: #cfcfcf;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1;
  padding: 0;
  outline: none;
}

.custom-close-btn:hover {
  color: #409eff;
  border-color: #409eff;
}

.edit-function-btn {
  background: rgba(37, 99, 235, 0.08);
  color: #2563eb;
  border: 1px solid rgba(37, 99, 235, 0.18);
  border-radius: 18px;
  padding: 10px 20px;
  transition: all 0.3s;
}

.edit-function-btn.active-btn {
  background: linear-gradient(135deg, #3b82f6 0%, #6366f1 100%);
  color: #ffffff;
}

.chat-history-options {
  display: flex;
  gap: 10px;
  min-width: 250px;
  justify-content: flex-end;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
}

.header-actions .hint-text {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #979db1;
  font-size: 12px;
  margin-right: 8px;
}

.header-actions .hint-text img {
  width: 16px;
  height: 16px;
}

.header-actions .save-btn {
  background: linear-gradient(135deg, #3b82f6 0%, #6366f1 100%);
  color: #ffffff;
  border: none;
  border-radius: 18px;
  padding: 8px 16px;
  height: 32px;
  font-size: 14px;
}

.header-actions .custom-close-btn {
  position: static;
  transform: none;
  width: 32px;
  height: 32px;
}
</style>
