<template>
  <el-drawer :visible.sync="dialogVisible" direction="rtl" size="80%" :wrapperClosable="false" :withHeader="false">
    <!-- 自定义标题区域 -->
    <div class="custom-header">
      <div class="header-left">
        <h3 class="bold-title">{{ $t('functionDialog.title') }}</h3>
      </div>
      <button class="custom-close-btn" @click="closeDialog">×</button>
    </div>

    <div class="function-manager">
      <!-- 左侧：未选功能 -->
      <div class="function-column">
        <div class="column-header">
          <h4 class="column-title">{{ $t('functionDialog.unselectedFunctions') }}</h4>
          <el-button type="text" @click="selectAll" class="select-all-btn">
            {{ $t('functionDialog.selectAll') }}
          </el-button>
        </div>
        <div class="function-list">
          <template v-if="unselected.length">
            <el-popover v-for="func in unselected" :key="func.name" placement="right" width="320" trigger="hover"
              popper-class="function-hover-preview">
              <div class="hover-preview-content">
                <div class="hover-preview-title">{{ func.name }}</div>
                <div v-if="func.fieldsMeta && func.fieldsMeta.length > 0" class="hover-preview-params">
                  <div class="hover-preview-params-label">{{ $t('functionDialog.paramPreview') }}</div>
                  <div v-for="f in func.fieldsMeta" :key="f.key" class="hover-preview-param-item">
                    <span class="param-name">{{ f.key }}</span>
                    <span v-if="f.configField || (f.label && f.label.includes('config_field'))" class="param-badge config">API Key / {{ $t('functionDialog.needConfig') }}</span>
                    <span v-else-if="f.required" class="param-badge required">{{ $t('functionDialog.required') }}</span>
                    <span v-else class="param-badge optional">{{ $t('functionDialog.autoExtract') }}</span>
                    <div class="param-desc">{{ cleanLabel(f.label) }}</div>
                  </div>
                </div>
                <div v-else class="hover-preview-no-params">{{ $t('functionDialog.noNeedToConfig') }}</div>
              </div>
              <div slot="reference" class="function-item">
                <el-checkbox :label="func.name" v-model="selectedNames" @change="(val) => handleCheckboxChange(func, val)"
                  @click.native.stop></el-checkbox>
                <div class="func-tag" @click="handleFunctionClick(func)">
                  <div class="color-dot"></div>
                  <span>{{ func.name }}</span>
                </div>
              </div>
            </el-popover>
          </template>
          <div v-else style="display: flex; justify-content: center; align-items: center;">
            <el-empty :description="$t('functionDialog.noMorePlugins')" />
          </div>
        </div>
      </div>

      <!-- 中间：已选功能 -->
      <div class="function-column">
        <div class="column-header">
          <h4 class="column-title">{{ $t('functionDialog.selectedFunctions') }}</h4>
          <el-button type="text" @click="deselectAll" class="select-all-btn">
            {{ $t('functionDialog.selectAll') }}
          </el-button>
        </div>
        <div class="function-list">
          <div v-if="selectedList.length > 0">
            <div v-for="func in selectedList" :key="func.name" class="function-item">
              <el-checkbox :label="func.name" v-model="selectedNames" @change="(val) => handleCheckboxChange(func, val)"
                @click.native.stop></el-checkbox>
              <div class="func-tag" @click="handleFunctionClick(func)">
                <div class="color-dot"></div>
                <span>{{ func.name }}</span>
              </div>
            </div>
          </div>
          <div v-else style="display: flex; justify-content: center; align-items: center;">
            <el-empty :description="$t('functionDialog.pleaseSelectPlugin')" />
          </div>
        </div>
      </div>

      <!-- 右侧：参数配置 -->
      <div class="params-column">
        <h4 v-if="currentFunction" class="column-title">
          {{ $t('functionDialog.paramConfig') }} - {{ currentFunction.name }}
        </h4>
        <div v-if="currentFunction" class="params-container">
          <el-form :model="currentFunction" class="param-form">
            <!-- 遍历 fieldsMeta，而不是 params 的 keys -->
            <div v-if="currentFunction.fieldsMeta.length == 0">
              <el-empty :description="currentFunction.name + $t('functionDialog.noNeedToConfig')" />
            </div>
            <el-form-item v-for="field in currentFunction.fieldsMeta" :key="field.key"
              :label="cleanLabel(field.label)"
              class="param-item"
              :class="{ 'textarea-field': field.type === 'array' || field.type === 'json', 'param-optional': isParamOptional(field) }">
              <template #label>
                <span style="font-size: 16px; margin-right: 6px;">{{ cleanLabel(field.label) }}</span>
                <span v-if="isParamOptional(field)" class="optional-hint">{{ $t('functionDialog.autoExtractHint') }}</span>
                <el-tooltip v-else effect="dark" :content="fieldRemark(field)" placement="top">
                  <img src="@/assets/home/info.png" alt="" class="info-icon">
                </el-tooltip>
              </template>
              <!-- ARRAY -->
              <el-input v-if="field.type === 'array'" type="textarea" v-model="currentFunction.params[field.key]"
                @change="val => handleParamChange(currentFunction, field.key, val)" />

              <!-- JSON -->
              <el-input v-else-if="field.type === 'json'" type="textarea" :rows="6" placeholder="请输入合法的 JSON"
                v-model="textCache[field.key]" @blur="flushJson(field)" />

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
        <div v-else class="empty-tip">{{ $t('functionDialog.pleaseSelectFunctionForParam') }}</div>
      </div>
    </div>

    <!-- MCP区域：仅展示接入点状态与刷新 -->
    <div class="mcp-access-point">
      <div class="mcp-container">
        <div class="mcp-right">
          <div class="mcp-header">
            <h3 class="bold-title">{{ $t('functionDialog.accessPointStatus') }}</h3>
          </div>
          <div class="status-container">
            <span class="status-indicator" :class="mcpStatus"></span>
            <span class="status-text">{{
              mcpStatus === 'connected' ? $t('functionDialog.connected') :
                mcpStatus === 'loading' ? $t('functionDialog.loading') : $t('functionDialog.disconnected')
            }}</span>
            <button class="refresh-btn" @click="refreshStatus">
              <span class="refresh-icon">↻</span>
              <span>{{ $t('functionDialog.refresh') }}</span>
            </button>
          </div>
          <div class="mcp-tools-list">
            <div v-if="mcpTools.length > 0" class="tools-grid">
              <el-button v-for="tool in mcpTools" :key="tool" size="small" class="tool-btn" plain>
                {{ tool }}
              </el-button>
            </div>
            <div v-else class="no-tools">
              <span>{{ $t('functionDialog.noAvailableTools') }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="drawer-footer">
      <el-button @click="closeDialog">{{ $t('functionDialog.cancel') }}</el-button>
      <el-button type="primary" @click="saveSelection">{{ $t('functionDialog.saveConfig') }}</el-button>
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
        this.$message.error(`${this.currentFunction.name}${this.$t('functionDialog.jsonFormatError')}`);
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

<style lang="scss" scoped>
.function-manager {
  display: grid;
  grid-template-columns: max-content max-content 1fr;
  gap: 12px;
  height: calc(58vh);
}

.custom-header {
  position: relative;
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 24px;
  border-bottom: 1px solid rgba(148, 163, 184, 0.25);

  .header-left {
    display: flex;
    align-items: center;
    gap: 16px;
  }

  .bold-title {
    font-size: 18px;
    font-weight: bold;
    margin: 0;
    color: #0f172a;
  }

  .select-all-btn {
    padding: 0;
    height: auto;
    font-size: 14px;
  }
}

.function-column {
  position: relative;
  width: auto;
  padding: 10px;
  overflow-y: auto;
  border-right: 1px solid rgba(148, 163, 184, 0.25);
  scrollbar-width: none;
  overflow-x: hidden;
}

.function-column::-webkit-scrollbar {
  display: none;
}

.function-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.function-item {
  padding: 8px 12px;
  margin: 4px 0;
  width: 100%;
  text-align: left;
  cursor: pointer;
  border-radius: 8px;
  transition: background-color 0.2s, box-shadow 0.2s;
  display: flex;
  align-items: center;
  justify-content: space-between;

  &:hover {
    background-color: rgba(148, 163, 184, 0.12);
    box-shadow: 0 4px 12px rgba(148, 163, 184, 0.18);
  }
}

.params-column {
  min-width: 280px;
  padding: 10px;
  overflow-y: auto;
  scrollbar-width: none;
}

.params-column::-webkit-scrollbar {
  display: none;
}

.column-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.column-title {
  text-align: center;
  width: 100%;
}

.func-tag {
  display: flex;
  align-items: center;
  cursor: pointer;
  flex-grow: 1;
  margin-left: 8px;
}

.color-dot {
  flex-shrink: 0;
  width: 8px;
  height: 8px;
  background: linear-gradient(135deg, #3b82f6 0%, #6366f1 100%);
  margin-right: 8px;
  border-radius: 50%;
}

.param-form {
  .param-item {
    font-size: 16px;

    &.textarea-field {
      ::v-deep .el-form-item__content {
        margin-left: 0 !important;
        display: block;
        width: 100%;
      }

      ::v-deep .el-form-item__label {
        display: block;
        width: 100% !important;
        margin-bottom: 8px;
      }
    }
  }

  .param-input {
    width: 100%;
  }

  ::v-deep .el-form-item {
    display: flex;
    flex-direction: column;
    margin-bottom: 12px;

    .el-form-item__label {
      font-size: 13px !important;
      color: #475569;
      text-align: left;
      padding-right: 10px;
      flex-shrink: 0;
      width: auto !important;
    }

    .el-form-item__content {
      margin-left: 0 !important;
      flex-grow: 1;

      .el-input__inner {
        text-align: left;
        padding-left: 10px;
        width: 100%;
        border-radius: 8px;
        border: 1px solid rgba(148, 163, 184, 0.5);
        background: rgba(248, 250, 252, 0.9);
      }
    }
  }
}

.params-container {
  padding: 16px;
  border-radius: 16px;
  min-width: 280px;
  background: rgba(255, 255, 255, 0.65);
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.1);
}

.empty-tip {
  padding: 20px;
  color: #909399;
  text-align: center;
}


.drawer-footer {
  position: absolute;
  bottom: 0;
  width: 100%;
  border-top: 1px solid rgba(148, 163, 184, 0.25);
  padding: 10px 16px;
  text-align: center;
  background: rgba(248, 250, 252, 0.9);
}

.info-icon {
  width: 16px;
  height: 16px;
  margin-right: 1vh;
}

.custom-close-btn {
  position: absolute;
  top: 50%;
  right: 10px;
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
  transition: all 0.3s;
}

.custom-close-btn:hover {
  color: #2563eb;
  border-color: #2563eb;
}

::v-deep .el-checkbox__label {
  display: none;
}
</style>

<style lang="scss">
/* 悬停预览气泡样式（非 scoped，Popover 挂载到 body） */
.function-hover-preview {
  .hover-preview-content {
    font-size: 13px;
    line-height: 1.5;
  }
  .hover-preview-title {
    font-weight: 600;
    margin-bottom: 10px;
    color: #303133;
    font-size: 14px;
  }
  .hover-preview-params-label {
    font-size: 12px;
    color: #909399;
    margin-bottom: 8px;
  }
  .hover-preview-param-item {
    margin-bottom: 10px;
    padding-bottom: 8px;
    border-bottom: 1px solid #ebeef5;
  }
  .hover-preview-param-item:last-child {
    border-bottom: none;
    margin-bottom: 0;
    padding-bottom: 0;
  }
  .param-name {
    font-weight: 500;
    color: #606266;
    margin-right: 6px;
  }
  .param-badge {
    display: inline-block;
    font-size: 11px;
    padding: 1px 6px;
    border-radius: 3px;
    margin-right: 4px;
  }
  .param-badge.config {
    background: #fef0f0;
    color: #f56c6c;
  }
  .param-badge.required {
    background: #fdf6ec;
    color: #e6a23c;
  }
  .param-badge.optional {
    background: #f0f9eb;
    color: #67c23a;
  }
  .param-desc {
    font-size: 12px;
    color: #909399;
    margin-top: 4px;
    padding-left: 0;
    word-break: break-word;
  }
  .hover-preview-no-params {
    color: #909399;
    font-size: 13px;
  }
}
</style>

<style lang="scss" scoped>
.optional-hint {
  font-size: 12px;
  color: #67c23a;
  margin-left: 4px;
}

.param-optional ::v-deep .el-form-item__label {
  color: #909399;
}

.mcp-access-point {
  border-top: 1px solid #EBEEF5;
  padding: 20px 24px;
  text-align: left;
}

.mcp-header {
  .bold-title {
    font-size: 18px;
    font-weight: bold;
    margin: 5px 0 30px 0;
  }
}

.mcp-container {
  display: flex;
  justify-content: space-between;
  gap: 30px;
}

.mcp-left,
.mcp-right {
  flex: 1;
  padding-bottom: 50px;
}

.url-header {
  margin-bottom: 8px;
  color: black;

  h4 {
    margin: 0 0 15px 0;
    font-size: 16px;
    font-weight: normal;
  }

  .address-desc {
    display: flex;
    align-items: center;
    font-size: 14px;
    margin-bottom: 12px;

    .doc-link {
      color: #1677ff;
      text-decoration: none;
      margin-left: 4px;

      &:hover {
        text-decoration: underline;
      }
    }
  }
}

.url-input {
  border-radius: 4px 0 0 4px;
  font-size: 14px;
  height: 36px;
  box-sizing: border-box;

  ::v-deep .el-input__inner {
    background-color: #f5f5f5 !important;
  }

  ::v-deep .el-input__suffix {
    right: 0;
    display: flex;
    align-items: center;
    padding-right: 10px;

    .inner-copy-btn {
      pointer-events: auto;
      border: none;
      background: #1677ff;
      color: white;
      padding: 6px;
      margin-top: 4px;
      margin-left: 4px;
    }
  }
}

.mcp-right {
  h4 {
    margin: 0 0 10px 0;
    font-size: 16px;
    font-weight: normal;
    color: black;
  }
}

.status-container {
  display: flex;
  align-items: center;

  .status-indicator {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    margin-right: 8px;

    &.disconnected {
      background-color: #909399;
      /* 灰色 - 未连接 */
    }

    &.connected {
      background-color: #67C23A;
      /* 绿色 - 已连接 */
    }

    &.loading {
      background-color: #E6A23C;
      /* 橙色 - 加载中 */
      animation: pulse 1.5s infinite;
    }
  }

  .status-text {
    font-size: 14px;
    margin-right: 10px;
  }

  .refresh-btn {
    display: flex;
    align-items: center;
    padding: 2px 10px;
    background: white;
    color: black;
    border: 1px solid #DCDFE6;
    border-radius: 4px;
    cursor: pointer;
    font-size: 14px;
    transition: all 0.3s;

    &:hover {
      background: #1677ff;
      color: white;
      border-color: #1677ff;
    }

    .refresh-icon {
      margin-right: 6px;
      font-size: 14px;
    }
  }
}

@keyframes pulse {
  0% {
    opacity: 1;
  }

  50% {
    opacity: 0.4;
  }

  100% {
    opacity: 1;
  }
}

.mcp-tools-list {
  margin-top: 10px;

  .tools-grid {
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  .tool-btn {
    padding: 6px 12px;
    border-color: #1677ff;
    color: #1677ff;
    background-color: white;
    font-size: 12px;

    &:hover {
      background-color: #1677ff;
      color: white;
      border-color: #1677ff;
    }
  }

  .no-tools {
    text-align: center;
    color: #909399;
    font-size: 14px;
    padding: 10px 0;
  }
}
</style>