<template>
  <div class="xn-page">
    <page-header :title="$t('paramManagement.pageTitle')" :description="$t('xn.admin.params.desc')">
      <el-button type="primary" @click="showAddDialog"><xn-icon name="plus" /> {{ $t('paramManagement.addParam') }}</el-button>
    </page-header>

    <div class="xn-toolbar">
      <el-input :placeholder="$t('paramManagement.searchPlaceholder')" v-model="searchCode" clearable
        @keyup.enter.native="handleSearch" @clear="handleSearch">
        <xn-icon slot="prefix" name="search" class="xa-search-icon" />
      </el-input>
      <el-button @click="handleSearch">{{ $t('paramManagement.search') }}</el-button>
      <span class="xn-toolbar__grow"></span>
      <template v-if="selectedCount">
        <span class="xn-muted">{{ $t('xn.admin.selected', { n: selectedCount }) }}</span>
        <el-button type="danger" plain size="small" @click="deleteSelectedParams"><xn-icon name="trash" /> {{ $t('xn.admin.deleteSelected') }}</el-button>
      </template>
    </div>

    <div class="xn-panel xn-panel--flush xa-panel">
      <xn-empty v-if="loadFailed && !loading" error @retry="fetchParams" />
      <template v-else>
        <el-table ref="paramsTable" :data="paramsList" v-loading="loading" row-key="id">
          <el-table-column width="52" align="center">
            <template slot="header" slot-scope="{}">
              <el-checkbox :value="isAllSelected" :indeterminate="selectedCount > 0 && !isAllSelected"
                :disabled="!paramsList.length" :aria-label="$t('paramManagement.selectAll')" @change="handleSelectAll" />
            </template>
            <template slot-scope="scope"><el-checkbox v-model="scope.row.selected" /></template>
          </el-table-column>
          <el-table-column :label="$t('paramManagement.paramCode')" min-width="220">
            <template slot-scope="{ row }"><span class="xa-code">{{ row.paramCode }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('paramManagement.paramValue')" min-width="260">
            <template slot-scope="scope">
              <div v-if="isSensitiveParam(scope.row.paramCode)" class="xa-secret">
                <span class="xn-num xa-value">{{ scope.row.showValue ? scope.row.paramValue : maskSensitiveValue(scope.row.paramValue) }}</span>
                <el-button type="text" @click="toggleSensitiveValue(scope.row)">
                  {{ scope.row.showValue ? $t('paramManagement.hide') : $t('paramManagement.view') }}
                </el-button>
              </div>
              <span v-else class="xa-value" :title="scope.row.paramValue">{{ scope.row.paramValue }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="$t('paramDialog.valueType')" width="100">
            <template slot-scope="{ row }"><span class="xn-tag xn-tag--muted">{{ row.valueType }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('paramManagement.remark')" prop="remark" min-width="200" show-overflow-tooltip />
          <el-table-column :label="$t('paramManagement.operation')" width="130" align="right">
            <template slot-scope="scope">
              <el-button type="text" @click="editParam(scope.row)">{{ $t('paramManagement.edit') }}</el-button>
              <el-button type="text" class="xa-danger" @click="deleteParam(scope.row)">{{ $t('paramManagement.delete') }}</el-button>
            </template>
          </el-table-column>
          <template slot="empty">
            <xn-empty v-if="lastSearch" icon="search" :title="$t('xn.admin.params.noMatch')" :description="$t('xn.admin.noMatchDesc')" />
            <xn-empty v-else icon="tune" :title="$t('xn.admin.params.empty')" :description="$t('xn.admin.params.emptyDesc')">
              <el-button type="primary" @click="showAddDialog"><xn-icon name="plus" /> {{ $t('paramManagement.addParam') }}</el-button>
            </xn-empty>
          </template>
        </el-table>
        <div v-if="total" class="xa-foot">
          <el-pagination background layout="total, sizes, prev, pager, next" :total="total" :page-size="pageSize"
            :page-sizes="pageSizeOptions" :current-page="currentPage" @size-change="handlePageSizeChange" @current-change="goToPage" />
        </div>
      </template>
    </div>

    <!-- 新增/编辑参数对话框 -->
    <param-dialog ref="paramDialog" :title="dialogTitle" :visible.sync="dialogVisible" :form="paramForm"
      @submit="handleSubmit" @cancel="dialogVisible = false" />
  </div>
</template>

<script>
import Api from "@/apis/api";
import ParamDialog from "@/components/ParamDialog.vue";

export default {
  components: { ParamDialog },
  data() {
    return {
      searchCode: "",
      lastSearch: "",
      paramsList: [],
      currentPage: 1,
      loading: false,
      loadFailed: false,
      pageSize: 10,
      pageSizeOptions: [10, 20, 50, 100],
      total: 0,
      dialogVisible: false,
      dialogTitle: "新增参数",
      sensitive_keys: ["api_key", "personal_access_token", "access_token", "token", "secret", "access_key_secret", "secret_key", "password", "mqtt_signature_key", "private_key"],
      paramForm: {
        id: null,
        paramCode: "",
        paramValue: "",
        valueType: "string",
        remark: ""
      },
    };
  },
  created() {
    this.fetchParams();
  },
  beforeDestroy() {
    clearTimeout(this._loadTimer);
  },
  computed: {
    pageCount() {
      return Math.ceil(this.total / this.pageSize);
    },
    selectedCount() {
      return this.paramsList.filter((p) => p.selected).length;
    },
    isAllSelected() {
      return this.paramsList.length > 0 && this.paramsList.every((p) => p.selected);
    },
  },
  methods: {
    handlePageSizeChange(val) {
      this.pageSize = val;
      this.currentPage = 1;
      this.fetchParams();
    },
    // 业务错误由请求层统一提示且不回调；超过 8 秒仍无结果时显示失败状态
    startLoading() {
      this.loading = true;
      this.loadFailed = false;
      clearTimeout(this._loadTimer);
      this._loadTimer = setTimeout(() => {
        if (this.loading) { this.loading = false; this.loadFailed = true; }
      }, 8000);
    },
    fetchParams() {
      this.startLoading();
      Api.admin.getParamsList(
        {
          page: this.currentPage,
          limit: this.pageSize,
          paramCode: this.searchCode,
        },
        ({ data }) => {
          this.loading = false;
          clearTimeout(this._loadTimer);
          if (data.code === 0) {
            this.lastSearch = this.searchCode;
            this.paramsList = data.data.list.map(item => ({
              ...item,
              valueType: item.valueType || "string",
              selected: false,
              showValue: false
            }));
            this.total = data.data.total;
            // 删除最后一页的全部数据后回到上一页
            if (!this.paramsList.length && this.currentPage > 1 && this.total) {
              this.currentPage = Math.max(1, this.pageCount);
              this.fetchParams();
            }
          } else {
            this.loadFailed = true;
            this.$message.error({
              message: data.msg || this.$t('paramManagement.getParamsListFailed'),
              showClose: true
            });
          }
        }
      );
    },
    handleSearch() {
      this.currentPage = 1;
      this.fetchParams();
    },
    handleSelectAll() {
      const next = !this.isAllSelected;
      this.paramsList.forEach(row => {
        row.selected = next;
      });
    },
    showAddDialog() {
      this.dialogTitle = this.$t('paramManagement.addParam');
      this.paramForm = {
        id: null,
        paramCode: "",
        paramValue: "",
        valueType: "string", // 默认值
        remark: ""
      };
      this.dialogVisible = true;
    },
    editParam(row) {
      this.dialogTitle = this.$t('paramManagement.editParam');
      this.paramForm = {
        id: row.id,
        paramCode: row.paramCode,
        paramValue: row.paramValue,
        valueType: row.valueType || "string", // 确保有值
        remark: row.remark
      };
      this.dialogVisible = true;
    },
    handleSubmit(form) {
      if (form.id) {
        // 更新参数
        Api.admin.updateParam(form, ({ data }) => {
          this.dialogVisible = false;
          this.fetchParams();
          this.$message.success({
            message: data && data.msg && data.msg !== 'success' ? data.msg : this.$t('paramManagement.updateSuccess'),
            showClose: true
          });
        }, ({ data }) => {
          this.$message.error({
            message: data.msg || this.$t('paramManagement.updateFailed'),
            showClose: true
          });
          // 调用ParamDialog的resetSaving方法重置保存状态
          if (this.$refs.paramDialog && typeof this.$refs.paramDialog.resetSaving === 'function') {
            this.$refs.paramDialog.resetSaving();
          }
        });
      } else {
        // 新增参数
        Api.admin.addParam(form, ({ data }) => {
          if (data.code === 0) {
            this.dialogVisible = false;
            this.fetchParams();
            this.$message.success({
              message: data.msg && data.msg !== 'success' ? data.msg : this.$t('paramManagement.addSuccess'),
              showClose: true
            });
          } else {
            this.$message.error({
              message: data.msg || this.$t('paramManagement.addFailed'),
              showClose: true
            });
            // 调用ParamDialog的resetSaving方法重置保存状态
            if (this.$refs.paramDialog && typeof this.$refs.paramDialog.resetSaving === 'function') {
              this.$refs.paramDialog.resetSaving();
            }
          }
        });
      }
    },
    deleteSelectedParams() {
      const selectedParams = this.paramsList.filter(row => row.selected);
      if (selectedParams.length === 0) {
        this.$message.warning({
          message: this.$t('paramManagement.selectParamsFirst'),
          showClose: true
        });
        return;
      }
      this.deleteParams(selectedParams);
    },
    deleteParam(row) {
      if (!row.id) {
        this.$message.warning({
          message: this.$t('paramManagement.selectParamsFirst'),
          showClose: true
        });
        return;
      }
      this.deleteParams([row]);
    },
    deleteParams(params) {
      const paramCount = params.length;
      const paramIds = params.map(param => param.id).filter(id => id);
      if (paramIds.length === 0) {
        this.$message.error({
          message: this.$t('paramManagement.invalidParamId'),
          showClose: true
        });
        return;
      }
      this.$confirm(this.$t('paramManagement.confirmBatchDelete', { paramCount }), this.$t('xn.admin.params.deleteTitle'), {
        confirmButtonText: this.$t('paramManagement.delete'),
        cancelButtonText: this.$t('button.cancel'),
        type: 'warning'
      }).then(() => {
        Api.admin.deleteParam(paramIds, ({ data }) => {
          if (data.code === 0) {
            this.fetchParams();
            this.$message.success({
              message: this.$t('paramManagement.batchDeleteSuccess', { paramCount }),
              showClose: true
            });
          } else {
            this.$message.error({
              message: data.msg || this.$t('paramManagement.deleteFailed'),
              showClose: true
            });
          }
        });
      }).catch(() => {
        this.$message({
          type: 'info',
          message: this.$t('paramManagement.operationCancelled'),
          duration: 1000
        });
      });
    },
    goToPage(page) {
      if (page !== this.currentPage) {
        this.currentPage = page;
        this.fetchParams();
      }
    },
    isSensitiveParam(paramCode) {
      return this.sensitive_keys.some(key => String(paramCode || '').toLowerCase().includes(key));
    },
    maskSensitiveValue(value) {
      value = String(value == null ? '' : value);
      if (value.length <= 4) {
        return '****';
      }
      return value.substring(0, 2) + '****' + value.substring(value.length - 2);
    },
    toggleSensitiveValue(row) {
      row.showValue = !row.showValue;
    },
  }
};
</script>

<style scoped>
.xa-search-icon { height: 100%; margin: 0 2px 0 4px; font-size: 16px; color: var(--xn-ink-3); }
.xa-panel { overflow: hidden; }
.xa-code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; color: var(--xn-ink); word-break: break-all; }
.xa-value { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; word-break: break-all; }
.xa-secret { display: flex; align-items: center; gap: 8px; }
.xa-danger { color: var(--xn-danger); }
.xa-danger:hover, .xa-danger:focus { color: #8D3523; }
.xa-foot { display: flex; justify-content: flex-end; padding: 4px 16px 14px; border-top: 1px solid var(--xn-line-2); }
</style>
