<template>
  <el-drawer :visible.sync="dialogVisible" direction="rtl" size="80%" :wrapperClosable="false"
    :title="$t('functionDialog.title')" :before-close="handleBeforeClose" custom-class="xn-fn-drawer">
    <div class="fd">
      <div class="fd__main">
        <!-- 左：未选功能（勾选即加入） -->
        <section class="fd-col">
          <header class="fd-col__head">
            <h4 class="fd-col__title">{{ $t('functionDialog.unselectedFunctions') }} <span class="xn-num xn-muted">{{ unselected.length }}</span></h4>
            <el-button type="text" :disabled="!unselected.length" @click="selectAll">{{ $t('functionDialog.selectAll') }}</el-button>
          </header>
          <div class="fd-col__list">
            <template v-if="unselected.length">
              <el-popover v-for="func in unselected" :key="func.name" placement="right" width="320" trigger="hover"
                :open-delay="300" popper-class="xn-fn-preview">
                <div class="fnp">
                  <div class="fnp__title">{{ func.name }}</div>
                  <template v-if="func.fieldsMeta && func.fieldsMeta.length > 0">
                    <div class="fnp__label">{{ $t('functionDialog.paramPreview') }}</div>
                    <div v-for="f in func.fieldsMeta" :key="f.key" class="fnp__item">
                      <span class="fnp__name">{{ cleanLabel(f.label) || f.key }}</span>
                      <span v-if="f.configField || (f.label && f.label.includes('config_field'))" class="xn-tag xn-tag--warning">{{ $t('functionDialog.needConfig') }}</span>
                      <span v-else-if="f.required" class="xn-tag xn-tag--warning">{{ $t('functionDialog.required') }}</span>
                      <span v-else class="xn-tag xn-tag--muted">{{ $t('functionDialog.autoExtract') }}</span>
                    </div>
                  </template>
                  <div v-else class="fnp__none">{{ $t('xn.agents.fn.noParams') }}</div>
                </div>
                <div slot="reference" class="fd-item">
                  <el-checkbox :label="func.name" v-model="selectedNames" @change="(val) => handleCheckboxChange(func, val)">{{ func.name }}</el-checkbox>
                </div>
              </el-popover>
            </template>
            <p v-else class="fd-col__empty">{{ $t('functionDialog.noMorePlugins') }}</p>
          </div>
        </section>

        <!-- 中：已选功能（点名称配置参数） -->
        <section class="fd-col">
          <header class="fd-col__head">
            <h4 class="fd-col__title">{{ $t('functionDialog.selectedFunctions') }} <span class="xn-num xn-muted">{{ selectedList.length }}</span></h4>
            <el-button type="text" :disabled="!selectedList.length" @click="deselectAll">{{ $t('xn.agents.fn.clearAll') }}</el-button>
          </header>
          <div class="fd-col__list">
            <template v-if="selectedList.length > 0">
              <div v-for="func in selectedList" :key="func.name" class="fd-item"
                :class="{ 'is-on': currentFunction && currentFunction.name === func.name }">
                <el-checkbox :label="func.name" v-model="selectedNames" class="fd-item__check" :aria-label="func.name"
                  @change="(val) => handleCheckboxChange(func, val)"><span class="fd-sr">{{ func.name }}</span></el-checkbox>
                <button type="button" class="fd-item__name" @click="handleFunctionClick(func)">
                  <span class="xn-clip">{{ func.name }}</span>
                  <xn-icon v-if="func.fieldsMeta && func.fieldsMeta.length" name="tune" class="fd-item__icon" />
                </button>
              </div>
            </template>
            <p v-else class="fd-col__empty">{{ $t('functionDialog.pleaseSelectPlugin') }}</p>
          </div>
        </section>

        <!-- 右：参数配置 -->
        <section class="fd-col fd-col--params">
          <header class="fd-col__head">
            <h4 class="fd-col__title">{{ $t('functionDialog.paramConfig') }}<template v-if="currentFunction">：{{ currentFunction.name }}</template></h4>
          </header>
          <div v-if="currentFunction" class="fd-params">
            <p v-if="currentFunction.fieldsMeta.length == 0" class="fd-col__empty">{{ $t('xn.agents.fn.noParamsNamed', { name: currentFunction.name }) }}</p>
            <el-form v-else :model="currentFunction" label-position="top">
              <el-form-item v-for="field in currentFunction.fieldsMeta" :key="field.key" class="fd-param">
                <template #label>
                  <span class="fd-param__label">{{ cleanLabel(field.label) || field.key }}</span>
                  <span v-if="isParamOptional(field)" class="fd-param__hint">{{ $t('functionDialog.autoExtractHint') }}</span>
                  <el-tooltip v-else effect="dark" :content="fieldRemark(field)" placement="top">
                    <xn-icon name="info" class="fd-param__info" />
                  </el-tooltip>
                </template>
                <!-- ARRAY -->
                <el-input v-if="field.type === 'array'" type="textarea" :rows="3" v-model="currentFunction.params[field.key]"
                  @change="val => handleParamChange(currentFunction, field.key, val)" />
                <!-- JSON -->
                <el-input v-else-if="field.type === 'json'" type="textarea" :rows="6" :placeholder="$t('xn.agents.fn.jsonPlaceholder')"
                  v-model="textCache[field.key]" class="fd-mono" @blur="flushJson(field)" />
                <!-- number -->
                <el-input-number v-else-if="field.type === 'number'" :value="currentFunction.params[field.key]"
                  @change="val => handleParamChange(currentFunction, field.key, val)" />
                <!-- boolean -->
                <el-switch v-else-if="field.type === 'boolean' || field.type === 'bool'"
                  :value="currentFunction.params[field.key]"
                  @change="val => handleParamChange(currentFunction, field.key, val)" />
                <!-- string or fallback -->
                <el-input v-else v-model="currentFunction.params[field.key]"
                  @change="val => handleParamChange(currentFunction, field.key, val)" />
              </el-form-item>
            </el-form>
          </div>
          <p v-else class="fd-col__empty">{{ $t('functionDialog.pleaseSelectFunctionForParam') }}</p>
        </section>
      </div>

      <!-- 接入点：只展示状态与设备上报的工具 -->
      <section class="fd-mcp">
        <div class="fd-mcp__head">
          <h4 class="fd-col__title">{{ $t('functionDialog.accessPointStatus') }}</h4>
          <span v-if="mcpStatus === 'connected'" class="xn-tag xn-tag--success"><i class="dot"></i>{{ $t('functionDialog.connected') }}</span>
          <span v-else-if="mcpStatus === 'loading'" class="xn-tag xn-tag--muted">{{ $t('functionDialog.loading') }}</span>
          <span v-else class="xn-tag xn-tag--muted"><i class="dot"></i>{{ $t('functionDialog.disconnected') }}</span>
          <el-button size="small" :disabled="mcpStatus === 'loading'" @click="refreshStatus"><xn-icon name="refresh" /> {{ $t('functionDialog.refresh') }}</el-button>
        </div>
        <div v-if="mcpTools.length > 0" class="fd-mcp__tools">
          <span v-for="tool in mcpTools" :key="tool" class="xn-tag xn-tag--lake fd-mono">{{ tool }}</span>
        </div>
        <p v-else class="fd-mcp__none">{{ $t('xn.agents.fn.noTools') }}</p>
      </section>

      <footer class="fd__foot">
        <el-button @click="closeDialog">{{ $t('functionDialog.cancel') }}</el-button>
        <el-button type="primary" @click="saveSelection">{{ $t('xn.agents.fn.apply') }}</el-button>
      </footer>
    </div>
  </el-drawer>
</template>

<script>
import Api from '@/apis/api';
import i18n from '@/i18n';

export default {
  i18n,

  props: {
    value: Boolean,
    functions: {
      type: Array,
      default: () => []
    },
    allFunctions: {
      type: Array,
      default: () => []
    },
    agentId: {
      type: String,
      required: true
    }
  },
  data() {
    return {
      textCache: {},
      dialogVisible: this.value,
      selectedNames: [],
      currentFunction: null,
      modifiedFunctions: {},
      tempFunctions: {},
      // 添加一个标志位来跟踪是否已经保存
      hasSaved: false,
      loading: false,

      mcpStatus: "disconnected",
      mcpTools: [],
    }
  },
  computed: {
    selectedList() {
      return this.allFunctions.filter(f => this.selectedNames.includes(f.name));
    },
    unselected() {
      return this.allFunctions.filter(f => !this.selectedNames.includes(f.name));
    }
  },
  watch: {
    currentFunction(newFn) {
      if (!newFn) return;
      // 对每个字段，如果是 array 或 json，就在 textCache 里生成初始字符串
      newFn.fieldsMeta.forEach(f => {
        const v = newFn.params[f.key];
        if (f.type === 'array') {
          this.$set(this.textCache, f.key, Array.isArray(v) ? v.join('\n') : '');
        }
        else if (f.type === 'json') {
          try {
            this.$set(this.textCache, f.key, JSON.stringify(v ?? {}, null, 2));
          } catch {
            this.$set(this.textCache, f.key, '');
          }
        }
      });
    },
    value(v) {
      this.dialogVisible = v;
      if (v) {
        // 对话框打开时，初始化选中态
        this.selectedNames = this.functions.map(f => f.name);
        // 把后端传来的 this.functions（带 params）merge 到 allFunctions 上
        this.functions.forEach(saved => {
          const idx = this.allFunctions.findIndex(f => f.name === saved.name);
          if (idx >= 0) {
            // 保留用户之前在 saved.params 上的改动
            this.allFunctions[idx].params = { ...saved.params };
          }
        });
        // 右侧默认指向第一个
        this.currentFunction = this.selectedList[0] || null;

        // 加载 MCP 工具列表（服务端默认接入统一网关）
        this.loadMcpTools();
      }
    },
    dialogVisible(newVal) {
      this.$emit('input', newVal);
    }
  },
  methods: {
    // 抽屉右上角关闭 / Esc：与“取消”一致，丢弃未保存的选择
    handleBeforeClose() {
      this.closeDialog();
    },

    refreshStatus() {
      this.mcpStatus = "loading";
      this.loadMcpTools();
    },

    // 加载 MCP 工具列表（从服务端统一网关获取）
    loadMcpTools() {
      Api.agent.getAgentMcpToolsList(this.agentId, (res) => {
        if (res.data.code === 0) {
          this.mcpTools = res.data.data || [];
          // 根据工具列表更新状态
          this.mcpStatus = this.mcpTools.length > 0 ? "connected" : "disconnected";
        } else {
          this.mcpTools = [];
          this.mcpStatus = "disconnected";
          console.error('获取MCP工具列表失败:', res.data.msg);
        }
      });
    },

    flushArray(key) {
      const text = this.textCache[key] || '';
      const arr = text
        .split('\n')
        .map(s => s.trim())
        .filter(Boolean);
      this.handleParamChange(this.currentFunction, key, arr);
    },

    flushJson(field) {
      const key = field.key;
      if (!key) {
        return;
      }
      const text = this.textCache[key] || '';
      try {
        const obj = JSON.parse(text);
        this.handleParamChange(this.currentFunction, key, obj);
      } catch {
        this.$message.error(this.$t('xn.agents.fn.jsonError', { name: this.currentFunction.name, field: this.cleanLabel(field.label) || key }));
      }
    },
    handleFunctionClick(func) {
      if (this.selectedNames.includes(func.name)) {
        const tempFunc = this.tempFunctions[func.name];
        this.currentFunction = tempFunc ? tempFunc : func;
      }
    },
    handleParamChange(func, key, value) {
      if (!this.tempFunctions[func.name]) {
        this.tempFunctions[func.name] = JSON.parse(JSON.stringify(func));
      }
      this.tempFunctions[func.name].params[key] = value;
    },
    handleCheckboxChange(func, checked) {
      if (checked) {
        if (!this.selectedNames.includes(func.name)) {
          this.selectedNames = [...this.selectedNames, func.name];
        }
      } else {
        this.selectedNames = this.selectedNames.filter(name => name !== func.name);
      }

      if (this.selectedList.length > 0) {
        this.currentFunction = this.selectedList[0];
      } else {
        this.currentFunction = null;
      }
    },

    selectAll() {
      this.selectedNames = [...this.allFunctions.map(f => f.name)];
      if (this.selectedList.length > 0) {
        this.currentFunction = JSON.parse(JSON.stringify(this.selectedList[0]));
      }
    },

    deselectAll() {
      this.selectedNames = [];
      this.currentFunction = null;
    },

    closeDialog() {
      this.tempFunctions = {};
      this.selectedNames = this.functions.map(f => f.name);
      this.currentFunction = null;
      this.dialogVisible = false;
      this.$emit('input', false);
      this.$emit('dialog-closed', false);
    },

    saveSelection() {
      Object.keys(this.tempFunctions).forEach(name => {
        this.modifiedFunctions[name] = JSON.parse(JSON.stringify(this.tempFunctions[name]));
      });
      this.tempFunctions = {};
      this.hasSaved = true;

      const selected = this.selectedList.map(f => {
        const modified = this.modifiedFunctions[f.name];
        return {
          id: f.id,
          name: f.name,
          params: modified
            ? { ...modified.params }
            : { ...f.params }
        }
      });

      this.$emit('update-functions', selected);
      this.dialogVisible = false;
      // 通知父组件对话框已关闭且已保存
      this.$emit('dialog-closed', true);
    },
    fieldRemark(field) {
      let description = (field && field.label) ? this.cleanLabel(field.label) : '';
      if (field.default) {
        description += `（${this.$t('functionDialog.defaultValue')}：${field.default}）`;
      }
      return description;
    },
    /** 去除 label 中的 config_field 等内部标记，用于展示 */
    cleanLabel(label) {
      if (!label || typeof label !== 'string') return label || '';
      return label.replace(/\s*config_field:\s*true\s*/gi, '').trim();
    },
    /** 是否为可选/自动提取参数（非必填且非配置项） */
    isParamOptional(field) {
      if (!field) return true;
      if (field.required || field.configField) return false;
      if (field.label && typeof field.label === 'string' && field.label.includes('config_field')) return false;
      return true;
    },
  }
}
</script>

<style scoped>
.fd { display: flex; flex-direction: column; height: 100%; min-height: 0; }
.fd__main {
  flex: 1 1 auto; min-height: 0; display: grid; grid-template-columns: minmax(180px, 220px) minmax(180px, 220px) minmax(0, 1fr);
  border: 1px solid var(--xn-line); border-radius: var(--xn-r-lg); overflow: hidden;
}
.fd-col { display: flex; flex-direction: column; min-width: 0; min-height: 0; border-right: 1px solid var(--xn-line-2); }
.fd-col--params { border-right: 0; }
.fd-col__head { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 48px; padding: 0 14px; border-bottom: 1px solid var(--xn-line-2); background: var(--xn-mist-2); }
.fd-col__title { margin: 0; font-size: 14px; font-weight: 600; color: var(--xn-ink); }
.fd-col__title .xn-num { margin-left: 4px; font-weight: 400; }
.fd-col__list { flex: 1; overflow-y: auto; padding: 6px; }
.fd-col__empty { margin: 0; padding: 24px 14px; font-size: 13px; color: var(--xn-ink-3); text-align: center; }
.fd-item { display: flex; align-items: center; gap: 4px; min-height: 38px; padding: 0 8px; border-radius: var(--xn-r); }
.fd-item:hover { background: var(--xn-mist-2); }
.fd-item.is-on { background: var(--xn-lake-soft); }
.fd-item ::v-deep .el-checkbox { display: flex; align-items: center; width: 100%; min-width: 0; }
.fd-item ::v-deep .el-checkbox__label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--xn-ink); font-size: 14px; }
.fd-item__check { width: auto !important; flex: none; }
.fd-item__check ::v-deep .el-checkbox__label { display: none; }
.fd-item__name {
  display: flex; align-items: center; justify-content: space-between; gap: 6px; flex: 1; min-width: 0; height: 34px; padding: 0 4px;
  border: 0; background: none; font: inherit; font-size: 14px; color: var(--xn-ink); text-align: left; cursor: pointer;
}
.fd-item__icon { color: var(--xn-ink-4); }
.fd-item.is-on .fd-item__icon, .fd-item__name:hover .fd-item__icon { color: var(--xn-lake); }
.fd-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
.fd-params { flex: 1; overflow-y: auto; padding: 14px 16px; }
.fd-param ::v-deep .el-form-item__label { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; line-height: 1.5; padding-bottom: 6px; float: none; }
.fd-param__label { font-size: 14px; color: var(--xn-ink-2); font-weight: 500; }
.fd-param__hint { font-size: 12px; font-weight: 400; color: var(--xn-ink-3); }
.fd-param__info { color: var(--xn-ink-3); cursor: help; }
.fd-mono, .fd-mono ::v-deep textarea { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; }
.fd-mcp { flex: none; margin-top: 16px; padding: 14px 16px; border: 1px solid var(--xn-line); border-radius: var(--xn-r-lg); }
.fd-mcp__head { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.fd-mcp__head .el-button { margin-left: auto; }
.fd-mcp__tools { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 12px; }
.fd-mcp__none { margin: 8px 0 0; font-size: 13px; color: var(--xn-ink-3); }
.fd__foot { flex: none; display: flex; justify-content: flex-end; gap: 8px; padding-top: 16px; }
.dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
@media (max-width: 900px) {
  .fd__main { grid-template-columns: 1fr 1fr; grid-auto-rows: minmax(160px, auto); overflow-y: auto; }
  .fd-col--params { grid-column: 1 / -1; border-top: 1px solid var(--xn-line-2); }
}
</style>

<style>
/* 抽屉宽度上限；悬停预览气泡挂在 body 上，所以不能 scoped */
.xn-fn-drawer { max-width: 1080px; min-width: min(720px, 100vw); }
.xn-fn-drawer .el-drawer__body { display: flex; flex-direction: column; min-height: 0; overflow: hidden; padding: 16px 24px 20px; }
.xn-fn-preview .fnp { font-size: 13px; line-height: 1.5; color: var(--xn-ink-2); }
.xn-fn-preview .fnp__title { margin-bottom: 8px; font-size: 14px; font-weight: 600; color: var(--xn-ink); }
.xn-fn-preview .fnp__label { margin-bottom: 6px; font-size: 12px; color: var(--xn-ink-3); }
.xn-fn-preview .fnp__item { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 6px 0; border-top: 1px solid var(--xn-line-2); }
.xn-fn-preview .fnp__name { min-width: 0; word-break: break-word; }
.xn-fn-preview .fnp__none { color: var(--xn-ink-3); }
</style>
