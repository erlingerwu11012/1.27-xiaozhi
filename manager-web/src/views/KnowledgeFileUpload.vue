<template>
  <div class="xn-page">
    <page-header :back="'/knowledge-base-management'" :back-label="$t('knowledgeBaseManagement.title')"
      :title="knowledgeBaseName || $t('xn.nav.knowledgeUpload')" :description="$t('xn.knowledge.docsDesc')">
      <template v-if="datasetId">
        <el-button @click="showRetrievalTestDialog"><xn-icon name="flask" /> {{ $t('knowledgeFileUpload.retrievalTest') }}</el-button>
        <el-button type="primary" @click="showUploadDialog"><xn-icon name="upload" /> {{ $t('knowledgeFileUpload.uploadDocument') }}</el-button>
      </template>
    </page-header>

    <div v-if="!datasetId" class="xn-panel">
      <xn-empty icon="book" :title="$t('xn.knowledge.noDatasetTitle')" :description="$t('xn.knowledge.noDatasetDesc')">
        <el-button type="primary" @click="goBack">{{ $t('xn.knowledge.backToList') }}</el-button>
      </xn-empty>
    </div>

    <template v-else>
      <div class="xn-toolbar">
        <el-input v-model="searchName" :placeholder="$t('knowledgeFileUpload.searchPlaceholder')" clearable
          @keyup.enter.native="handleSearch" @clear="handleSearch">
          <xn-icon slot="prefix" name="search" class="kf-search-icon" />
        </el-input>
        <el-button @click="handleSearch">{{ $t('knowledgeFileUpload.search') }}</el-button>
        <span class="xn-toolbar__grow"></span>
        <template v-if="selectedFiles.length">
          <span class="xn-muted">{{ $t('xn.knowledge.selectedDocs', { n: selectedFiles.length }) }}</span>
          <el-button type="danger" plain size="small" @click="handleBatchDelete"><xn-icon name="trash" /> {{ $t('xn.knowledge.deleteSelected') }}</el-button>
        </template>
      </div>

      <div class="xn-panel xn-panel--flush kf-panel">
        <xn-empty v-if="loadFailed && !loading" error @retry="fetchFileList" />
        <template v-else>
          <el-table ref="fileTable" :data="fileList" v-loading="loading" row-key="id" @selection-change="handleSelectionChange">
            <el-table-column type="selection" width="52" align="center"></el-table-column>
            <el-table-column :label="$t('knowledgeFileUpload.documentName')" min-width="260">
              <template slot-scope="scope">
                <span class="kf-doc">
                  <span class="kf-doc__ext">{{ fileExt(scope.row.name) }}</span>
                  <span class="kf-doc__name xn-clip" :title="scope.row.name">{{ scope.row.name }}</span>
                </span>
              </template>
            </el-table-column>
            <el-table-column :label="$t('knowledgeFileUpload.uploadTime')" width="160" class-name="kf-nowrap">
              <template slot-scope="scope"><span class="xn-num">{{ formatDate(scope.row.createdAt) }}</span></template>
            </el-table-column>
            <el-table-column :label="$t('knowledgeFileUpload.status')" width="120">
              <template slot-scope="scope">
                <span class="xn-tag" :class="statusTagClass(scope.row.parseStatusCode)">
                  <i v-if="scope.row.parseStatusCode === 1" class="dot kf-pulse"></i>{{ getParseStatusText(scope.row.parseStatusCode) }}
                </span>
              </template>
            </el-table-column>
            <el-table-column :label="$t('knowledgeFileUpload.sliceCount')" width="100" align="right">
              <template slot-scope="scope"><span class="xn-num">{{ scope.row.sliceCount || 0 }}</span></template>
            </el-table-column>
            <el-table-column :label="$t('knowledgeFileUpload.operation')" width="170" align="right">
              <template slot-scope="scope">
                <el-button type="text" @click="handleParse(scope.row)"
                  :disabled="scope.row.parseStatusCode === 1 || scope.row.parseStatusCode === 3 || scope.row.parseStatusCode === 4" v-if="!scope.row.sliceCount || scope.row.sliceCount <= 0">
                  {{ $t('knowledgeFileUpload.parse') }}
                </el-button>
                <el-button type="text" @click="handleViewSlices(scope.row)" v-if="scope.row.sliceCount && scope.row.sliceCount > 0">
                  {{ $t('knowledgeFileUpload.viewSlices') }}
                </el-button>
                <el-button type="text" class="kf-danger" @click="handleDelete(scope.row)">{{ $t('knowledgeFileUpload.delete') }}</el-button>
              </template>
            </el-table-column>
            <template slot="empty">
              <xn-empty v-if="searchName && total === 0" icon="search" :title="$t('xn.knowledge.docNoMatch')" />
              <xn-empty v-else icon="upload" :title="$t('xn.knowledge.docEmptyTitle')" :description="$t('xn.knowledge.docEmptyDesc')">
                <el-button type="primary" @click="showUploadDialog"><xn-icon name="upload" /> {{ $t('knowledgeFileUpload.uploadDocument') }}</el-button>
              </xn-empty>
            </template>
          </el-table>
          <div v-if="total > 0" class="kf-foot">
            <span class="xn-muted kf-note"><xn-icon name="info" /> {{ $t('xn.knowledge.parseNote') }}</span>
            <el-pagination background layout="total, sizes, prev, pager, next" :total="total"
              :page-size="pageSize" :page-sizes="pageSizeOptions" :current-page="currentPage"
              @size-change="handlePageSizeChange" @current-change="goToPage" />
          </div>
        </template>
      </div>
    </template>

    <!-- 上传文档 -->
    <el-dialog :title="$t('knowledgeFileUpload.uploadDocument')" :visible.sync="uploadDialogVisible" width="640px" append-to-body>
      <p v-if="isMock" class="kf-mock-note"><demo-tag /> {{ $t('xn.knowledge.uploadMockNote') }}</p>
      <el-upload class="kf-uploader" drag :action="uploadUrl" :auto-upload="false" :on-change="handleFileChange"
        :multiple="true" :show-file-list="false" accept=".doc,.docx,.pdf,.txt,.md,.mdx,.csv,.xls,.xlsx,.ppt,.pptx">
        <xn-icon name="upload" class="kf-uploader__icon" />
        <div class="el-upload__text">{{ $t('knowledgeFileUpload.dragOrClick') }}</div>
        <div class="kf-uploader__tip">{{ $t('knowledgeFileUpload.uploadTip') }}</div>
      </el-upload>

      <div v-if="selectedFilesList.length > 0" class="kf-picked">
        <p class="kf-picked__title">{{ $t('knowledgeFileUpload.selectedFiles') }}<span class="xn-num xn-muted">（{{ selectedFilesList.length }}）</span></p>
        <ul class="kf-picked__list">
          <li v-for="(file, index) in selectedFilesList" :key="index" class="kf-picked__item">
            <span class="kf-doc__ext">{{ fileExt(file.name) }}</span>
            <span class="kf-picked__name xn-clip" :title="file.name">{{ file.name }}</span>
            <span class="kf-picked__size xn-num">{{ formatFileSize(file.size) }}</span>
            <el-button type="text" class="kf-picked__remove" :aria-label="$t('xn.knowledge.removeFile')" @click="removeSelectedFile(index)">
              <xn-icon name="close" />
            </el-button>
          </li>
        </ul>
      </div>

      <div slot="footer">
        <el-button @click="uploadDialogVisible = false">{{ $t('knowledgeFileUpload.cancel') }}</el-button>
        <el-button type="primary" @click="handleBatchUploadSubmit" :loading="uploading" :disabled="selectedFilesList.length === 0">
          {{ selectedFilesList.length ? $t('xn.knowledge.uploadN', { n: selectedFilesList.length }) : $t('xn.knowledge.upload') }}
        </el-button>
      </div>
    </el-dialog>

    <!-- 查看切片 -->
    <el-dialog :title="$t('knowledgeFileUpload.viewSlices')" :visible.sync="sliceDialogVisible" width="820px" top="8vh" append-to-body custom-class="kf-slice-dialog">
      <p class="kf-dialog-sub xn-clip" :title="currentDocumentName">{{ currentDocumentName }}</p>
      <div v-loading="sliceLoading" class="kf-slices">
        <ol v-if="sliceList.length > 0" class="kf-slice-list">
          <li v-for="(slice, index) in sliceList" :key="slice.id || index" class="kf-slice">
            <span class="kf-slice__no xn-num">{{ $t('knowledgeFileUpload.slice') }} {{ (sliceCurrentPage - 1) * slicePageSize + index + 1 }}</span>
            <p class="kf-slice__text">{{ slice.content }}</p>
          </li>
        </ol>
        <xn-empty v-else-if="!sliceLoading" icon="list" :title="$t('knowledgeFileUpload.noSliceData')" />
      </div>
      <div v-if="sliceTotal > 0" class="kf-slice-foot">
        <el-pagination background small layout="total, sizes, prev, pager, next" :total="sliceTotal"
          :page-size="slicePageSize" :page-sizes="pageSizeOptions" :current-page="sliceCurrentPage"
          @size-change="handleSliceSizeChange" @current-change="handleSlicePageChange" />
      </div>
      <div slot="footer">
        <el-button @click="sliceDialogVisible = false">{{ $t('xn.common.close') }}</el-button>
      </div>
    </el-dialog>

    <!-- 召回测试 -->
    <el-dialog :title="$t('knowledgeFileUpload.retrievalTest')" :visible.sync="retrievalTestDialogVisible" width="760px" top="8vh" append-to-body>
      <p class="kf-dialog-sub">{{ $t('xn.knowledge.retrievalHelp') }}</p>
      <el-form :model="retrievalTestForm" label-position="top" @submit.native.prevent>
        <el-form-item :label="$t('knowledgeFileUpload.testQuestion')" required>
          <div class="kf-rt-row">
            <el-input v-model="retrievalTestForm.question" :placeholder="$t('knowledgeFileUpload.testQuestionPlaceholder')"
              maxlength="200" clearable @keyup.enter.native="runRetrievalTest" />
            <el-button type="primary" @click="runRetrievalTest" :loading="retrievalTestLoading">{{ $t('knowledgeFileUpload.runTest') }}</el-button>
          </div>
        </el-form-item>
      </el-form>

      <section v-if="retrievalTestResult" class="kf-rt-result">
        <div class="kf-rt-result__head">
          <h3 class="kf-rt-result__title">{{ $t('xn.knowledge.testResult') }}</h3>
          <demo-tag :text="$t('xn.common.simulated')" />
          <span class="xn-toolbar__grow"></span>
          <span v-if="retrievalTestResult.chunks && retrievalTestResult.chunks.length" class="xn-muted kf-rt-count">{{ $t('xn.knowledge.retrievalCount', { n: retrievalTestResult.chunks.length }) }}</span>
        </div>
        <ol v-if="retrievalTestResult.chunks && retrievalTestResult.chunks.length > 0" class="kf-slice-list">
          <li v-for="(chunk, index) in retrievalTestResult.chunks" :key="chunk.id || index" class="kf-slice">
            <div class="kf-rt-meta">
              <span class="kf-slice__no xn-num">{{ $t('knowledgeFileUpload.slice') }} {{ index + 1 }}</span>
              <span v-if="chunk.document_name || chunk.document_keyword" class="xn-muted xn-clip kf-rt-src">{{ chunk.document_name || chunk.document_keyword }}</span>
              <span class="xn-toolbar__grow"></span>
              <span class="kf-rt-score">{{ $t('knowledgeFileUpload.comprehensiveSimilarity') }} <b class="xn-num">{{ (chunk.similarity || 0).toFixed(4) }}</b></span>
            </div>
            <p class="kf-slice__text">{{ chunk.content }}</p>
          </li>
        </ol>
        <xn-empty v-else icon="search" :title="$t('knowledgeFileUpload.noRelatedSlices')" :description="$t('xn.knowledge.noRelatedDesc')" />
      </section>

      <div slot="footer">
        <el-button @click="retrievalTestDialogVisible = false">{{ $t('xn.common.close') }}</el-button>
      </div>
    </el-dialog>
  </div>
</template>

<script>
import Api from "@/apis/api";
import KnowledgeBaseAPI from "@/apis/module/knowledgeBase";
import { IS_MOCK } from "@/utils/media";

const STATUS_TAG = { info: 'muted', primary: 'lake', warning: 'warning', success: 'success', danger: 'danger' };

export default {
  data() {
    return {
      datasetId: '',
      knowledgeBaseName: '',
      searchName: "",
      fileList: [],
      loadFailed: false,
      isMock: IS_MOCK,
      selectedFiles: [],
      currentPage: 1,
      loading: false,
      pageSize: 10,
      pageSizeOptions: [10, 20, 50, 100],
      total: 0,
      uploadDialogVisible: false,
      uploading: false,
      uploadForm: {
        file: null
      },
      uploadUrl: '',
      isAllSelected: false,
      selectedFilesList: [], // 批量上传选择的文件列表

      // 切片管理相关数据
      sliceDialogVisible: false,
      currentDocumentId: '',
      currentDocumentName: '',
      sliceList: [],
      sliceLoading: false,
      sliceCurrentPage: 1,
      slicePageSize: 10,
      sliceTotal: 0,
      sliceSearchKeyword: '',

      // 召回测试相关数据
      retrievalTestDialogVisible: false,
      retrievalTestForm: {
        question: ''
      },
      retrievalTestResult: null,
      retrievalTestLoading: false,
      
      // 状态轮询相关数据
      statusPollingTimer: null,
      statusPollingInterval: 5000, // 5秒轮询一次
      maxStatusPollingTime: 300000, // 最大轮询时间5分钟
      statusPollingStartTime: null
    };
  },
  created() {
    this.datasetId = this.$route.query.datasetId || '';
    this.knowledgeBaseName = this.$route.query.knowledgeBaseName || '';
    this.uploadUrl = `${Api.getServiceUrl()}/api/v1/documents/upload`;
    // 没有指定知识库时不请求文档列表，页面引导回知识库列表
    if (this.datasetId) this.fetchFileList();
  },
  
  beforeDestroy() {
    this.stopStatusPolling();
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
    // 切片分页页数计算
    slicePageCount() {
      return Math.ceil(this.sliceTotal / this.slicePageSize);
    },
    // 切片分页可见页码计算（最多显示3个页码）
    sliceVisiblePages() {
      const pages = [];
      const maxVisible = 3;
      let start = Math.max(1, this.sliceCurrentPage - 1);
      let end = Math.min(this.slicePageCount, start + maxVisible - 1);

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
    goBack() {
      this.$router.push('/knowledge-base-management');
    },
    fileExt(name) {
      const m = /\.([A-Za-z0-9]+)$/.exec(name || '');
      return m ? m[1].slice(0, 4).toUpperCase() : 'FILE';
    },
    handlePageSizeChange: function (val) {
      this.pageSize = val;
      this.currentPage = 1;
      this.fetchFileList();
    },
    fetchFileList: function () {
      this.loading = true;
      this.loadFailed = false;
      const params = {
        page: this.currentPage,
        page_size: this.pageSize,
        name: this.searchName
      };

      KnowledgeBaseAPI.getDocumentList(this.datasetId, params,
        async ({ data }) => {
          this.loading = false;
          if (data && data.code === 0) {
            this.fileList = data.data.list;
            this.total = data.data.total;
            // 删除最后一页的最后一条后回到上一页
            if (!this.fileList.length && this.total > 0 && this.currentPage > 1) {
              this.currentPage = Math.max(1, Math.ceil(this.total / this.pageSize));
              this.fetchFileList();
              return;
            }

            // 为每个文档获取切片数量
            await this.fetchSliceCountsForDocuments();
            
            // 自动为处理中的文档启动状态检测
            this.startStatusPolling();
          } else {
            this.loadFailed = true;
            this.$message.error(data?.msg || this.$t('knowledgeFileUpload.getListFailed'));
            this.fileList = [];
            this.total = 0;
          }
        },
        (err) => {
          this.loading = false;
          this.loadFailed = true;
          console.log('Error callback received:', err);
          if (err && err.data) {
            console.log('后端返回错误消息:', err.data.msg || err.msg);
            this.$message.error(err.data.msg || err.msg || this.$t('knowledgeFileUpload.getListFailed'));
          } else {
            this.$message.error(this.$t('knowledgeFileUpload.getListFailed'));
          }
          console.error('获取文档列表失败:', err);
          this.fileList = [];
          this.total = 0;
        }
      );
    },
    
    // 启动文档状态轮询
    startStatusPolling: function () {
      // 检查是否已经有轮询在进行
      if (this.statusPollingTimer) {
        console.log('状态轮询已在运行');
        return;
      }
      
      // 检查是否有处理中的文档
      const hasProcessingDocuments = this.fileList.some(document => 
        document.parseStatusCode === 1
      );
      
      if (!hasProcessingDocuments) {
        console.log('没有处理中的文档，不启动状态轮询');
        return;
      }
      
      console.log('启动文档状态轮询');
      this.statusPollingStartTime = Date.now();
      
      // 立即执行一次状态检查
      this.pollDocumentStatus();
      
      // 开始轮询
      this.statusPollingTimer = setInterval(() => {
        this.pollDocumentStatus();
      }, this.statusPollingInterval);
    },
    
    // 停止文档状态轮询
    stopStatusPolling: function () {
      if (this.statusPollingTimer) {
        clearInterval(this.statusPollingTimer);
        this.statusPollingTimer = null;
        console.log('停止文档状态轮询');
      }
    },
    
    // 轮询文档状态
    pollDocumentStatus: async function () {
      // 检查是否超过最大轮询时间
      if (Date.now() - this.statusPollingStartTime > this.maxStatusPollingTime) {
        console.log('达到最大轮询时间，停止状态轮询');
        this.stopStatusPolling();
        return;
      }
      
      try {
        const params = {
          page: this.currentPage,
          page_size: this.pageSize,
          name: this.searchName
        };
        
        const response = await new Promise((resolve, reject) => {
          KnowledgeBaseAPI.getDocumentList(this.datasetId, params,
            ({ data }) => resolve(data),
            (err) => reject(err)
          );
        });
        
        if (response && response.code === 0) {
          const updatedFileList = response.data.list;
          
          // 更新文档状态
          this.updateDocumentStatuses(updatedFileList);
          
          // 检查是否还有处理中的文档
          const hasProcessingDocuments = updatedFileList.some(document => 
            document.parseStatusCode === 1
          );
          
          if (!hasProcessingDocuments) {
            console.log('所有文档处理完成，停止状态轮询');
            this.stopStatusPolling();
          }
        }
      } catch (error) {
        console.warn('轮询文档状态失败:', error);
      }
    },
    
    // 更新文档状态
    updateDocumentStatuses: function (updatedFileList) {
      let hasChanges = false;
      
      updatedFileList.forEach(updatedDoc => {
        const existingDoc = this.fileList.find(doc => doc.id === updatedDoc.id);
        if (existingDoc && existingDoc.parseStatusCode !== updatedDoc.parseStatusCode) {
          // 状态发生变化，更新文档
          Object.assign(existingDoc, updatedDoc);
          hasChanges = true;
          console.log(`文档 ${existingDoc.name} 状态已更新: ${existingDoc.parseStatusCode} -> ${updatedDoc.parseStatusCode}`);
          
          // 如果状态变为完成，启动切片数量检测
          if (updatedDoc.parseStatusCode === 3) {
            this.fetchSliceCountForSingleDocument(updatedDoc.id);
          }
        }
      });
      
      if (hasChanges) {
        this.$forceUpdate();
      }
    },

    // 为文档列表中的每个文档获取切片数量
    fetchSliceCountsForDocuments: async function () {
      if (!this.fileList || this.fileList.length === 0) {
        return;
      }

      // 为每个文档获取切片数量
      for (const document of this.fileList) {
        this.fetchSliceCountForSingleDocument(document.id);
      }
    },

    // 获取单个文档的切片数量
    fetchSliceCountForSingleDocument: function (documentId) {
      const document = this.fileList.find(doc => doc.id === documentId);
      if (!document) {
        console.warn('未找到文档:', documentId);
        return;
      }

      const params = {
        page: 1,
        page_size: 1  // 只需要获取总数，所以每页1条记录即可
      };

      KnowledgeBaseAPI.listChunks(this.datasetId, documentId, params,
        ({ data }) => {
          if (data && data.code === 0) {
            const sliceCount = data.data.total || 0;
            // 更新文档的切片数量
            this.$set(document, 'sliceCount', sliceCount);
            // 强制更新视图
            this.$forceUpdate();
            console.log(`文档 ${document.name} 切片数量已更新为:`, sliceCount);
          } else {
            console.warn(`获取文档 ${document.name} 切片数量失败:`, data?.msg);
          }
        },
        (err) => {
          console.warn(`获取文档 ${document.name} 切片数量失败:`, err);
        }
      );
    },

    // 智能检测切片生成状态并自动刷新
    smartRefreshSliceCount: function (documentId) {
      const document = this.fileList.find(doc => doc.id === documentId);
      if (!document) {
        console.warn('未找到文档:', documentId);
        return;
      }

      // 延迟2秒后获取切片数量，给后端更多处理时间
      setTimeout(() => {
        this.fetchSliceCountForSingleDocument(documentId);
      }, 2000);
    },
    handleSearch: function () {
      this.currentPage = 1;
      this.fetchFileList();
    },
    headerCellClassName: function ({ row, column, rowIndex, columnIndex }) {
      if (columnIndex === 0) {
        return 'header-cell-first';
      }
      return 'header-cell';
    },
    showUploadDialog: function () {
      this.uploadForm = {
        name: '',
        file: null
      };
      this.selectedFilesList = []; // 清空已选择文件列表
      this.uploadDialogVisible = true;
    },
    handleFileChange: function (file, fileList) {
      if (!file || !file.raw) return;

      // 文件上传前的验证
      const isLt10M = file.size / 1024 / 1024 < 10;
      if (!isLt10M) {
        this.$message.error(this.$t('xn.knowledge.fileTooLarge'));
        return;
      }

      // 添加到已选择文件列表
      this.selectedFilesList.push({
        name: file.name,
        size: file.size,
        raw: file.raw
      });
    },
    beforeUpload: function (file) {
      // 文件上传前的验证
      const isLt10M = file.size / 1024 / 1024 < 10;
      if (!isLt10M) {
        this.$message.error(this.$t('xn.knowledge.fileTooLarge'));
        return false;
      }
      // 保存文件到uploadForm
      this.uploadForm.file = file;
      return false; // 阻止自动上传，使用自定义上传逻辑
    },
    // 移除已选择的文件
    removeSelectedFile: function (index) {
      this.selectedFilesList.splice(index, 1);
    },

    // 格式化文件大小
    formatFileSize: function (bytes) {
      if (bytes === 0) return '0 B';
      const k = 1024;
      const sizes = ['B', 'KB', 'MB', 'GB'];
      const i = Math.floor(Math.log(bytes) / Math.log(k));
      return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    },

    // 批量上传提交
    handleBatchUploadSubmit: function () {
      if (this.selectedFilesList.length === 0) {
        this.$message.error(this.$t('knowledgeFileUpload.fileRequired'));
        return;
      }

      this.uploading = true;

      // 创建上传任务数组
      const uploadPromises = this.selectedFilesList.map(file => {
        return new Promise((resolve, reject) => {
          const formData = new FormData();
          formData.append('file', file.raw);

          KnowledgeBaseAPI.uploadDocument(this.datasetId, formData,
            ({ data }) => {
              if (data && data.code === 0) {
                resolve({ success: true, fileName: file.name });
              } else {
                reject({ success: false, fileName: file.name, error: data?.msg || this.$t('knowledgeFileUpload.uploadFailed') });
              }
            },
            (err) => {
              // 错误回调处理后端返回的错误信息
              if (err && err.data) {
                reject({ success: false, fileName: file.name, error: err.data.msg || err.msg || this.$t('knowledgeFileUpload.uploadFailed') });
              } else {
                reject({ success: false, fileName: file.name, error: this.$t('knowledgeFileUpload.uploadFailed') });
              }
              console.error('上传文档失败:', err);
            }
          );
        });
      });

      // 执行所有上传任务
      Promise.all(uploadPromises.map(p => p.catch(e => e)))
        .then(results => {
          this.uploading = false;

          const successCount = results.filter(r => r.success).length;
          const failedCount = results.filter(r => !r.success).length;

          if (successCount > 0) {
            this.$message.success(this.$t(this.isMock ? 'xn.knowledge.uploadDoneMock' : 'xn.knowledge.uploadDone', { n: successCount }));
          }

          if (failedCount > 0) {
            const failedFiles = results.filter(r => !r.success).map(r => r.fileName);
            this.$message.error(this.$t('xn.knowledge.uploadPartFailed', { n: failedCount, files: failedFiles.join('、') }));
          }

          if (successCount > 0) {
            this.uploadDialogVisible = false;
            this.fetchFileList();
          }
        })
        .catch(error => {
          this.uploading = false;
          this.$message.error(this.$t('knowledgeFileUpload.uploadFailed'));
          console.error('批量上传失败:', error);
        });
    },

    // 单文件上传（保留原有功能）
    handleUploadSubmit: function () {
      if (!this.uploadForm.file) {
        this.$message.error(this.$t('knowledgeFileUpload.fileRequired'));
        return;
      }

      this.uploading = true;

      const formData = new FormData();
      formData.append('file', this.uploadForm.file);

      KnowledgeBaseAPI.uploadDocument(this.datasetId, formData,
        ({ data }) => {
          this.uploading = false;
          if (data && data.code === 0) {
            this.$message.success(this.$t('knowledgeFileUpload.uploadSuccess'));
            this.uploadDialogVisible = false;
            this.fetchFileList();
          } else {
            this.$message.error(data?.msg || this.$t('knowledgeFileUpload.uploadFailed'));
          }
        },
        (err) => {
          this.uploading = false;
          // 错误回调处理后端返回的错误信息
          if (err && err.data) {
            this.$message.error(err.data.msg || err.msg || this.$t('knowledgeFileUpload.uploadFailed'));
          } else {
            this.$message.error(this.$t('knowledgeFileUpload.uploadFailed'));
          }
          console.error('上传文档失败:', err);
        }
      );
    },
    handleParse: function (row) {
      this.$confirm(this.$t('knowledgeFileUpload.confirmParse'), this.$t('warning'), {
        confirmButtonText: this.$t('knowledgeFileUpload.confirm'),
        cancelButtonText: this.$t('knowledgeFileUpload.cancel'),
        type: 'warning'
      }).then(() => {
        KnowledgeBaseAPI.parseDocument(this.datasetId, row.id,
          ({ data }) => {
            if (data && data.code === 0) {
              this.$message.success(this.$t('xn.knowledge.parseStarted'));
              
              // 立即更新文档状态为处理中
              const document = this.fileList.find(doc => doc.id === row.id);
              if (document) {
                document.parseStatusCode = 1; // 处理中状态
                this.$forceUpdate();
              }
              
              // 启动状态轮询
              this.startStatusPolling();
              
              // 使用智能检测自动刷新切片数量
              this.smartRefreshSliceCount(row.id);
            } else {
              this.$message.error(data?.msg || this.$t('knowledgeFileUpload.parseFailed'));
            }
          },
          (err) => {
            // 错误回调处理后端返回的错误信息
            if (err && err.data) {
              this.$message.error(err.data.msg || err.msg || this.$t('knowledgeFileUpload.parseFailed'));
            } else {
              this.$message.error(this.$t('knowledgeFileUpload.parseFailed'));
            }
            console.error('解析文档失败:', err);
          }
        );
      }).catch(() => {
        this.$message.info(this.$t('knowledgeFileUpload.parseCancelled'));
      });
    },
    handleViewSlices: function (row) {
      // 查看切片
      this.currentDocumentId = row.id;
      this.currentDocumentName = row.name;
      this.sliceDialogVisible = true;
      this.sliceCurrentPage = 1;
      this.sliceSearchKeyword = '';
      this.fetchSlices();
    },
    handleDelete: function (row) {
      this.$confirm(this.$t('knowledgeFileUpload.confirmDelete'), this.$t('warning'), {
        confirmButtonText: this.$t('knowledgeFileUpload.confirm'),
        cancelButtonText: this.$t('knowledgeFileUpload.cancel'),
        type: 'warning'
      }).then(() => {
        KnowledgeBaseAPI.deleteDocument(this.datasetId, row.id,
          ({ data }) => {
            if (data && data.code === 0) {
              this.$message.success(this.$t('knowledgeFileUpload.deleteSuccess'));
              this.fetchFileList();
            } else {
              this.$message.error(data?.msg || this.$t('knowledgeFileUpload.deleteFailed'));
            }
          },
          (err) => {
            // 错误回调处理后端返回的错误信息
            if (err && err.data) {
              this.$message.error(err.data.msg || err.msg || this.$t('knowledgeFileUpload.deleteFailed'));
            } else {
              this.$message.error(this.$t('knowledgeFileUpload.deleteFailed'));
            }
            console.error('删除文档失败:', err);
          }
        );
      }).catch(() => {
        this.$message.info(this.$t('knowledgeFileUpload.deleteCancelled'));
      });
    },
    handleSelectionChange: function (selection) {
      this.selectedFiles = selection;
    },
    handleSelectAll: function () {
      if (this.isAllSelected) {
        this.$refs.fileTable.clearSelection();
        this.isAllSelected = false;
      } else {
        this.$refs.fileTable.clearSelection();
        this.fileList.forEach(row => {
          this.$refs.fileTable.toggleRowSelection(row, true);
        });
        this.isAllSelected = true;
      }
    },
    handleBatchDelete: function () {
      if (this.selectedFiles.length === 0) {
        this.$message.warning(this.$t('knowledgeFileUpload.selectFilesFirst'));
        return;
      }

      this.$confirm(this.$t('knowledgeFileUpload.confirmBatchDelete', { count: this.selectedFiles.length }), this.$t('warning'), {
        confirmButtonText: this.$t('knowledgeFileUpload.confirm'),
        cancelButtonText: this.$t('knowledgeFileUpload.cancel'),
        type: 'warning'
      }).then(() => {
        const deletePromises = this.selectedFiles.map(file => {
          return new Promise((resolve, reject) => {
            KnowledgeBaseAPI.deleteDocument(this.datasetId, file.id,
              ({ data }) => {
                if (data && data.code === 0) {
                  resolve();
                } else {
                  reject(data?.msg || this.$t('knowledgeFileUpload.deleteFailed'));
                }
              },
              (err) => {
                // 错误回调处理后端返回的错误信息
                if (err && err.data) {
                  reject(err.data.msg || err.msg || this.$t('knowledgeFileUpload.deleteFailed'));
                } else {
                  reject(this.$t('knowledgeFileUpload.deleteFailed'));
                }
                console.error('删除文档失败:', err);
              }
            );
          });
        });

        Promise.all(deletePromises)
          .then(() => {
            this.$message.success(this.$t('knowledgeFileUpload.batchDeleteSuccess', { count: this.selectedFiles.length }));
            this.selectedFiles = [];
            this.fetchFileList();
          })
          .catch((error) => {
            this.$message.error(error || this.$t('knowledgeFileUpload.batchDeleteFailed'));
          });
      }).catch(() => {
        this.$message.info(this.$t('knowledgeFileUpload.deleteCancelled'));
      });
    },
    getParseStatusType: function (parseStatusCode) {
      switch (parseStatusCode) {
        case 0:
          return 'info'; // 灰色 - 未开始
        case 1:
          return 'primary'; // 蓝色 - 处理中
        case 2:
          return 'warning'; // 黄色 - 已取消
        case 3:
          return 'success'; // 绿色 - 完成
        case 4:
          return 'danger'; // 红色 - 失败
        default:
          return 'info'; // 默认灰色
      }
    },
    statusTagClass: function (parseStatusCode) {
      return 'xn-tag--' + (STATUS_TAG[this.getParseStatusType(parseStatusCode)] || 'muted');
    },
    getParseStatusText: function (parseStatusCode) {
      switch (parseStatusCode) {
        case 0:
          return this.$t('knowledgeFileUpload.statusNotStarted');
        case 1:
          return this.$t('knowledgeFileUpload.statusProcessing');
        case 2:
          return this.$t('knowledgeFileUpload.statusCancelled');
        case 3:
          return this.$t('knowledgeFileUpload.statusCompleted');
        case 4:
          return this.$t('knowledgeFileUpload.statusFailed');
        default:
          return this.$t('knowledgeFileUpload.statusNotStarted');
      }
    },
    goToPage: function (page) {
      if (page !== this.currentPage) {
        this.currentPage = page;
        this.fetchFileList();
      }
    },
    goFirst: function () {
      if (this.currentPage !== 1) {
        this.currentPage = 1;
        this.fetchFileList();
      }
    },
    goPrev: function () {
      if (this.currentPage > 1) {
        this.currentPage--;
        this.fetchFileList();
      }
    },
    goNext: function () {
      if (this.currentPage < this.pageCount) {
        this.currentPage++;
        this.fetchFileList();
      }
    },
    formatDate: function (dateString) {
      if (!dateString) return '';
      const date = new Date(dateString);
      return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
    },

    // 切片管理相关方法
    fetchSlices: function () {
      this.sliceLoading = true;

      const params = {
        page: this.sliceCurrentPage,
        page_size: this.slicePageSize
      };

      if (this.sliceSearchKeyword) {
        params.keywords = this.sliceSearchKeyword;
      }

      KnowledgeBaseAPI.listChunks(this.datasetId, this.currentDocumentId, params,
        ({ data }) => {
          this.sliceLoading = false;
          if (data && data.code === 0) {
            // 解析切片列表数据
            this.parseSliceData(data.data);
          } else {
            this.$message.error(data?.msg || this.$t('xn.knowledge.slicesLoadFailed'));
            this.sliceList = [];
            this.sliceTotal = 0;
          }
        },
        (err) => {
          this.sliceLoading = false;
          // 错误回调处理后端返回的错误信息
          if (err && err.data) {
            this.$message.error(err.data.msg || err.msg || this.$t('xn.knowledge.slicesLoadFailed'));
          } else {
            this.$message.error(this.$t('xn.knowledge.slicesLoadFailed'));
          }
          console.error('获取切片列表失败:', err);
          this.sliceList = [];
          this.sliceTotal = 0;
        }
      );
    },

    parseSliceData: function (data) {
      try {
        if (data && data.list) {
          // 后端已经解析过的格式
          this.sliceList = data.list;
          this.sliceTotal = data.total || data.list.length;
        } else if (data && data.chunks && Array.isArray(data.chunks)) {
          // RAGFlow API原始格式
          this.sliceList = data.chunks;
          this.sliceTotal = data.total || data.chunks.length;
        } else if (data && Array.isArray(data)) {
          this.sliceList = data;
          this.sliceTotal = data.length;
        } else {
          this.sliceList = [];
          this.sliceTotal = 0;
        }

        console.log('解析后的切片数据:', {
          list: this.sliceList,
          total: this.sliceTotal
        });
      } catch (error) {
        console.error('解析切片数据失败:', error);
        this.sliceList = [];
        this.sliceTotal = 0;
      }
    },

    handleSliceSizeChange: function (pageSize) {
      this.slicePageSize = pageSize;
      this.sliceCurrentPage = 1;
      this.fetchSlices();
    },

    handleSlicePageChange: function (page) {
      this.sliceCurrentPage = page;
      this.fetchSlices();
    },

    // 跳转到切片管理第一页
    goToSliceFirstPage: function () {
      if (this.sliceCurrentPage !== 1) {
        this.sliceCurrentPage = 1;
        this.fetchSlices();
      }
    },

    // 切片管理上一页
    goToSlicePrevPage: function () {
      if (this.sliceCurrentPage > 1) {
        this.sliceCurrentPage--;
        this.fetchSlices();
      }
    },

    // 切片管理跳转到指定页
    goToSlicePage: function (page) {
      if (page !== this.sliceCurrentPage) {
        this.sliceCurrentPage = page;
        this.fetchSlices();
      }
    },

    // 切片管理下一页
    goToSliceNextPage: function () {
      if (this.sliceCurrentPage < this.slicePageCount) {
        this.sliceCurrentPage++;
        this.fetchSlices();
      }
    },

    // 召回测试相关方法
    showRetrievalTestDialog: function () {
      // 初始化召回测试表单
      this.retrievalTestForm = {
        question: ''
      };
      this.retrievalTestResult = null;
      this.retrievalTestDialogVisible = true;
    },

    runRetrievalTest: function () {
      if (!this.retrievalTestForm.question.trim()) {
        this.$message.error(this.$t('knowledgeFileUpload.testQuestionRequired'));
        return;
      }

      this.retrievalTestLoading = true;
      this.retrievalTestResult = null;

      // 准备请求数据
      const requestData = {
        question: this.retrievalTestForm.question.trim()
      };

      // 调用召回测试API
      KnowledgeBaseAPI.retrievalTest(this.datasetId, requestData,
        ({ data }) => {
          this.retrievalTestLoading = false;
          if (data && data.code === 0) {
            this.retrievalTestResult = data.data || data;
            this.$message.success(this.$t(this.isMock ? 'xn.knowledge.retrievalDoneMock' : 'xn.knowledge.retrievalDone'));
          } else {
            this.$message.error(data?.msg || this.$t('xn.knowledge.retrievalFailed'));
          }
        },
        (err) => {
          this.retrievalTestLoading = false;
          // 错误回调处理后端返回的错误信息
          if (err && err.data) {
            this.$message.error(err.data.msg || err.msg || this.$t('xn.knowledge.retrievalFailed'));
          } else {
            this.$message.error(this.$t('xn.knowledge.retrievalFailed'));
          }
          console.error('召回测试失败:', err);
        }
      );
    },

    handleRetrievalTestDialogClose: function () {
      this.retrievalTestDialogVisible = false;
      this.retrievalTestResult = null;
    }
  }
};
</script>

<style scoped>
.kf-search-icon { height: 100%; margin: 0 2px 0 4px; font-size: 16px; color: var(--xn-ink-3); }
.kf-panel { overflow: hidden; }
.kf-panel ::v-deep .kf-nowrap .cell { white-space: nowrap; }
.kf-doc { display: inline-flex; align-items: center; gap: 10px; max-width: 100%; min-width: 0; }
.kf-doc__ext {
  flex: none; display: inline-flex; align-items: center; justify-content: center; min-width: 40px; height: 22px; padding: 0 4px;
  border: 1px solid var(--xn-line); border-radius: 6px; background: var(--xn-mist-2);
  font-size: 11px; font-weight: 600; letter-spacing: 0.02em; color: var(--xn-ink-2);
}
.kf-doc__name { min-width: 0; font-weight: 500; }
.kf-pulse { animation: kf-pulse 1.4s ease-in-out infinite; }
@keyframes kf-pulse { 50% { opacity: 0.35; } }
.kf-danger { color: var(--xn-danger); }
.kf-danger:hover, .kf-danger:focus { color: #8D3523; }
.kf-foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; padding: 4px 16px 14px; border-top: 1px solid var(--xn-line-2); }
.kf-note { display: inline-flex; align-items: center; gap: 6px; padding-top: 10px; font-size: 13px; }

/* 上传 */
.kf-mock-note { display: flex; align-items: flex-start; gap: 8px; margin: 0 0 14px; font-size: 13px; line-height: 1.7; color: var(--xn-ink-2); }
.kf-mock-note .xn-tag { flex: none; margin-top: 1px; }
.kf-uploader ::v-deep .el-upload, .kf-uploader ::v-deep .el-upload-dragger { width: 100%; }
.kf-uploader ::v-deep .el-upload-dragger { height: auto; padding: 28px 20px 22px; }
.kf-uploader ::v-deep .el-upload__text { font-size: 14px; color: var(--xn-ink); }
.kf-uploader__icon { display: block; margin: 0 auto 10px; font-size: 32px; color: var(--xn-ink-3); }
.kf-uploader__tip { margin: 8px auto 0; max-width: 560px; overflow-wrap: anywhere; word-break: normal; font-size: 13px; line-height: 1.6; color: var(--xn-ink-3); }
.kf-picked { margin-top: 16px; }
.kf-picked__title { margin: 0 0 8px; font-size: 14px; font-weight: 600; color: var(--xn-ink); }
.kf-picked__list { max-height: 220px; overflow-y: auto; margin: 0; padding: 0; list-style: none; border: 1px solid var(--xn-line); border-radius: 8px; }
.kf-picked__item { display: flex; align-items: center; gap: 10px; padding: 6px 8px 6px 12px; }
.kf-picked__item + .kf-picked__item { border-top: 1px solid var(--xn-line-2); }
.kf-picked__name { flex: 1 1 auto; min-width: 0; color: var(--xn-ink); }
.kf-picked__size { flex: none; font-size: 13px; color: var(--xn-ink-3); }
.kf-picked__remove { flex: none; color: var(--xn-ink-3); font-size: 16px; }
.kf-picked__remove:hover { color: var(--xn-danger); }

/* 切片与召回结果 */
.kf-dialog-sub { margin: -4px 0 14px; font-size: 13px; color: var(--xn-ink-3); }
.kf-slices { min-height: 120px; }
.kf-slice-list { display: grid; gap: 10px; max-height: 52vh; overflow-y: auto; margin: 0; padding: 0; list-style: none; }
.kf-slice { padding: 12px 14px; border: 1px solid var(--xn-line); border-radius: 10px; background: #fff; }
.kf-slice__no { display: inline-block; font-size: 12px; font-weight: 600; color: var(--xn-ink-3); }
.kf-slice__text { margin: 6px 0 0; font-size: 14px; line-height: 1.75; color: var(--xn-ink); white-space: pre-wrap; word-break: break-word; }
.kf-slice-foot { display: flex; justify-content: flex-end; margin-top: 8px; }
.kf-rt-row { display: flex; gap: 10px; }
.kf-rt-row .el-input { flex: 1 1 auto; }
.kf-rt-result { margin-top: 4px; padding-top: 16px; border-top: 1px solid var(--xn-line-2); }
.kf-rt-result__head { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.kf-rt-result__title { margin: 0; font-size: 16px; font-weight: 600; color: var(--xn-ink); }
.kf-rt-count { font-size: 13px; }
.kf-rt-meta { display: flex; align-items: center; gap: 10px; min-width: 0; }
.kf-rt-src { min-width: 0; font-size: 13px; }
.kf-rt-score { flex: none; font-size: 13px; color: var(--xn-ink-3); }
.kf-rt-score b { margin-left: 4px; font-weight: 600; color: var(--xn-lake-ink); }
.kf-rt-result .xn-empty { padding: 28px 16px; }
.kf-rt-result .kf-slice-list { max-height: 42vh; }
@media (max-width: 640px) {
  .kf-rt-row { flex-direction: column; }
}
</style>
