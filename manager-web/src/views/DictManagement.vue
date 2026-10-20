<template>
  <div class="xn-page">
    <page-header :title="$t('dictManagement.pageTitle')" :description="$t('xn.admin.dict.desc')" />

    <div v-if="typeLoadFailed && !dictTypeLoading" class="xn-panel">
      <xn-empty error @retry="loadDictTypeList" />
    </div>

    <div v-else class="dm-layout">
      <!-- 左侧：字典类型 -->
      <section class="xn-panel dm-types">
        <header class="xn-panel__head">
          <h2 class="xn-panel__title">{{ $t('xn.admin.dict.types') }}</h2>
          <div class="dm-head-actions">
            <el-button v-if="selectedDictTypes.length" type="danger" plain size="small" @click="batchDeleteDictType">
              <xn-icon name="trash" /> {{ $t('xn.admin.dict.deleteTypes', { n: selectedDictTypes.length }) }}
            </el-button>
            <el-button size="small" @click="showAddDictTypeDialog"><xn-icon name="plus" /> {{ $t('xn.admin.dict.addType') }}</el-button>
          </div>
        </header>
        <el-table ref="dictTypeTable" :data="dictTypeList" v-loading="dictTypeLoading" row-key="id" highlight-current-row
          @row-click="handleDictTypeRowClick" @selection-change="handleDictTypeSelectionChange" :row-class-name="tableRowClassName"
          class="dm-type-table">
          <el-table-column type="selection" width="44" align="center" />
          <el-table-column :label="$t('dictManagement.dictTypeName')" min-width="150">
            <template slot-scope="{ row }">
              <div class="dm-type-name">{{ row.dictName }}</div>
              <div class="dm-type-code">{{ row.dictType }}</div>
            </template>
          </el-table-column>
          <el-table-column width="64" align="right">
            <template slot-scope="scope">
              <el-button type="text" @click.stop="editDictType(scope.row)">{{ $t('dictManagement.edit') }}</el-button>
            </template>
          </el-table-column>
          <template slot="empty">
            <xn-empty icon="list" :title="$t('xn.admin.dict.noTypes')" :description="$t('xn.admin.dict.noTypesDesc')" />
          </template>
        </el-table>
      </section>

      <!-- 右侧：字典数据 -->
      <section class="xn-panel dm-data">
        <header class="xn-panel__head">
          <div class="dm-data-title">
            <h2 class="xn-panel__title">{{ selectedDictType ? selectedDictType.dictName : $t('xn.admin.dict.data') }}</h2>
            <span v-if="selectedDictType" class="xn-tag xn-tag--muted">{{ selectedDictType.dictType }}</span>
          </div>
          <el-button type="primary" size="small" :disabled="!selectedDictType" @click="showAddDictDataDialog">
            <xn-icon name="plus" /> {{ $t('dictManagement.addDictData') }}
          </el-button>
        </header>
        <div class="xn-toolbar xn-toolbar--inline dm-data-toolbar">
          <el-input :placeholder="$t('dictManagement.searchPlaceholder')" v-model="search" clearable :disabled="!selectedDictType"
            @keyup.enter.native="handleSearch" @clear="handleSearch">
            <xn-icon slot="prefix" name="search" class="xa-search-icon" />
          </el-input>
          <el-button :disabled="!selectedDictType" @click="handleSearch">{{ $t('dictManagement.search') }}</el-button>
          <span class="xn-toolbar__grow"></span>
          <template v-if="selectedDataCount">
            <span class="xn-muted">{{ $t('xn.admin.selected', { n: selectedDataCount }) }}</span>
            <el-button type="danger" plain size="small" @click="batchDeleteDictData"><xn-icon name="trash" /> {{ $t('xn.admin.deleteSelected') }}</el-button>
          </template>
        </div>

        <xn-empty v-if="dataLoadFailed && !dictDataLoading" error @retry="loadDictDataList(selectedDictType && selectedDictType.id)" />
        <template v-else>
          <el-table ref="dictDataTable" :data="dictDataList" v-loading="dictDataLoading" row-key="id">
            <el-table-column width="52" align="center">
              <template slot="header">
                <el-checkbox :value="isAllDictDataSelected" :indeterminate="selectedDataCount > 0 && !isAllDictDataSelected"
                  :disabled="!dictDataList.length" :aria-label="$t('dictManagement.selectAll')" @change="selectAllDictData" />
              </template>
              <template slot-scope="scope"><el-checkbox v-model="scope.row.selected" /></template>
            </el-table-column>
            <el-table-column :label="$t('dictManagement.dictLabel')" prop="dictLabel" min-width="160" />
            <el-table-column :label="$t('dictManagement.dictValue')" min-width="160">
              <template slot-scope="{ row }"><span class="xa-code">{{ row.dictValue }}</span></template>
            </el-table-column>
            <el-table-column :label="$t('dictManagement.sort')" prop="sort" width="80" align="right" class-name="xn-num" />
            <el-table-column :label="$t('dictManagement.operation')" width="130" align="right">
              <template slot-scope="scope">
                <el-button type="text" @click="editDictData(scope.row)">{{ $t('dictManagement.edit') }}</el-button>
                <el-button type="text" class="xa-danger" @click="deleteDictData(scope.row)">{{ $t('dictManagement.delete') }}</el-button>
              </template>
            </el-table-column>
            <template slot="empty">
              <xn-empty v-if="!selectedDictType" icon="list" :title="$t('dictManagement.selectDictTypeFirst')" />
              <xn-empty v-else-if="lastSearch" icon="search" :title="$t('xn.admin.dict.noMatch')" :description="$t('xn.admin.noMatchDesc')" />
              <xn-empty v-else icon="list" :title="$t('xn.admin.dict.noData')" :description="$t('xn.admin.dict.noDataDesc')">
                <el-button type="primary" @click="showAddDictDataDialog"><xn-icon name="plus" /> {{ $t('dictManagement.addDictData') }}</el-button>
              </xn-empty>
            </template>
          </el-table>
          <div v-if="total" class="xa-foot">
            <el-pagination background layout="total, sizes, prev, pager, next" :total="total" :page-size="pageSize"
              :page-sizes="pageSizeOptions" :current-page="currentPage" @size-change="handlePageSizeChange" @current-change="goToPage" />
          </div>
        </template>
      </section>
    </div>

    <!-- 使用字典类型编辑弹框组件 -->
    <DictTypeDialog :visible.sync="dictTypeDialogVisible" :title="dictTypeDialogTitle" :dictTypeData="dictTypeForm"
      @save="saveDictType" />
    <!-- 使用字典数据编辑弹框组件 -->
    <DictDataDialog :visible.sync="dictDataDialogVisible" :title="dictDataDialogTitle" :dictData="dictDataForm"
      :dictTypeId="selectedDictType ? selectedDictType.id : null" @save="saveDictData" />
  </div>
</template>

<script>
import dictApi from '@/apis/module/dict'
import DictDataDialog from '@/components/DictDataDialog.vue'
import DictTypeDialog from '@/components/DictTypeDialog.vue'

export default {
  name: 'DictManagement',
  components: {
    DictTypeDialog,
    DictDataDialog,
  },
  data() {
    return {
      // 字典类型相关
      dictTypeList: [],
      dictTypeLoading: false,
      typeLoadFailed: false,
      selectedDictType: null,
      selectedDictTypes: [],  // 恢复多选数组
      dictTypeDialogVisible: false,
      dictTypeDialogTitle: '新增字典类型',
      dictTypeForm: {
        id: null,
        dictName: '',
        dictType: ''
      },
      // 字典数据相关
      dictDataList: [],
      dictDataLoading: false,
      dataLoadFailed: false,
      dictDataDialogVisible: false,
      dictDataDialogTitle: '新增字典数据',
      dictDataForm: {
        id: null,
        dictTypeId: null,
        dictLabel: '',
        dictValue: '',
        sort: 0
      },
      search: '',
      lastSearch: '',
      // 添加分页相关数据
      pageSizeOptions: [10, 20, 50, 100],
      currentPage: 1,
      pageSize: 10,
      total: 0
    }
  },
  created() {
    this.loadDictTypeList()
  },
  beforeDestroy() {
    clearTimeout(this._typeTimer)
    clearTimeout(this._dataTimer)
  },
  computed: {
    pageCount() {
      return Math.ceil(this.total / this.pageSize);
    },
    selectedDataCount() {
      return this.dictDataList.filter((d) => d.selected).length
    },
    isAllDictDataSelected() {
      return this.dictDataList.length > 0 && this.dictDataList.every((d) => d.selected)
    },
  },
  methods: {
    // 业务错误由请求层统一提示且不回调；超过 8 秒仍无结果时显示失败状态
    watchdog(timerKey, loadingKey, failedKey) {
      clearTimeout(this[timerKey])
      this[timerKey] = setTimeout(() => {
        if (this[loadingKey]) { this[loadingKey] = false; this[failedKey] = true }
      }, 8000)
    },
    // 字典类型相关方法
    loadDictTypeList() {
      this.dictTypeLoading = true
      this.typeLoadFailed = false
      this.watchdog('_typeTimer', 'dictTypeLoading', 'typeLoadFailed')
      const keepId = this.selectedDictType && this.selectedDictType.id
      dictApi.getDictTypeList({
        page: 1,
        limit: 100,
        // 原页面把右侧“字典标签”搜索词也传给了类型列表，导致搜索后新增类型时左侧列表被过滤为空；这里类型列表不再按标签过滤
        dictName: ''
      }, ({ data }) => {
        clearTimeout(this._typeTimer)
        if (data.code === 0) {
          this.dictTypeList = data.data.list
          if (this.dictTypeList.length > 0) {
            // 刷新后保留当前选中的类型（不存在时选第一个）
            const target = this.dictTypeList.find((t) => t.id === keepId) || this.dictTypeList[0]
            this.selectedDictType = target
            this.loadDictDataList(target.id)
            this.$nextTick(() => {
              this.$refs.dictTypeTable && this.$refs.dictTypeTable.setCurrentRow(target)
            })
          } else {
            this.selectedDictType = null
            this.dictDataList = []
            this.total = 0
          }
        } else {
          this.typeLoadFailed = true
        }
        this.dictTypeLoading = false
      })
    },
    handleDictTypeRowClick(row) {
      if (this.selectedDictType && this.selectedDictType.id !== row.id) {
        this.currentPage = 1
        this.search = ''
      }
      this.selectedDictType = row
      this.loadDictDataList(row.id)
      this.$refs.dictTypeTable.setCurrentRow(row)
    },
    handleDictTypeSelectionChange(val) {
      this.selectedDictTypes = val
    },
    tableRowClassName({ row }) {
      return row === this.selectedDictType ? 'current-row' : ''
    },
    showAddDictTypeDialog() {
      this.dictTypeDialogTitle = this.$t('dictManagement.addDictType')
      this.dictTypeForm = {
        id: null,
        dictName: '',
        dictType: ''
      }
      this.dictTypeDialogVisible = true
    },
    editDictType(row) {
      this.dictTypeDialogTitle = this.$t('dictManagement.editDictType')
      this.dictTypeForm = { ...row }
      this.dictTypeDialogVisible = true
    },
    saveDictType(formData) {
      const api = formData.id ? dictApi.updateDictType : dictApi.addDictType
      api(formData, ({ data }) => {
        if (data.code === 0) {
          this.$message.success(this.$t('dictManagement.saveSuccess'))
          this.dictTypeDialogVisible = false
          this.loadDictTypeList()
        }
      })
    },
    batchDeleteDictType() {
      if (this.selectedDictTypes.length === 0) {
        this.$message.warning(this.$t('dictManagement.selectDictTypeToDelete'))
        return
      }
      this.$confirm(this.$t('xn.admin.dict.confirmDeleteTypes', { n: this.selectedDictTypes.length }), this.$t('xn.admin.dict.deleteTypeTitle'), {
        confirmButtonText: this.$t('dictManagement.delete'),
        cancelButtonText: this.$t('dictManagement.cancel'),
        type: 'warning'
      }).then(() => {
        const ids = this.selectedDictTypes.map(item => item.id)
        dictApi.deleteDictType(ids, ({ data }) => {
          if (data.code === 0) {
            this.$message.success(this.$t('dictManagement.deleteSuccess'))
            this.selectedDictTypes = []
            this.loadDictTypeList()
          }
        })
      }).catch(() => {})
    },
    // 字典数据相关方法
    loadDictDataList(dictTypeId) {
      if (!dictTypeId) return
      this.dictDataLoading = true
      this.dataLoadFailed = false
      this.watchdog('_dataTimer', 'dictDataLoading', 'dataLoadFailed')
      const keyword = this.search
      dictApi.getDictDataList({
        dictTypeId,
        page: this.currentPage,
        limit: this.pageSize,
        dictLabel: keyword,
        dictValue: ''
      }, ({ data }) => {
        clearTimeout(this._dataTimer)
        if (data.code === 0) {
          this.lastSearch = keyword
          this.dictDataList = data.data.list.map(item => ({
            ...item,
            selected: false
          }))
          this.total = data.data.total
          // 删除最后一页的全部数据后回到上一页
          if (!this.dictDataList.length && this.currentPage > 1 && this.total) {
            this.currentPage = Math.max(1, this.pageCount)
            this.loadDictDataList(dictTypeId)
          }
        } else {
          this.dataLoadFailed = true
          this.$message.error(data.msg || this.$t('dictManagement.getDictDataFailed'))
        }
        this.dictDataLoading = false
      })
    },
    selectAllDictData() {
      const next = !this.isAllDictDataSelected
      this.dictDataList.forEach(row => {
        row.selected = next
      })
    },
    showAddDictDataDialog() {
      if (!this.selectedDictType) {
        this.$message.warning(this.$t('dictManagement.selectDictTypeFirst'))
        return
      }
      this.dictDataDialogTitle = this.$t('dictManagement.addDictData')
      this.dictDataForm = {
        id: null,
        dictTypeId: this.selectedDictType.id,
        dictLabel: '',
        dictValue: '',
        sort: 0
      }
      this.dictDataDialogVisible = true
    },
    editDictData(row) {
      this.dictDataDialogTitle = this.$t('dictManagement.editDictData')
      const { selected, ...rest } = row
      this.dictDataForm = { ...rest }
      this.dictDataDialogVisible = true
    },
    saveDictData(formData) {
      const api = formData.id ? dictApi.updateDictData : dictApi.addDictData
      api(formData, ({ data }) => {
        if (data.code === 0) {
          this.$message.success(this.$t('dictManagement.saveSuccess'))
          this.dictDataDialogVisible = false
          this.loadDictDataList(formData.dictTypeId)
        }
      })
    },
    deleteDictData(row) {
      this.$confirm(this.$t('dictManagement.confirmDeleteDictData'), this.$t('xn.admin.dict.deleteDataTitle'), {
        confirmButtonText: this.$t('dictManagement.delete'),
        cancelButtonText: this.$t('dictManagement.cancel'),
        type: 'warning'
      }).then(() => {
        dictApi.deleteDictData([row.id], ({ data }) => {
          if (data.code === 0) {
            this.$message.success(this.$t('dictManagement.deleteSuccess'))
            this.loadDictDataList(row.dictTypeId)
          }
        })
      }).catch(() => {})
    },
    batchDeleteDictData() {
      const selectedRows = this.dictDataList.filter(row => row.selected)
      if (selectedRows.length === 0) {
        this.$message.warning(this.$t('dictManagement.selectDictDataToDelete'))
        return
      }
      this.$confirm(this.$t('dictManagement.confirmBatchDeleteDictData', { count: selectedRows.length }), this.$t('xn.admin.dict.deleteDataTitle'), {
        confirmButtonText: this.$t('dictManagement.delete'),
        cancelButtonText: this.$t('dictManagement.cancel'),
        type: 'warning'
      }).then(() => {
        const ids = selectedRows.map(item => item.id)
        dictApi.deleteDictData(ids, ({ data }) => {
          if (data.code === 0) {
            this.$message.success(this.$t('dictManagement.deleteSuccess'))
            this.loadDictDataList(this.selectedDictType.id)
          }
        })
      }).catch(() => {})
    },
    handleSearch() {
      if (!this.selectedDictType) {
        this.$message.warning(this.$t('dictManagement.selectDictTypeFirst'))
        return
      }
      this.currentPage = 1
      this.loadDictDataList(this.selectedDictType.id)
    },
    // 添加分页相关方法
    handlePageSizeChange(val) {
      this.pageSize = val;
      this.currentPage = 1;
      this.loadDictDataList(this.selectedDictType && this.selectedDictType.id);
    },
    goToPage(page) {
      this.currentPage = page;
      this.loadDictDataList(this.selectedDictType && this.selectedDictType.id);
    },
  },
}
</script>

<style scoped>
.dm-layout { display: grid; grid-template-columns: minmax(260px, 320px) minmax(0, 1fr); gap: 16px; align-items: start; }
.dm-layout .xn-panel + .xn-panel { margin-top: 0; }
.dm-types, .dm-data { overflow: hidden; min-width: 0; }
.dm-head-actions { display: flex; align-items: center; gap: 8px; }
.dm-head-actions .el-button + .el-button { margin-left: 0; }
.dm-type-table ::v-deep .el-table__row { cursor: pointer; }
.dm-type-table ::v-deep .el-table__body tr.current-row > td.el-table__cell { background: var(--xn-lake-soft); }
.dm-type-name { font-weight: 500; color: var(--xn-ink); }
.dm-type-code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; color: var(--xn-ink-3); word-break: break-all; }
.dm-data-title { display: flex; align-items: center; gap: 10px; min-width: 0; }
.dm-data-toolbar { margin: 0; padding: 12px 16px; border-bottom: 1px solid var(--xn-line-2); border-radius: 0; }
.xa-search-icon { height: 100%; margin: 0 2px 0 4px; font-size: 16px; color: var(--xn-ink-3); }
.xa-code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; word-break: break-all; }
.xa-danger { color: var(--xn-danger); }
.xa-danger:hover, .xa-danger:focus { color: #8D3523; }
.xa-foot { display: flex; justify-content: flex-end; padding: 4px 16px 14px; border-top: 1px solid var(--xn-line-2); }
@media (max-width: 1100px) {
  .dm-layout { grid-template-columns: minmax(0, 1fr); }
}
</style>
