<template>
  <div class="xn-page">
    <page-header :title="$t('knowledgeBaseManagement.title')" :description="$t('xn.knowledge.kbDesc')">
      <el-button type="primary" @click="showAddDialog"><xn-icon name="plus" /> {{ $t('knowledgeBaseManagement.addKnowledgeBase') }}</el-button>
    </page-header>

    <div class="xn-toolbar">
      <el-input v-model="searchName" :placeholder="$t('knowledgeBaseManagement.searchPlaceholder')" clearable
        @keyup.enter.native="handleSearch" @clear="handleSearch">
        <xn-icon slot="prefix" name="search" class="kb-search-icon" />
      </el-input>
      <el-button @click="handleSearch">{{ $t('knowledgeBaseManagement.search') }}</el-button>
      <span class="xn-toolbar__grow"></span>
      <template v-if="selectedKnowledgeBase.length">
        <span class="xn-muted">{{ $t('xn.knowledge.selectedKb', { n: selectedKnowledgeBase.length }) }}</span>
        <el-button type="danger" plain size="small" @click="deleteSelectedKnowledgeBase"><xn-icon name="trash" /> {{ $t('xn.knowledge.deleteSelected') }}</el-button>
      </template>
    </div>

    <div class="xn-panel xn-panel--flush kb-panel">
      <xn-empty v-if="loadFailed && !loading" error @retry="fetchKnowledgeBaseList" />
      <template v-else>
        <el-table ref="paramsTable" :data="knowledgeBaseList" v-loading="loading" row-key="datasetId"
          @selection-change="handleSelectionChange">
          <el-table-column type="selection" width="52" align="center" />
          <el-table-column :label="$t('knowledgeBaseManagement.name')" min-width="180">
            <template slot-scope="scope">
              <button type="button" class="kb-name" @click="showViewDialog(scope.row)">
                <xn-icon name="book" class="kb-name__icon" /><span class="xn-clip">{{ scope.row.name }}</span>
              </button>
            </template>
          </el-table-column>
          <el-table-column :label="$t('knowledgeBaseManagement.description')" min-width="240" show-overflow-tooltip>
            <template slot-scope="scope">
              <span :class="{ 'xn-muted': !scope.row.description }">{{ scope.row.description || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column :label="$t('knowledgeBaseManagement.documentCount')" width="100" align="right">
            <template slot-scope="scope"><span class="xn-num">{{ scope.row.documentCount || 0 }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('knowledgeBaseManagement.status')" width="110">
            <template slot-scope="scope">
              <span class="kb-status">
                <el-switch v-model="scope.row.status" :active-value="1" :inactive-value="0"
                  :aria-label="$t('knowledgeBaseManagement.status')" @change="handleStatusChange(scope.row)" />
                <span class="kb-status__text" :class="{ 'xn-muted': scope.row.status !== 1 }">{{ scope.row.status === 1 ? $t('knowledgeBaseDialog.statusEnabled') : $t('knowledgeBaseDialog.statusDisabled') }}</span>
              </span>
            </template>
          </el-table-column>
          <el-table-column :label="$t('knowledgeBaseManagement.createdAt')" width="170" class-name="kb-nowrap">
            <template slot-scope="scope"><span class="xn-num">{{ formatDate(scope.row.createdAt) }}</span></template>
          </el-table-column>
          <el-table-column :label="$t('knowledgeBaseManagement.operation')" width="190" align="right">
            <template slot-scope="scope">
              <el-button type="text" @click="showViewDialog(scope.row)">{{ $t('knowledgeBaseManagement.view') }}</el-button>
              <el-button type="text" @click="showEditDialog(scope.row)">{{ $t('knowledgeBaseManagement.edit') }}</el-button>
              <el-button type="text" class="kb-danger" @click="deleteSingleKnowledgeBase(scope.row)">{{ $t('knowledgeBaseManagement.delete') }}</el-button>
            </template>
          </el-table-column>
          <template slot="empty">
            <xn-empty v-if="activeSearchName" icon="search" :title="$t('xn.knowledge.kbNoMatch')"
              :description="$t('xn.knowledge.kbNoMatchDesc')" />
            <xn-empty v-else icon="book" :title="$t('xn.knowledge.kbEmptyTitle')" :description="$t('xn.knowledge.kbEmptyDesc')">
              <el-button type="primary" @click="showAddDialog"><xn-icon name="plus" /> {{ $t('knowledgeBaseManagement.addKnowledgeBase') }}</el-button>
            </xn-empty>
          </template>
        </el-table>
        <div v-if="total > 0" class="kb-foot">
          <el-pagination background layout="total, sizes, prev, pager, next" :total="total"
            :page-size="pageSize" :page-sizes="pageSizeOptions" :current-page="currentPage"
            @size-change="handlePageSizeChange" @current-change="goToPage" />
        </div>
      </template>
    </div>

    <!-- 新增/编辑知识库对话框 -->
    <knowledge-base-dialog ref="knowledgeBaseDialog" :title="dialogTitle" :visible.sync="dialogVisible" :form="knowledgeBaseForm"
      @submit="handleSubmit" @cancel="dialogVisible = false" />
  </div>
</template>

<script>
import Api from "@/apis/api";
import KnowledgeBaseDialog from "@/components/KnowledgeBaseDialog.vue";

export default {
  components: { KnowledgeBaseDialog },
  data() {
    return {
      searchName: "",
      activeSearchName: "",
      loadFailed: false,
      knowledgeBaseList: [],
      currentPage: 1,
      loading: false,
      pageSize: 10,
      pageSizeOptions: [10, 20, 50, 100],
      total: 0,
      dialogVisible: false,
      dialogTitle: "",
      selectedKnowledgeBase: [],
      isAllSelected: false,
      knowledgeBaseForm: {
        id: null,
        datasetId: null,
        name: "",
        description: "",
        status: 1
      }
    };
  },
  created() {
    this.fetchKnowledgeBaseList();
  },
  computed: {
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
  },
  methods: {
    handlePageSizeChange: function(val) {
      this.pageSize = val;
      this.currentPage = 1;
      this.fetchKnowledgeBaseList();
    },
    fetchKnowledgeBaseList: function() {
      this.loading = true;
      this.loadFailed = false;
      Api.knowledgeBase.getKnowledgeBaseList(
        {
          page: this.currentPage,
          page_size: this.pageSize,
          name: this.searchName,
        },
        (res) => {
          this.loading = false;
          console.log('getKnowledgeBaseList response:', res); // 添加调试日志
          
          // 修复：从 res.data 获取分页数据，而不是 res.data.data
          // 因为 knowledgeBase.js 直接传递了整个响应对象
          if (res.data && res.data.code === 0) {
            const pageData = res.data.data || {};
            this.knowledgeBaseList = pageData.list || [];
            this.total = pageData.total || 0;
            // 删除最后一页的最后一条后回到上一页
            if (!this.knowledgeBaseList.length && this.total > 0 && this.currentPage > 1) {
              this.currentPage = Math.max(1, Math.ceil(this.total / this.pageSize));
              this.fetchKnowledgeBaseList();
              return;
            }
            this.activeSearchName = this.searchName;
            console.log('Updated knowledgeBaseList:', this.knowledgeBaseList); // 添加调试日志
          } else {
            this.loadFailed = true;
            this.$message.error({
              message: res.data?.msg || this.$t('knowledgeBaseManagement.getKnowledgeBaseListFailed'),
              showClose: true
            });
          }
        },
        () => {
          this.loading = false;
          this.loadFailed = true;
          this.$message.error(this.$t('knowledgeBaseManagement.getKnowledgeBaseListFailed'));
        }
      );
    },
    handleSearch: function() {
      this.currentPage = 1;
      this.fetchKnowledgeBaseList();
    },
    handleSelectionChange: function(val) {
      this.selectedKnowledgeBase = val;
    },
    toggleSelectAll: function() {
      if (this.isAllSelected) {
        // 取消全选
        this.$refs.paramsTable.clearSelection();
        this.isAllSelected = false;
      } else {
        // 全选
        this.knowledgeBaseList.forEach(row => {
          this.$refs.paramsTable.toggleRowSelection(row, true);
        });
        this.isAllSelected = true;
      }
    },
    headerCellClassName: function({ row, column, rowIndex, columnIndex }) {
      if (columnIndex === 0) {
        return 'header-cell-first';
      }
      return 'header-cell';
    },
    showAddDialog: function() {
      console.log('showAddDialog called');
      this.dialogTitle = this.$t('knowledgeBaseManagement.addKnowledgeBase');
      this.knowledgeBaseForm = {
        id: null,
        datasetId: null,
        name: "",
        description: "",
        status: 1
      };
      this.dialogVisible = true;
      console.log('dialogVisible set to:', this.dialogVisible);
    },
    showViewDialog: function(row) {
      // 跳转到上传文件页面，传递知识库ID和名称
      this.$router.push({
        path: '/knowledge-file-upload',
        query: {
          datasetId: row.datasetId,
          knowledgeBaseName: row.name
        }
      });
    },
    showEditDialog: function(row) {
      this.dialogTitle = this.$t('knowledgeBaseManagement.editKnowledgeBase');
      this.knowledgeBaseForm = {
        id: row.id,
        datasetId: row.datasetId,
        name: row.name,
        description: row.description || "",
        status: row.status,
        ragModelId: row.ragModelId || null
      };
      this.dialogVisible = true;
    },
    handleSubmit: function(form) {
      console.log('handleSubmit called with form:', form);
      if (form.id) {
        console.log('Editing knowledge base:', form.datasetId);
        Api.knowledgeBase.updateKnowledgeBase(form.datasetId, form, (res) => {
          console.log('Update response:', res);
          if (res.data && res.data.code === 0) {
            this.dialogVisible = false;
            this.fetchKnowledgeBaseList();
            this.$message.success(this.$t('knowledgeBaseManagement.updateSuccess'));
          } else {
            this.$message.error(res.data?.msg || this.$t('knowledgeBaseManagement.updateFailed'));
          }
        }, (err) => {
          console.log('Error callback received:', err);
          // 错误回调处理后端返回的错误信息
          if (err && err.data) {
            console.log('后端返回错误消息:', err.data.msg || err.msg);
            this.$message.error(err.data.msg || err.msg || this.$t('knowledgeBaseManagement.updateFailed'));
          } else {
            this.$message.error(this.$t('knowledgeBaseManagement.updateFailed'));
          }
        });
      } else {
        // 新增 - 只传递必要的字段，不传递id
        const createData = {
          name: form.name,
          description: form.description,
          status: form.status,
          ragModelId: form.ragModelId
        };
        console.log('Creating knowledge base with data:', createData);
        Api.knowledgeBase.createKnowledgeBase(createData, (res) => {
          console.log('Create response:', res);
          if (res.data && res.data.code === 0) {
            this.dialogVisible = false;
            this.fetchKnowledgeBaseList();
            this.$message.success(this.$t('knowledgeBaseManagement.addSuccess'));
          } else {
            this.$message.error(res.data?.msg || this.$t('knowledgeBaseManagement.addFailed'));
          }
        }, (err) => {
          console.log('Error callback received:', err);
          // 错误回调处理后端返回的错误信息
          if (err && err.data) {
            console.log('后端返回错误消息:', err.data.msg || err.msg);
            this.$message.error(err.data.msg || err.msg || this.$t('knowledgeBaseManagement.addFailed'));
          } else {
            this.$message.error(this.$t('knowledgeBaseManagement.addFailed'));
          }
        });
      }
    },
    deleteSelectedKnowledgeBase: function() {
      if (this.selectedKnowledgeBase.length === 0) {
        this.$message.warning(this.$t('knowledgeBaseManagement.selectKnowledgeBaseFirst'));
        return;
      }

      this.$confirm(
        this.$t('knowledgeBaseManagement.confirmBatchDelete', { count: this.selectedKnowledgeBase.length }),
        this.$t('common.warning'),
        {
          confirmButtonText: this.$t('common.confirm'),
          cancelButtonText: this.$t('common.cancel'),
          type: 'warning'
        }).then(() => {
        const ids = this.selectedKnowledgeBase.map(item => item.datasetId).join(',');
        Api.knowledgeBase.deleteKnowledgeBases(ids, (res) => {
          if (res.data && res.data.code === 0) {
            this.fetchKnowledgeBaseList();
            this.$message.success(this.$t('knowledgeBaseManagement.batchDeleteSuccess', { count: this.selectedKnowledgeBase.length }));
          } else {
            this.$message.error(res.data?.msg || this.$t('knowledgeBaseManagement.deleteFailed'));
          }
        }, (err) => {
          console.log('Error callback received:', err);
          // 错误回调处理后端返回的错误信息
          if (err && err.data) {
            console.log('后端返回错误消息:', err.data.msg || err.msg);
            this.$message.error(err.data.msg || err.msg || this.$t('knowledgeBaseManagement.deleteFailed'));
          } else {
            this.$message.error(this.$t('knowledgeBaseManagement.deleteFailed'));
          }
        });
      }).catch(() => {
        this.$message({
          type: 'info',
          message: this.$t('knowledgeBaseManagement.operationCancelled'),
          duration: 1000
        });
      });
    },
    deleteSingleKnowledgeBase: function(row) {
      this.$confirm(
        this.$t('knowledgeBaseManagement.confirmBatchDelete', { count: 1 }),
        this.$t('common.warning'),
        {
          confirmButtonText: this.$t('common.confirm'),
          cancelButtonText: this.$t('common.cancel'),
          type: 'warning'
        }).then(() => {
        Api.knowledgeBase.deleteKnowledgeBase(row.datasetId, (res) => {
          if (res.data && res.data.code === 0) {
            this.fetchKnowledgeBaseList();
            this.$message.success(this.$t('knowledgeBaseManagement.batchDeleteSuccess', { count: 1 }));
          } else {
            this.$message.error(res.data?.msg || this.$t('knowledgeBaseManagement.deleteFailed'));
          }
        }, (err) => {
          console.log('Error callback received:', err);
          // 错误回调处理后端返回的错误信息
          if (err && err.data) {
            console.log('后端返回错误消息:', err.data.msg || err.msg);
            this.$message.error(err.data.msg || err.msg || this.$t('knowledgeBaseManagement.deleteFailed'));
          } else {
            this.$message.error(this.$t('knowledgeBaseManagement.deleteFailed'));
          }
        });
      }).catch(() => {
        this.$message({
          type: 'info',
          message: this.$t('knowledgeBaseManagement.operationCancelled'),
          duration: 1000
        });
      });
    },
    handleStatusChange: function(row) {
      // 只传递需要更新的字段，确保包含id字段
      const updateForm = {
        id: row.id, // 添加id字段，后端需要此字段来定位记录
        datasetId: row.datasetId,
        name: row.name,
        description: row.description,
        status: row.status
      };
      console.log('Updating knowledge base status:', updateForm); // 添加调试日志
      Api.knowledgeBase.updateKnowledgeBase(row.datasetId, updateForm, (res) => {
        console.log('Status update response:', res); // 添加调试日志
        if (res.data && res.data.code !== 0) {
          // 恢复原来的状态
          this.fetchKnowledgeBaseList();
          this.$message.error(res.data?.msg || this.$t('knowledgeBaseManagement.updateFailed'));
        } else {
          // 更新成功，显示成功消息
          this.$message.success(this.$t('knowledgeBaseManagement.updateSuccess'));
        }
      }, () => {
        // 恢复原来的状态
        this.fetchKnowledgeBaseList();
        this.$message.error(this.$t('knowledgeBaseManagement.updateFailed'));
      });
    },
    goToPage: function(page) {
      if (page !== this.currentPage) {
        this.currentPage = page;
        this.fetchKnowledgeBaseList();
      }
    },
    goFirst: function() {
      if (this.currentPage !== 1) {
        this.currentPage = 1;
        this.fetchKnowledgeBaseList();
      }
    },
    goPrev: function() {
      if (this.currentPage > 1) {
        this.currentPage--;
        this.fetchKnowledgeBaseList();
      }
    },
    goNext: function() {
      if (this.currentPage < this.pageCount) {
        this.currentPage++;
        this.fetchKnowledgeBaseList();
      }
    },
    formatDate: function(dateString) {
      if (!dateString) return '';
      const date = new Date(dateString);
      return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
    }
  }
};
</script>

<style scoped>
.kb-search-icon { height: 100%; margin: 0 2px 0 4px; font-size: 16px; color: var(--xn-ink-3); }
.kb-panel { overflow: hidden; }
.kb-name {
  display: inline-flex; align-items: center; gap: 8px; max-width: 100%; padding: 2px 0; border: 0; background: none;
  color: var(--xn-ink); font: inherit; font-weight: 600; text-align: left; cursor: pointer;
}
.kb-name:hover { color: var(--xn-lake); }
.kb-name__icon { font-size: 16px; color: var(--xn-ink-3); }
.kb-name:hover .kb-name__icon { color: var(--xn-lake); }
.kb-status { display: inline-flex; align-items: center; gap: 8px; }
.kb-status__text { font-size: 13px; }
.kb-panel ::v-deep .kb-nowrap .cell { white-space: nowrap; }
.kb-danger { color: var(--xn-danger); }
.kb-danger:hover, .kb-danger:focus { color: #8D3523; }
.kb-foot { display: flex; justify-content: flex-end; padding: 4px 16px 14px; border-top: 1px solid var(--xn-line-2); }
</style>
