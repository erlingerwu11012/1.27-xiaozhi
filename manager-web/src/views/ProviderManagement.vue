<template>
  <div class="xn-page">
    <page-header :title="$t('header.providerManagement')" :description="$t('xn.admin.provider.desc')">
      <el-button type="primary" @click="showAddDialog"><xn-icon name="plus" /> {{ $t('common.addProvider') }}</el-button>
    </page-header>

    <div class="xn-toolbar">
      <el-select :value="searchModelType" class="pm-type" @change="handleSelectModelType" :aria-label="$t('providerManagement.categoryFilter')">
        <el-option :label="$t('xn.admin.provider.allTypes')" value="" />
        <el-option v-for="item in translatedModelTypes" :key="item.value" :label="item.label" :value="item.value" />
      </el-select>
      <el-input :placeholder="$t('providerManagement.searchPlaceholder')" v-model="searchName" clearable
        @keyup.enter.native="handleSearch" @clear="handleSearch">
        <xn-icon slot="prefix" name="search" class="xa-search-icon" />
      </el-input>
      <el-button @click="handleSearch">{{ $t('common.search') }}</el-button>
      <span class="xn-toolbar__grow"></span>
      <template v-if="selectedCount">
        <span class="xn-muted">{{ $t('xn.admin.selected', { n: selectedCount }) }}</span>
        <el-button type="danger" plain size="small" @click="deleteSelectedProviders"><xn-icon name="trash" /> {{ $t('xn.admin.deleteSelected') }}</el-button>
      </template>
    </div>

    <div class="xn-panel xn-panel--flush xa-panel">
      <xn-empty v-if="loadFailed && !loading" error @retry="fetchProviders" />
      <template v-else>
        <el-table ref="providersTable" :data="filteredProvidersList" v-loading="loading" row-key="id">
          <el-table-column width="52" align="center">
            <template slot="header" slot-scope="{}">
              <el-checkbox :value="isAllSelected" :indeterminate="selectedCount > 0 && !isAllSelected"
                :disabled="!providersList.length" :aria-label="$t('common.selectAll')" @change="handleSelectAll" />
            </template>
            <template slot-scope="scope"><el-checkbox v-model="scope.row.selected" /></template>
          </el-table-column>
          <el-table-column :label="$t('providerManagement.category')" width="130">
            <template slot-scope="scope">
              <span class="xn-tag xn-tag--lake">{{ getModelTypeLabel(scope.row.modelType) }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="$t('common.name')" prop="name" min-width="180" />
          <el-table-column :label="$t('providerManagement.providerCode')" min-width="150">
            <template slot-scope="{ row }"><span class="xa-code">{{ row.providerCode }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('providerManagement.fieldConfig')" min-width="200">
            <template slot-scope="scope">
              <el-popover v-if="scope.row.fields.length" placement="bottom-start" width="380" trigger="hover">
                <table class="pm-fields">
                  <tr v-for="field in scope.row.fields" :key="field.key">
                    <td class="xa-code">{{ field.key }}</td>
                    <td>{{ field.label }}</td>
                    <td class="xn-muted">{{ field.type }}</td>
                    <td><span v-if="isSensitiveField(field.key)" class="xn-tag xn-tag--warning">{{ $t('common.sensitive') }}</span></td>
                  </tr>
                </table>
                <button slot="reference" type="button" class="pm-fields-btn">
                  {{ $t('xn.admin.provider.fieldCount', { n: scope.row.fields.length }) }}
                  <span class="xn-muted xa-clip">{{ scope.row.fields.map((f) => f.key).join(', ') }}</span>
                </button>
              </el-popover>
              <span v-else class="xn-muted">{{ $t('xn.admin.provider.noFieldsShort') }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="$t('common.sort')" prop="sort" width="70" align="right" class-name="xn-num" />
          <el-table-column :label="$t('common.action')" width="120" align="right">
            <template slot-scope="scope">
              <el-button type="text" @click="editProvider(scope.row)">{{ $t('common.edit') }}</el-button>
              <el-button type="text" class="xa-danger" @click="deleteProvider(scope.row)">{{ $t('common.delete') }}</el-button>
            </template>
          </el-table-column>
          <template slot="empty">
            <xn-empty v-if="lastSearch || searchModelType" icon="search" :title="$t('xn.admin.provider.noMatch')" :description="$t('xn.admin.noMatchDesc')" />
            <xn-empty v-else icon="plug" :title="$t('xn.admin.provider.empty')" :description="$t('xn.admin.provider.emptyDesc')">
              <el-button type="primary" @click="showAddDialog"><xn-icon name="plus" /> {{ $t('common.addProvider') }}</el-button>
            </xn-empty>
          </template>
        </el-table>
        <div v-if="total" class="xa-foot">
          <el-pagination background layout="total, sizes, prev, pager, next" :total="total" :page-size="pageSize"
            :page-sizes="pageSizeOptions" :current-page="currentPage" @size-change="handlePageSizeChange" @current-change="goToPage" />
        </div>
      </template>
    </div>

    <!-- 新增/编辑供应器对话框 -->
    <provider-dialog :title="dialogTitle" :visible.sync="dialogVisible" :form="providerForm" :model-types="translatedModelTypes"
      @submit="handleSubmit" @cancel="dialogVisible = false" />
  </div>
</template>

<script>
import Api from "@/apis/api";
import ProviderDialog from "@/components/ProviderDialog.vue";

export default {
  components: { ProviderDialog },
  data() {
    return {
      searchName: "",
      searchModelType: "",
      providersList: [],
      modelTypes: [
        { value: "ASR", labelKey: 'providerManagement.modelType.ASR' },
        { value: "TTS", labelKey: 'providerManagement.modelType.TTS' },
        { value: "LLM", labelKey: 'providerManagement.modelType.LLM' },
        { value: "Intent", labelKey: 'providerManagement.modelType.Intent' },
        { value: "Memory", labelKey: 'providerManagement.modelType.Memory' },
        { value: "VAD", labelKey: 'providerManagement.modelType.VAD' },
        { value: "Plugin", labelKey: 'providerManagement.modelType.Plugin' },
        { value: "RAG", labelKey: 'providerManagement.modelType.RAG' }
      ],
      currentPage: 1,
      loading: false,
      pageSize: 10,
      pageSizeOptions: [10, 20, 50, 100],
      total: 0,
      dialogVisible: false,
      dialogTitle: "新增供应器",
      isDropdownOpen: false,
      loadFailed: false,
      lastSearch: "",
      sensitive_keys: ["api_key", "personal_access_token", "access_token", "token", "secret", "access_key_secret", "secret_key"],
      providerForm: {
        id: null,
        modelType: "",
        providerCode: "",
        name: "",
        fields: [],
        sort: 0
      },
      DropdownVisible: false,
    };
  },
  created() {
    this.fetchProviders();
  },
  beforeDestroy() {
    clearTimeout(this._loadTimer);
  },
  computed: {
    selectedCount() {
      return this.providersList.filter((p) => p.selected).length;
    },
    isAllSelected() {
      return this.providersList.length > 0 && this.providersList.every((p) => p.selected);
    },
    translatedModelTypes() {
      return this.modelTypes.map(type => ({
        value: type.value,
        label: this.$t(type.labelKey)
      }));
    },
    selectedModelTypeLabel() {
      if (!this.searchModelType) return `（${this.$t('providerManagement.all')}）`;
      const selectedType = this.modelTypes.find(item => item.value === this.searchModelType);
      return selectedType ? `（${this.$t(selectedType.labelKey)}）` : "";
    },
    pageCount() {
      return Math.ceil(this.total / this.pageSize);
    },
    visiblePages() {
      const pages = [];
      const maxVisible = 3;
      let start = Math.max(1, this.currentPage - 1);
      let end = Math.min(this.pageCount, start + maxVisible - 1);

      if (end - start + 1 < maxVisible) {
        start = Math.max(1, end - maxVisible + 1);
      }

      for (let i = start; i <= end; i++) {
        pages.push(i);
      }
      return pages;
    },
    filteredProvidersList() {
      return this.providersList;

      // let list = this.providersList.filter(item => {
      //   const nameMatch = item.name.toLowerCase().includes(this.searchName.toLowerCase());
      //   const typeMatch = !this.searchModelType || item.model_type === this.searchModelType;
      //   return nameMatch && typeMatch;
      // });

      // list.sort((a, b) => a.sort - b.sort);

      // // 分页处理
      // const start = (this.currentPage - 1) * this.pageSize;
      // return list.slice(start, start + this.pageSize);
    }
  },
  methods: {
    fetchProviders() {
      this.loading = true;
      this.loadFailed = false;
      clearTimeout(this._loadTimer);
      // 业务错误由请求层统一提示且不回调；超过 8 秒仍无结果时显示失败状态
      this._loadTimer = setTimeout(() => {
        if (this.loading) { this.loading = false; this.loadFailed = true; }
      }, 8000);
      const keyword = this.searchName;

      Api.model.getModelProvidersPage(
        {
          page: this.currentPage,
          limit: this.pageSize,
          name: this.searchName,
          modelType: this.searchModelType
        },
        ({ data }) => {
          this.loading = false;
          clearTimeout(this._loadTimer);
          if (data.code === 0) {
            this.lastSearch = keyword;
            this.providersList = data.data.list.map(item => {
              return {
                ...item,
                selected: false,
                fields: (() => { try { return JSON.parse(item.fields || '[]') || []; } catch (e) { return []; } })()
              };
            });
            this.total = data.data.total;
          } else {
            this.loadFailed = true;
            this.$message.error({
              message: data.msg || this.$t('xn.admin.provider.loadFailed')
            });
          }
        }
      );
    },
    handleSearch() {
      this.currentPage = 1;
      this.fetchProviders();
    },
    handleSelectModelType(value) {
      this.isDropdownOpen = false;
      this.searchModelType = value;
      this.handleSearch();
    },
    handleSelectAll() {
      const next = !this.isAllSelected;
      this.providersList.forEach(row => {
        row.selected = next;
      });
    },
    showAddDialog() {
      this.dialogTitle = this.$t('common.addProvider');
      this.providerForm = {
        id: null,
        modelType: "",
        providerCode: "",
        name: "",
        fields: [],
        sort: 0
      };
      this.dialogVisible = true;
    },
    editProvider(row) {
      this.dialogTitle = this.$t('common.editProvider');
      this.providerForm = {
        ...row,
        fields: JSON.parse(JSON.stringify(row.fields))
      };
      this.dialogVisible = true;
    },
    handleSubmit({ form, done }) {
      this.loading = true;
      if (form.id) {
        // 编辑
        Api.model.updateModelProvider(form, ({ data }) => {

          if (data.code === 0) {
            this.fetchProviders(); // 刷新表格
            this.$message.success({
            message: this.$t('common.updateSuccess'),
            showClose: true
          });
          }
        });
      } else {
        // 新增
        Api.model.addModelProvider(form, ({ data }) => {
          if (data.code === 0) {
            this.fetchProviders(); // 刷新表格
            this.$message.success({
            message: this.$t('common.addSuccess'),
            showClose: true
          });
            this.total += 1;
          }
        });
      }
      this.loading = false;
      this.dialogVisible = false;
      done && done();
    },
    deleteSelectedProviders() {
      const selectedRows = this.providersList.filter(row => row.selected);
      if (selectedRows.length === 0) {
        this.$message.warning({
          message: this.$t('providerManagement.selectToDelete'),
          showClose: true
        });
        return;
      }
      this.deleteProvider(selectedRows);
    },
    deleteProvider(row) {
      const providers = Array.isArray(row) ? row : [row];
      const providerCount = providers.length;

      this.$confirm(this.$t('providerManagement.confirmDelete', { count: providerCount }), this.$t('common.warning'), {
        confirmButtonText: this.$t('common.confirm'),
        cancelButtonText: this.$t('common.cancel'),
        type: 'warning',
      }).then(() => {
        const ids = providers.map(provider => provider.id);
        Api.model.deleteModelProviderByIds(ids, ({ data }) => {
          if (data.code === 0) {

            this.fetchProviders(); // 刷新表格

            this.$message.success({
              message: this.$t('common.deleteSuccess'),
              showClose: true
            });
          } else {
            this.$message.error({
              message: data.msg || this.$t('common.deleteFailure'),
              showClose: true
            });
          }
        });
      }).catch(() => {
        this.$message({
          type: 'info',
          message: this.$t('common.deleteCancelled'),
          showClose: true,
          duration: 1000
        });
      });
    },
    getModelTypeTag(type) {
      const typeMap = {
        'ASR': 'success',
        'TTS': 'warning',
        'LLM': 'danger',
        'Intent': 'info',
        'Memory': '',
        'VAD': 'primary',
        'RAG': 'warning'
      };
      return typeMap[type] || '';
    },
    getModelTypeLabel(type) {
      const typeItem = this.modelTypes.find(item => item.value === type);
      return typeItem ? this.$t(typeItem.labelKey) : type;
    },
    isSensitiveField(fieldKey) {
      if (typeof fieldKey !== 'string') return false;
      return this.sensitive_keys.some(key =>
        fieldKey.toLowerCase().includes(key.toLowerCase())
      );
    },
    handlePageSizeChange(val) {
      this.pageSize = val;
      this.currentPage = 1;
      this.fetchProviders();
    },
    headerCellClassName({ columnIndex }) {
      if (columnIndex === 0) {
        return "custom-selection-header";
      }
      return "";
    },
    selectionCellClassName() {
      return "custom-selection-cell";
    },
    updateSelectionHeaderText() {
      // 确保表格已渲染
      this.$nextTick(() => {
        if (this.$refs.providersTable && this.$refs.providersTable.$el) {
          const headerCheckbox = this.$refs.providersTable.$el.querySelector('.custom-selection-header .el-checkbox .el-checkbox__label');
          if (headerCheckbox) {
            headerCheckbox.textContent = this.$t('modelConfig.select');
          }
        }
      });
    },
    mounted() {
      this.updateSelectionHeaderText();
    },
    updated() {
      this.updateSelectionHeaderText();
    },
    goFirst() {
      this.currentPage = 1;
      this.fetchProviders();
    },
    goPrev() {
      if (this.currentPage > 1) {
        this.currentPage--;
        this.fetchProviders();
      }
    },
    goNext() {
      if (this.currentPage < this.pageCount) {
        this.currentPage++;
        this.fetchProviders();
      }
    },
    goToPage(page) {
      this.currentPage = page;
      this.fetchProviders();
    },
    handleDropdownVisibleChange(visible) {
      this.DropdownVisible = visible;
    },
  },
};
</script>

<style scoped>
.pm-type { width: 160px; }
.xa-search-icon { height: 100%; margin: 0 2px 0 4px; font-size: 16px; color: var(--xn-ink-3); }
.xa-panel { overflow: hidden; }
.xa-code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; word-break: break-all; }
.xa-clip { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; }
.pm-fields-btn { display: block; max-width: 100%; padding: 2px 0; border: 0; background: none; font: inherit; color: var(--xn-lake); text-align: left; cursor: pointer; }
.pm-fields-btn:hover { color: var(--xn-lake-ink); }
.pm-fields { width: 100%; border-collapse: collapse; font-size: 13px; color: var(--xn-ink); }
.pm-fields td { padding: 6px 8px; border-bottom: 1px solid var(--xn-line-2); vertical-align: middle; }
.pm-fields tr:last-child td { border-bottom: 0; }
.xa-danger { color: var(--xn-danger); }
.xa-danger:hover, .xa-danger:focus { color: #8D3523; }
.xa-foot { display: flex; justify-content: flex-end; padding: 4px 16px 14px; border-top: 1px solid var(--xn-line-2); }
@media (max-width: 960px) { .pm-type { width: 100%; } }
</style>
