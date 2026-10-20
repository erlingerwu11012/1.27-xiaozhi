<template>
  <div class="xn-page">
    <page-header :title="$t('agentTemplateManagement.title')" :description="$t('xn.agents.tpl.desc')">
      <el-button type="primary" @click="showAddTemplateDialog"><xn-icon name="plus" /> {{ $t('agentTemplateManagement.createTemplate') }}</el-button>
    </page-header>

    <div class="xn-toolbar">
      <el-input v-model="search" :placeholder="$t('agentTemplateManagement.searchPlaceholder')" clearable
        @keyup.enter.native="handleSearch" @clear="handleSearch">
        <xn-icon slot="prefix" name="search" class="tm-search-icon" />
      </el-input>
      <el-button @click="handleSearch">{{ $t('agentTemplateManagement.search') }}</el-button>
      <span class="xn-toolbar__grow"></span>
      <template v-if="hasSelected">
        <span class="xn-muted">{{ $t('xn.agents.tpl.selected', { n: selectedTemplates.length }) }}</span>
        <el-button type="danger" plain size="small" @click="batchDeleteTemplate"><xn-icon name="trash" /> {{ $t('agentTemplateManagement.batchDelete') }}</el-button>
      </template>
    </div>

    <div class="xn-panel xn-panel--flush tm-panel">
      <xn-empty v-if="loadFailed && !templateLoading" error @retry="loadTemplateList" />
      <template v-else>
        <el-table ref="templateTable" :data="templateList" v-loading="templateLoading" row-key="id">
          <el-table-column width="52" align="center">
            <template slot="header" slot-scope="{}">
              <el-checkbox :value="isAllSelected" :indeterminate="hasSelected && !isAllSelected" :disabled="!templateList.length"
                :aria-label="isAllSelected ? $t('agentTemplateManagement.deselectAll') : $t('agentTemplateManagement.selectAll')"
                @change="handleSelectAll" />
            </template>
            <template slot-scope="scope">
              <el-checkbox v-model="scope.row.selected" :aria-label="scope.row.agentName" @change="handleRowSelectionChange(scope.row)" />
            </template>
          </el-table-column>
          <el-table-column :label="$t('agentTemplateManagement.serialNumber')" width="76">
            <template slot-scope="scope">
              <span class="xn-num xn-muted">{{ (currentPage - 1) * pageSize + scope.$index + 1 }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="$t('agentTemplateManagement.templateName')" min-width="200">
            <template slot-scope="scope">
              <button type="button" class="tm-name xn-clip" @click="editTemplate(scope.row)">{{ scope.row.agentName }}</button>
            </template>
          </el-table-column>
          <el-table-column :label="$t('xn.agents.tpl.prompt')" min-width="320">
            <template slot-scope="{ row }">
              <span v-if="row.systemPrompt" class="tm-prompt">{{ row.systemPrompt }}</span>
              <span v-else class="xn-muted">{{ $t('xn.agents.tpl.noPrompt') }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="$t('agentTemplateManagement.action')" width="170" align="right">
            <template slot-scope="scope">
              <el-button type="text" @click="editTemplate(scope.row)">{{ $t('agentTemplateManagement.editTemplate') }}</el-button>
              <el-button type="text" class="tm-danger" @click="deleteTemplate(scope.row)">{{ $t('agentTemplateManagement.deleteTemplate') }}</el-button>
            </template>
          </el-table-column>
          <template slot="empty">
            <xn-empty v-if="activeSearch" icon="search" :title="$t('xn.agents.tpl.noMatch')" :description="$t('xn.agents.tpl.noMatchDesc')">
              <el-button @click="clearSearch">{{ $t('xn.agents.tpl.clearSearch') }}</el-button>
            </xn-empty>
            <xn-empty v-else icon="template" :title="$t('xn.agents.tpl.emptyTitle')" :description="$t('xn.agents.tpl.emptyDesc')">
              <el-button type="primary" @click="showAddTemplateDialog"><xn-icon name="plus" /> {{ $t('agentTemplateManagement.createTemplate') }}</el-button>
            </xn-empty>
          </template>
        </el-table>
        <div v-if="total > 0" class="tm-foot">
          <el-pagination background layout="total, sizes, prev, pager, next" :total="total"
            :current-page="currentPage" :page-size="pageSize" :page-sizes="pageSizeOptions"
            @size-change="handlePageSizeChange" @current-change="handlePageChange" />
        </div>
      </template>
    </div>
  </div>
</template>

<script>
import agentApi from "@/apis/module/agent";

const LOAD_TIMEOUT = 10000;   // 回调迟迟不来（业务错误不会进入 success 回调）时显示失败状态

export default {
  name: "AgentTemplateManagement",

  data() {
    return {
      // 模板相关
      templateList: [],
      templateLoading: false,
      selectedTemplates: [],
      isAllSelected: false, // 添加全选状态
      loadFailed: false,
      loadWatch: null,

      search: "",
      activeSearch: "",
      // 分页相关数据
      pageSizeOptions: [10, 20, 50, 100],
      currentPage: 1,
      pageSize: 10,
      total: 0,
    };
  },
  created() {
    this.loadTemplateList();
  },
  beforeDestroy() {
    clearTimeout(this.loadWatch);
  },
  computed: {
    hasSelected() {
      return this.selectedTemplates.length > 0;
    },
  },
  methods: {
    // 加载模板列表（按名称搜索时带上 agentName 参数）
    loadTemplateList() {
      this.templateLoading = true;
      this.loadFailed = false;
      this.selectedTemplates = [];
      this.isAllSelected = false;
      const params = {
        page: this.currentPage,
        limit: this.pageSize,
      };
      if (this.activeSearch) {
        params.agentName = this.activeSearch;
      }
      clearTimeout(this.loadWatch);
      this.loadWatch = setTimeout(() => {
        this.templateLoading = false;
        this.loadFailed = true;
      }, LOAD_TIMEOUT);

      try {
        agentApi.getAgentTemplatesPage(
          params,
          (res) => {
            clearTimeout(this.loadWatch);
            // 更健壮的响应处理逻辑
            if (res && typeof res === "object") {
              if (res.data && res.data.code === 0) {
                const responseData = res.data.data || {};
                // 为每个模板添加selected属性
                this.templateList = Array.isArray(responseData.list)
                  ? responseData.list.map((item) => ({ ...item, selected: false }))
                  : [];
                this.total =
                  typeof responseData.total === "number" ? responseData.total : 0;
                // 删除最后一页的最后几条后，当前页可能已经不存在：回到最后一页
                if (!this.templateList.length && this.total > 0 && this.currentPage > 1) {
                  this.currentPage = Math.max(1, Math.ceil(this.total / this.pageSize));
                  this.loadTemplateList();
                  return;
                }
              } else {
                this.templateList = [];
                this.total = 0;
                this.loadFailed = true;
                this.$message.error(
                  res?.data?.msg || this.$t("agentTemplateManagement.fetchTemplateFailed")
                );
              }
            } else {
              this.templateList = [];
              this.total = 0;
              this.loadFailed = true;
              this.$message.error(
                this.$t("agentTemplateManagement.fetchTemplateBackendError")
              );
            }
            this.templateLoading = false;
          }
        );
      } catch (error) {
        clearTimeout(this.loadWatch);
        this.templateList = [];
        this.total = 0;
        this.templateLoading = false;
        this.loadFailed = true;
        this.$message.error(this.$t("agentTemplateManagement.fetchTemplateBackendError"));
      }
    },

    // 搜索模板：从第一页开始，按名称查询
    handleSearch() {
      this.activeSearch = (this.search || "").trim();
      this.currentPage = 1;
      this.loadTemplateList();
    },
    clearSearch() {
      this.search = "";
      this.handleSearch();
    },

    // 新增与编辑使用同一个页面：不带 templateId 表示新增
    showAddTemplateDialog() {
      this.$router.push({
        path: "/template-quick-config",
      });
    },

    // 编辑模板
    editTemplate(row) {
      this.$router.push({
        path: "/template-quick-config",
        query: { templateId: row.id },
      });
    },

    // 删除模板
    deleteTemplate(row) {
      this.$confirm(
        this.$t("xn.agents.tpl.confirmDelete", { name: row.agentName }),
        this.$t("agentTemplateManagement.deleteTemplate"),
        {
          confirmButtonText: this.$t("agentTemplateManagement.deleteTemplate"),
          cancelButtonText: this.$t("common.cancel"),
          type: "warning",
        }
      )
        .then(() => {
          agentApi.deleteAgentTemplate(row.id, (res) => {
            if (res && typeof res === "object") {
              if (res.data && res.data.code === 0) {
                this.$message.success(this.$t("agentTemplateManagement.deleteSuccess"));
                this.loadTemplateList();
              } else {
                this.$message.error(
                  res?.data?.msg || this.$t("agentTemplateManagement.deleteFailed")
                );
              }
            } else {
              this.$message.error(this.$t("agentTemplateManagement.deleteBackendError"));
            }
          });
        })
        .catch(() => {});
    },

    // 批量删除模板
    batchDeleteTemplate() {
      if (this.selectedTemplates.length === 0) {
        this.$message.warning(this.$t("agentTemplateManagement.selectTemplate"));
        return;
      }

      this.$confirm(
        this.$t("agentTemplateManagement.confirmBatchDelete", {
          count: this.selectedTemplates.length,
        }),
        this.$t("agentTemplateManagement.batchDelete"),
        {
          confirmButtonText: this.$t("xn.agents.tpl.deleteN", { n: this.selectedTemplates.length }),
          cancelButtonText: this.$t("common.cancel"),
          type: "warning",
        }
      )
        .then(() => {
          // 将 id 数组作为请求体
          const ids = this.selectedTemplates.map((template) => template.id);

          agentApi.batchDeleteAgentTemplate(ids, (res) => {
            if (res && typeof res === "object") {
              if (res.data && res.data.code === 0) {
                this.$message.success(
                  this.$t("agentTemplateManagement.batchDeleteSuccess")
                );
                // 清空选中状态并重新加载
                this.selectedTemplates = [];
                this.isAllSelected = false;
                this.loadTemplateList();
              } else {
                this.$message.error(
                  res?.data?.msg || this.$t("agentTemplateManagement.batchDeleteFailed")
                );
              }
            } else {
              this.$message.error(this.$t("agentTemplateManagement.deleteBackendError"));
            }
          });
        })
        .catch(() => {});
    },

    handlePageChange(page) {
      this.currentPage = page;
      this.loadTemplateList();
    },

    handlePageSizeChange(size) {
      this.pageSize = size;
      this.currentPage = 1;
      this.loadTemplateList();
    },

    // 全选 / 取消全选（当前页）
    handleSelectAll() {
      this.isAllSelected = !this.isAllSelected;
      this.templateList.forEach((row) => {
        row.selected = this.isAllSelected;
      });
      this.selectedTemplates = this.isAllSelected ? [...this.templateList] : [];
    },

    // 处理行选择变化
    handleRowSelectionChange() {
      this.selectedTemplates = this.templateList.filter((template) => template.selected);
      this.isAllSelected =
        this.templateList.length > 0 &&
        this.selectedTemplates.length === this.templateList.length;
    },
  },
};
</script>

<style scoped>
.tm-search-icon { height: 100%; margin: 0 2px 0 4px; font-size: 16px; color: var(--xn-ink-3); }
.tm-panel { overflow: hidden; }
.tm-panel ::v-deep .el-table__empty-text { width: 100%; line-height: 1.6; }
.tm-name { max-width: 100%; padding: 0; border: 0; background: none; font: inherit; font-weight: 600; color: var(--xn-ink); text-align: left; cursor: pointer; }
.tm-name:hover { color: var(--xn-lake); }
.tm-prompt { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; font-size: 13px; color: var(--xn-ink-2); }
.tm-danger { color: var(--xn-danger); }
.tm-danger:hover, .tm-danger:focus { color: #8D3523; }
.tm-foot { display: flex; justify-content: flex-end; padding: 4px 16px 14px; border-top: 1px solid var(--xn-line-2); }
</style>
