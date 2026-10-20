<template>
  <div class="xn-page">
    <page-header :title="$t('header.modelConfig')" :description="$t('xn.admin.model.desc')">
      <el-button type="primary" @click="addModel"><xn-icon name="plus" /> {{ $t('xn.admin.model.add') }}</el-button>
    </page-header>

    <div class="mc-layout">
      <!-- 左侧：模型类别 -->
      <nav class="xn-panel mc-nav" :aria-label="$t('xn.admin.model.categories')">
        <p class="mc-nav__title">{{ $t('xn.admin.model.categories') }}</p>
        <button v-for="c in categories" :key="c" type="button" class="mc-nav__item" :class="{ 'is-on': activeTab === c }"
          :aria-current="activeTab === c ? 'true' : null" @click="handleMenuSelect(c)">
          <span>{{ $t('modelConfig.' + c) }}</span>
          <span class="mc-nav__code">{{ c.toUpperCase() }}</span>
        </button>
      </nav>

      <!-- 右侧：当前类别的模型 -->
      <section class="mc-main">
        <div class="xn-toolbar">
          <el-input :placeholder="$t('modelConfig.searchPlaceholder')" v-model="search" clearable
            @keyup.enter.native="handleSearch" @clear="handleSearch">
            <xn-icon slot="prefix" name="search" class="xa-search-icon" />
          </el-input>
          <el-button @click="handleSearch">{{ $t('modelConfig.search') }}</el-button>
          <span class="xn-toolbar__grow"></span>
          <template v-if="selectedModels.length">
            <span class="xn-muted">{{ $t('xn.admin.selected', { n: selectedModels.length }) }}</span>
            <el-button type="danger" plain size="small" @click="batchDelete"><xn-icon name="trash" /> {{ $t('xn.admin.deleteSelected') }}</el-button>
          </template>
        </div>

        <div class="xn-panel xn-panel--flush xa-panel">
          <header class="xn-panel__head">
            <h2 class="xn-panel__title">{{ modelTypeText }}</h2>
            <span class="xn-muted mc-count">{{ $t('xn.admin.model.count', { n: total }) }}</span>
          </header>
          <xn-empty v-if="loadFailed && !loading" error @retry="loadData" />
          <template v-else>
            <el-table ref="modelTable" :data="modelList" v-loading="loading" row-key="id" @selection-change="handleSelectionChange">
              <el-table-column type="selection" width="48" align="center" />
              <el-table-column :label="$t('modelConfig.modelName')" min-width="200">
                <template slot-scope="{ row }">
                  <div class="mc-name">{{ row.modelName }}</div>
                  <div class="mc-id">{{ row.id }}</div>
                </template>
              </el-table-column>
              <el-table-column :label="$t('modelConfig.provider')" min-width="130">
                <template slot-scope="scope">
                  <span class="xa-code">{{ (scope.row.configJson && scope.row.configJson.type) || $t("modelConfig.unknown") }}</span>
                </template>
              </el-table-column>
              <el-table-column :label="$t('xn.admin.model.enabled')" width="90">
                <template slot-scope="scope">
                  <el-switch v-model="scope.row.isEnabled" :active-value="1" :inactive-value="0"
                    :aria-label="$t('xn.admin.model.enabled')" @change="handleStatusChange(scope.row)" />
                </template>
              </el-table-column>
              <el-table-column :label="$t('xn.admin.model.default')" width="110">
                <template slot-scope="scope">
                  <span v-if="scope.row.isDefault === 1" class="xn-tag xn-tag--lake"><i class="dot"></i>{{ $t('xn.admin.model.isDefault') }}</span>
                  <el-button v-else type="text" @click="handleDefaultChange(scope.row)">{{ $t('xn.admin.model.setDefault') }}</el-button>
                </template>
              </el-table-column>
              <el-table-column :label="$t('modelConfig.action')" :width="activeTab === 'tts' ? 260 : 170" align="right">
                <template slot-scope="scope">
                  <el-button v-if="activeTab === 'tts'" type="text" @click="openTtsDialog(scope.row)">{{ $t("modelConfig.voiceManagement") }}</el-button>
                  <el-button type="text" @click="editModel(scope.row)">{{ $t("modelConfig.edit") }}</el-button>
                  <el-button type="text" @click="duplicateModel(scope.row)">{{ $t("xn.admin.model.duplicate") }}</el-button>
                  <el-button type="text" class="xa-danger" @click="deleteModel(scope.row)">{{ $t("modelConfig.delete") }}</el-button>
                </template>
              </el-table-column>
              <template slot="empty">
                <xn-empty v-if="lastSearch" icon="search" :title="$t('xn.admin.model.noMatch')" :description="$t('xn.admin.noMatchDesc')" />
                <xn-empty v-else icon="chip" :title="$t('xn.admin.model.empty', { type: modelTypeText })" :description="$t('xn.admin.model.emptyDesc')">
                  <el-button type="primary" @click="addModel"><xn-icon name="plus" /> {{ $t('xn.admin.model.add') }}</el-button>
                </xn-empty>
              </template>
            </el-table>
            <div v-if="total" class="xa-foot">
              <el-pagination background layout="total, sizes, prev, pager, next" :total="total" :page-size="pageSize"
                :page-sizes="pageSizeOptions" :current-page="currentPage" @size-change="handlePageSizeChange" @current-change="goToPage" />
            </div>
          </template>
        </div>
      </section>
    </div>

    <ModelEditDialog :modelType="activeTab" :visible.sync="editDialogVisible" :modelData="editModelData" @save="handleModelSave" />
    <TtsModel :visible.sync="ttsDialogVisible" :ttsModelId="selectedTtsModelId" :modelConfig="selectedModelConfig" />
    <AddModelDialog :modelType="activeTab" :visible.sync="addDialogVisible" @confirm="handleAddConfirm" />
  </div>
</template>

<script>
import Api from "@/apis/api";
import AddModelDialog from "@/components/AddModelDialog.vue";
import ModelEditDialog from "@/components/ModelEditDialog.vue";
import TtsModel from "@/components/TtsModel.vue";
export default {
  components: { ModelEditDialog, TtsModel, AddModelDialog },
  data() {
    return {
      addDialogVisible: false,
      activeTab: "llm",
      search: "",
      editDialogVisible: false,
      editModelData: {},
      ttsDialogVisible: false,
      selectedTtsModelId: "",
      modelList: [],
      pageSizeOptions: [10, 20, 50, 100],
      currentPage: 1,
      pageSize: 10,
      total: 0,
      selectedModels: [],
      isAllSelected: false,
      loading: false,
      loadFailed: false,
      lastSearch: "",
      categories: ["vad", "asr", "llm", "vllm", "intent", "tts", "memory", "rag"],
      selectedModelConfig: {},
    };
  },

  created() {
    this.loadData();
  },

  beforeDestroy() {
    clearTimeout(this._loadTimer);
  },

  computed: {
    modelTypeText() {
      return (
        this.$t("modelConfig." + this.activeTab) || this.$t("modelConfig.modelConfig")
      );
    },
    pageCount() {
      return Math.ceil(this.total / this.pageSize);
    },
  },

  methods: {
    handlePageSizeChange(val) {
      this.pageSize = val;
      this.currentPage = 1;
      this.loadData();
    },
    openTtsDialog(row) {
      this.selectedTtsModelId = row.id;
      this.selectedModelConfig = row;
      this.ttsDialogVisible = true;
    },
    handleMenuSelect(index) {
      if (index === this.activeTab) return;
      this.activeTab = index;
      this.search = "";
      this.currentPage = 1; // 重置到第一页
      this.pageSize = 10; // 可选：重置每页条数
      this.loadData();
    },
    handleSearch() {
      this.currentPage = 1;
      this.loadData();
    },
    // 批量删除
    batchDelete() {
      if (this.selectedModels.length === 0) {
        this.$message.warning(this.$t("modelConfig.selectModelsFirst"));
        return;
      }

      this.$confirm(this.$t("modelConfig.confirmBatchDelete"), this.$t("message.info"), {
        confirmButtonText: this.$t("common.confirm"),
        cancelButtonText: this.$t("common.cancel"),
        type: "warning",
      })
        .then(() => {
          const deletePromises = this.selectedModels.map(
            (model) =>
              new Promise((resolve) => {
                Api.model.deleteModel(model.id, ({ data }) => resolve(data.code === 0));
                // 业务错误（如默认模型、正在被使用）时请求层只提示不回调：超时按失败计
                setTimeout(() => resolve(false), 8000);
              })
          );

          Promise.all(deletePromises).then((results) => {
            if (results.every(Boolean)) {
              this.$message.success({
                message: this.$t("modelConfig.batchDeleteSuccess"),
                showClose: true,
              });
              this.loadData();
            } else {
              this.$message.error({
                message: this.$t("modelConfig.partialDeleteFailed"),
                showClose: true,
              });
              this.loadData();
            }
          });
        })
        .catch(() => {
          this.$message.info(this.$t("modelConfig.deleteCancelled"));
        });
    },
    addModel() {
      this.addDialogVisible = true;
    },
    editModel(model) {
      this.editModelData = JSON.parse(JSON.stringify(model));
      this.editDialogVisible = true;
    },
    duplicateModel(model) {
      this.editModelData = JSON.parse(JSON.stringify(model));
      this.editModelData.duplicateMode = true;
      this.editDialogVisible = true;
    },
    // 删除单个模型
    deleteModel(model) {
      this.$confirm(this.$t("modelConfig.confirmDelete"), this.$t("message.info"), {
        confirmButtonText: this.$t("common.confirm"),
        cancelButtonText: this.$t("common.cancel"),
        type: "warning",
      })
        .then(() => {
          Api.model.deleteModel(model.id, ({ data }) => {
            if (data.code === 0) {
              this.$message.success({
                message: this.$t("modelConfig.deleteSuccess"),
                showClose: true,
              });
              this.loadData();
            } else {
              this.$message.error({
                message: data.msg || this.$t("modelConfig.deleteFailed"),
                showClose: true,
              });
            }
          });
        })
        .catch(() => {
          this.$message.info(this.$t("modelConfig.deleteCancelled"));
        });
    },
    handleCurrentChange(page) {
      this.currentPage = page;
      this.$refs.modelTable.clearSelection();
    },
    handleModelSave({ provideCode, formData, done }) {
      const modelType = this.activeTab;
      const id = formData.id;

      if (this.editModelData.duplicateMode) {
        formData.id = "";
        Api.model.addModel({ modelType, provideCode, formData }, ({ data }) => {
          if (data.code === 0) {
            this.$message.success(this.$t("modelConfig.duplicateSuccess"));
            this.loadData();
            this.editDialogVisible = false;
          } else {
            this.$message.error(data.msg || this.$t("modelConfig.duplicateFailed"));
          }
          done && done(); // 调用done回调关闭加载状态
        });
      } else {
        Api.model.updateModel({ modelType, provideCode, id, formData }, ({ data }) => {
          if (data.code === 0) {
            this.$message.success(this.$t("modelConfig.saveSuccess"));
            this.loadData();
            this.editDialogVisible = false;
          } else {
            this.$message.error(data.msg || this.$t("modelConfig.saveFailed"));
          }
          done && done(); // 调用done回调关闭加载状态
        });
      }
    },
    selectAll() {
      if (this.isAllSelected) {
        this.$refs.modelTable.clearSelection();
      } else {
        this.$refs.modelTable.toggleAllSelection();
      }
    },
    handleSelectionChange(val) {
      this.selectedModels = val;
      this.isAllSelected = val.length === this.modelList.length;
      if (val.length === 0) {
        this.isAllSelected = false;
      }
    },

    // 新增模型配置
    handleAddConfirm(newModel) {
      const params = {
        modelType: this.activeTab,
        provideCode: newModel.provideCode,
        formData: {
          ...newModel,
          isDefault: newModel.isDefault ? 1 : 0,
          isEnabled: newModel.isEnabled ? 1 : 0,
          configJson: newModel.configJson,
        },
      };

      Api.model.addModel(params, ({ data }) => {
        if (data.code === 0) {
          this.$message.success({
            message: this.$t("modelConfig.addSuccess"),
            showClose: true,
          });
          this.loadData();
        } else {
          this.$message.error({
            message: data.msg || this.$t("modelConfig.addFailed"),
            showClose: true,
          });
        }
      });
    },

    goToPage(page) {
      this.currentPage = page;
      this.loadData();
    },

    // 获取模型配置列表
    loadData() {
      this.loading = true; // 开始加载
      this.loadFailed = false;
      clearTimeout(this._loadTimer);
      // 业务错误由请求层统一提示且不回调；超过 8 秒仍无结果时显示失败状态
      this._loadTimer = setTimeout(() => {
        if (this.loading) { this.loading = false; this.loadFailed = true; }
      }, 8000);
      const keyword = this.search;
      const params = {
        modelType: this.activeTab,
        modelName: this.search,
        page: this.currentPage,
        limit: this.pageSize,
      };

      Api.model.getModelList(params, ({ data }) => {
        this.loading = false; // 结束加载
        clearTimeout(this._loadTimer);
        if (data.code === 0) {
          this.lastSearch = keyword;
          this.modelList = data.data.list;
          this.total = data.data.total;
          // 删除最后一页的全部数据后回到上一页
          if (!this.modelList.length && this.currentPage > 1 && this.total) {
            this.currentPage = Math.max(1, this.pageCount);
            this.loadData();
          }
        } else {
          this.loadFailed = true;
          this.$message.error(data.msg || this.$t("modelConfig.fetchModelsFailed"));
        }
      });
    },
    // 处理启用/禁用状态变更
    handleStatusChange(model) {
      const newStatus = model.isEnabled ? 1 : 0;
      const originalStatus = model.isEnabled;

      model.isEnabled = !model.isEnabled;

      Api.model.updateModelStatus(model.id, newStatus, ({ data }) => {
        if (data.code === 0) {
          this.$message.success(
            newStatus === 1
              ? this.$t("modelConfig.enableSuccess")
              : this.$t("modelConfig.disableSuccess")
          );
          // 保持新状态
          model.isEnabled = newStatus;
          // 刷新表格数据
          this.loadData();
        } else {
          // 操作失败时恢复原状态
          model.isEnabled = originalStatus;
          this.$message.error(data.msg || this.$t("modelConfig.operationFailed"));
        }
      });
    },
    handleDefaultChange(model) {
      Api.model.setDefaultModel(model.id, ({ data }) => {
        if (data.code === 0) {
          this.$message.success(this.$t("modelConfig.setDefaultSuccess"));
          this.loadData();
        }
      });
    },
  },
};
</script>

<style scoped>
.mc-layout { display: grid; grid-template-columns: 200px minmax(0, 1fr); gap: 16px; align-items: start; }
.mc-nav { padding: 8px; position: sticky; top: calc(var(--xn-topbar-h) + 16px); }
.mc-nav__title { margin: 6px 10px 8px; font-size: 12px; font-weight: 600; color: var(--xn-ink-3); }
.mc-nav__item {
  display: flex; align-items: center; justify-content: space-between; gap: 8px; width: 100%; height: 40px; padding: 0 12px;
  border: 0; border-radius: var(--xn-r); background: none; color: var(--xn-ink-2); font: inherit; font-size: 14px; text-align: left; cursor: pointer;
}
.mc-nav__item:hover { background: var(--xn-mist-2); color: var(--xn-ink); }
.mc-nav__item.is-on { background: var(--xn-lake-soft); color: var(--xn-lake-ink); font-weight: 600; }
.mc-nav__code { font-size: 12px; font-weight: 500; color: var(--xn-ink-4); }
.mc-nav__item.is-on .mc-nav__code { color: var(--xn-lake); }
.mc-main { min-width: 0; }
.mc-count { font-size: 13px; }
.mc-name { font-weight: 500; color: var(--xn-ink); }
.mc-id { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; color: var(--xn-ink-3); word-break: break-all; }
.xa-search-icon { height: 100%; margin: 0 2px 0 4px; font-size: 16px; color: var(--xn-ink-3); }
.xa-panel { overflow: hidden; }
.xa-panel ::v-deep .el-table td.el-table__cell:last-child .cell { white-space: nowrap; }
.xa-code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; word-break: break-all; }
.xa-danger { color: var(--xn-danger); }
.xa-danger:hover, .xa-danger:focus { color: #8D3523; }
.xa-foot { display: flex; justify-content: flex-end; padding: 4px 16px 14px; border-top: 1px solid var(--xn-line-2); }
@media (max-width: 1100px) {
  .mc-layout { grid-template-columns: minmax(0, 1fr); }
  .mc-nav { position: static; display: flex; flex-wrap: wrap; gap: 4px; }
  .mc-nav__title { display: none; }
  .mc-nav__item { width: auto; }
  .mc-nav__code { display: none; }
}
</style>
