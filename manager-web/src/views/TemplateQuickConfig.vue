<template>
  <div class="xn-page">
    <page-header :title="templateId ? $t('xn.agents.tpl.editTitle') : $t('xn.agents.tpl.createTitle')"
      back="/agent-template-management" :back-label="$t('agentTemplateManagement.title')" :description="$t('xn.agents.tpl.formDesc')" />

    <div v-if="loadFailed" class="xn-panel">
      <xn-empty error :description="loadFailedMsg || $t('xn.common.loadFailedDesc')">
        <el-button @click="goToHome">{{ $t('xn.agents.tpl.backToList') }}</el-button>
        <el-button type="primary" @click="fetchTemplateById($route.query.templateId)"><xn-icon name="refresh" /> {{ $t('xn.common.retry') }}</el-button>
      </xn-empty>
    </div>

    <section v-else class="xn-panel tq" v-loading="loading">
      <el-form ref="form" :model="form" :rules="rules" label-position="top" class="xn-panel__body tq-form" @submit.native.prevent>
        <el-form-item :label="$t('agentTemplateManagement.templateName')" prop="agentName" class="tq-name">
          <el-input v-model="form.agentName" :placeholder="$t('templateQuickConfig.agentSettings.agentNamePlaceholder')"
            maxlength="64" show-word-limit />
        </el-form-item>
        <el-form-item :label="$t('templateQuickConfig.agentSettings.systemPrompt')" prop="systemPrompt">
          <el-input v-model="form.systemPrompt" type="textarea" :rows="12" resize="vertical"
            :placeholder="$t('templateQuickConfig.agentSettings.systemPromptPlaceholder')" show-word-limit maxlength="2000" />
          <p class="tq-hint">{{ $t('xn.agents.tpl.modelHint') }}</p>
        </el-form-item>
      </el-form>
      <footer class="tq-foot">
        <el-button @click="goToHome">{{ $t('common.cancel') }}</el-button>
        <el-button @click="resetConfig">{{ $t('templateQuickConfig.resetConfig') }}</el-button>
        <el-button type="primary" :loading="saving" @click="saveConfig"><xn-icon name="check" /> {{ $t('templateQuickConfig.saveConfig') }}</el-button>
      </footer>
    </section>
  </div>
</template>

<script>
import agentApi from '@/apis/module/agent';

// 默认模型配置常量
const DEFAULT_MODEL_CONFIG = {
  ttsModelId: "TTS_QwenAudioTTSPlus",
  ttsVoiceId: "TTS_QwenAudioTTSPlus_0001",
  vadModelId: "VAD_SileroVAD",
  asrModelId: "ASR_Qwen3ASRRealtime",
  llmModelId: "LLM_QwenPlusOfficial",
  vllmModelId: "VLLM_QwenVLVLLM",
  memModelId: "Memory_mem_local_short",
  intentModelId: "Intent_function_call"
};
const SAVE_TIMEOUT = 15000;

export default {
  name: 'TemplateQuickConfig',
  data() {
    return {
      form: {
        agentCode: "小智",
        agentName: "",
        systemPrompt: "",
        sort: 0,
        model: { ...DEFAULT_MODEL_CONFIG }
      },
      rules: {
        agentName: [{
          validator: (rule, value, cb) => ((value || '').trim() ? cb() : cb(new Error(this.$t('xn.agents.tpl.nameRequired')))),
          trigger: 'blur',
        }],
      },
      templateId: '',
      originalForm: null,
      loading: false,
      loadFailed: false,
      loadFailedMsg: '',
      saving: false,
      saveWatch: null,
    };
  },
  beforeDestroy() {
    clearTimeout(this.saveWatch);
  },
  methods: {
    // 返回模板管理页面
    goToHome() {
      this.$router.push('/agent-template-management');
    },

    // 保存配置（先校验名称）
    saveConfig() {
      this.$refs.form.validate((valid) => {
        if (!valid) return;
        const configData = this.prepareConfigData();
        this.saving = true;
        clearTimeout(this.saveWatch);
        // 业务错误不会进入 success 回调，超时后恢复按钮
        this.saveWatch = setTimeout(() => { this.saving = false; }, SAVE_TIMEOUT);
        if (this.templateId) {
          this.updateExistingTemplate(configData);
        } else {
          this.createNewTemplate(configData);
        }
      });
    },

    // 准备配置数据
    prepareConfigData() {
      return {
        id: this.templateId || '',
        agentCode: this.form.agentCode,
        agentName: (this.form.agentName || '').trim(),
        systemPrompt: this.form.systemPrompt,
        sort: this.form.sort,
        functions: [],
        // 包含必要的模型字段以确保API调用成功
        ...this.form.model
      };
    },

    doneSaving() {
      clearTimeout(this.saveWatch);
      this.saving = false;
    },

    // 更新现有模板
    updateExistingTemplate(configData) {
      agentApi.updateAgentTemplate(configData, (res) => {
        this.doneSaving();
        if (res && res.data && res.data.code === 0) {
          this.$message.success({ message: this.$t('templateQuickConfig.saveSuccess'), showClose: true });
          this.originalForm = JSON.parse(JSON.stringify(this.form));
        } else {
          this.$message.error({ message: res?.data?.msg || this.$t('templateQuickConfig.saveFailed'), showClose: true });
        }
      });
    },

    // 创建新模板
    createNewTemplate(configData) {
      agentApi.addAgentTemplate(configData, (res) => {
        this.doneSaving();
        if (res && res.data && res.data.code === 0) {
          this.$message.success({ message: this.$t('templateQuickConfig.saveSuccess'), showClose: true });
          this.goToHome();
        } else {
          this.$message.error({ message: res?.data?.msg || this.$t('templateQuickConfig.saveFailed'), showClose: true });
        }
      });
    },

    // 重置为最近一次加载 / 保存时的内容
    resetConfig() {
      this.$confirm(
        this.$t('templateQuickConfig.confirmReset'),
        this.$t('templateQuickConfig.resetConfig'),
        {
          confirmButtonText: this.$t('templateQuickConfig.resetConfig'),
          cancelButtonText: this.$t('common.cancel'),
          type: 'warning'
        }
      ).then(() => {
        if (this.originalForm) {
          this.form = JSON.parse(JSON.stringify(this.originalForm));
        }
        this.$nextTick(() => this.$refs.form && this.$refs.form.clearValidate());
        this.$message.success({ message: this.$t('templateQuickConfig.resetSuccess'), showClose: true });
      }).catch(() => {});
    },

    // 根据ID获取模板
    fetchTemplateById(templateId) {
      this.loading = true;
      this.loadFailed = false;
      this.loadFailedMsg = '';
      const watch = setTimeout(() => { this.loading = false; this.loadFailed = true; }, 10000);
      agentApi.getAgentTemplateById(templateId, (res) => {
        clearTimeout(watch);
        this.loading = false;
        if (res && res.data && res.data.code === 0 && res.data.data) {
          const template = res.data.data;
          this.applyTemplateData(template);
          this.templateId = templateId;
          this.originalForm = JSON.parse(JSON.stringify(this.form));
        } else {
          this.loadFailed = true;
          this.loadFailedMsg = this.$t('templateQuickConfig.templateNotFound');
          this.$message.error(res?.data?.msg || this.$t('templateQuickConfig.templateNotFound'));
        }
      });
    },

    // 应用模板数据
    applyTemplateData(templateData) {
      this.form = {
        ...this.form,
        agentName: templateData.agentName || this.form.agentName,
        agentCode: templateData.agentCode || this.form.agentCode,
        systemPrompt: templateData.systemPrompt || this.form.systemPrompt,
        sort: templateData.sort || this.form.sort,
        model: {
          ttsModelId: templateData.ttsModelId || this.form.model.ttsModelId,
          ttsVoiceId: templateData.ttsVoiceId || this.form.model.ttsVoiceId,
          vadModelId: templateData.vadModelId || this.form.model.vadModelId,
          asrModelId: templateData.asrModelId || this.form.model.asrModelId,
          llmModelId: templateData.llmModelId || this.form.model.llmModelId,
          vllmModelId: templateData.vllmModelId || this.form.model.vllmModelId,
          memModelId: templateData.memModelId || this.form.model.memModelId,
          intentModelId: templateData.intentModelId || this.form.model.intentModelId
        }
      };
    },

    // 获取模板列表并设置排序号
    fetchTemplateListForSort() {
      agentApi.getAgentTemplate((res) => {
        if (res && res.data && res.data.code === 0) {
          const templateList = res.data.data || [];
          if (templateList.length > 0) {
            const maxSort = Math.max(...templateList.map(t => t.sort || 0));
            this.form.sort = maxSort + 1;
          } else {
            this.form.sort = 1;
          }
        } else {
          this.form.sort = 1;
        }
        this.originalForm = JSON.parse(JSON.stringify(this.form));
      });
    }
  },

  // 组件挂载时执行初始化
  mounted() {
    const templateId = this.$route.query.templateId;
    if (templateId) {
      // 编辑模式：加载现有模板
      this.fetchTemplateById(templateId);
    } else {
      // 新建模式：设置默认值并获取排序号
      this.form.agentName = this.$t('templateQuickConfig.newTemplate');
      this.originalForm = JSON.parse(JSON.stringify(this.form));
      this.fetchTemplateListForSort();
    }
  }
};
</script>

<style scoped>
.tq { max-width: 880px; }
.tq-form { padding-bottom: 4px; }
.tq-name { max-width: 420px; }
.tq-hint { margin: 6px 0 0; font-size: 13px; line-height: 1.5; color: var(--xn-ink-3); }
.tq-foot { display: flex; justify-content: flex-end; gap: 8px; padding: 14px 20px; border-top: 1px solid var(--xn-line-2); }
.tq-foot .el-button + .el-button { margin-left: 0; }
.tq ::v-deep .el-form-item__label { padding-bottom: 6px; line-height: 1.5; }
</style>
