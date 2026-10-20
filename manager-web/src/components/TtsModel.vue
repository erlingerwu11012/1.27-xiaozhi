<template>
  <el-dialog :visible.sync="localVisible" width="min(1080px, calc(100vw - 32px))" @close="handleClose" :append-to-body="true"
    :close-on-click-modal="false" :title="$t('xn.admin.voice.title', { name: (modelConfig && modelConfig.modelName) || ttsModelId })"
    custom-class="xn-tts-dialog">
    <div class="tm-toolbar">
      <el-input v-model="searchQuery" size="small" clearable :placeholder="$t('xn.admin.voice.search')" class="tm-search">
        <xn-icon slot="prefix" name="search" class="tm-search-icon" />
      </el-input>
      <span v-if="showReferenceColumns" class="xn-tag xn-tag--lake">{{ $t('xn.admin.voice.cloneMode') }}</span>
      <span class="tm-grow"></span>
      <template v-if="selectedCount">
        <span class="xn-muted">{{ $t('xn.admin.selected', { n: selectedCount }) }}</span>
        <el-button type="danger" plain size="small" @click="deleteRow(filteredTtsModels.filter(row => row.selected))">
          <xn-icon name="trash" /> {{ $t('xn.admin.deleteSelected') }}
        </el-button>
      </template>
      <el-button type="primary" size="small" @click="addNew"><xn-icon name="plus" /> {{ $t('xn.admin.voice.add') }}</el-button>
    </div>

    <div class="tm-table" ref="tableContainer" @scroll="handleScroll">
      <el-table v-loading="loading" :data="filteredTtsModels" style="width: 100%;">
        <el-table-column width="44" align="center">
          <template slot="header">
            <el-checkbox :value="allSelected" :disabled="!filteredTtsModels.length" :aria-label="$t('ttsModel.selectAll')" @change="toggleSelectAll" />
          </template>
          <template slot-scope="scope">
            <el-checkbox v-model="scope.row.selected"></el-checkbox>
          </template>
        </el-table-column>
        <el-table-column :label="$t('ttsModel.voiceCode')" min-width="150">
          <template slot-scope="scope">
            <el-input v-if="scope.row.editing" v-model="scope.row.voiceCode" size="small" class="tm-code"></el-input>
            <span v-else class="tm-mono">{{ scope.row.voiceCode }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="$t('ttsModel.voiceName')" min-width="140">
          <template slot-scope="scope">
            <el-input v-if="scope.row.editing" v-model="scope.row.voiceName" size="small"></el-input>
            <span v-else class="tm-strong">{{ scope.row.voiceName }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="$t('ttsModel.languageType')" width="120">
          <template slot-scope="scope">
            <el-input v-if="scope.row.editing" v-model="scope.row.languageType" size="small"></el-input>
            <span v-else>{{ scope.row.languageType }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="!showReferenceColumns" :label="$t('ttsModel.preview')" min-width="230">
          <template slot-scope="scope">
            <el-input v-if="scope.row.editing" v-model="scope.row.voiceDemo" size="small" :placeholder="$t('ttsModel.enterMp3Url')"></el-input>
            <AudioPlayer v-else-if="isValidAudioUrl(scope.row.voiceDemo)" :audioUrl="scope.row.voiceDemo" />
            <span v-else class="xn-muted">{{ $t('xn.admin.voice.noDemo') }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="!showReferenceColumns" :label="$t('ttsModel.remark')" min-width="140">
          <template slot-scope="scope">
            <el-input v-if="scope.row.editing" type="textarea" :rows="1" autosize v-model="scope.row.remark"
              :placeholder="$t('ttsModel.enterRemark')"></el-input>
            <span v-else>{{ scope.row.remark }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="showReferenceColumns" :label="$t('ttsModel.cloneAudioPath')" min-width="200">
          <template slot-scope="scope">
            <el-input v-if="scope.row.editing" v-model="scope.row.referenceAudio" size="small" :placeholder="$t('ttsModel.enterCloneAudioPath')"></el-input>
            <span v-else class="tm-mono">{{ scope.row.referenceAudio }}</span>
          </template>
        </el-table-column>
        <el-table-column v-if="showReferenceColumns" :label="$t('ttsModel.cloneAudioText')" min-width="200">
          <template slot-scope="scope">
            <el-input v-if="scope.row.editing" v-model="scope.row.referenceText" size="small" :placeholder="$t('ttsModel.enterCloneAudioText')"></el-input>
            <span v-else>{{ scope.row.referenceText }}</span>
          </template>
        </el-table-column>
        <el-table-column :label="$t('ttsModel.operation')" width="130" align="right">
          <template slot-scope="scope">
            <template v-if="!scope.row.editing">
              <el-button type="text" @click="startEdit(scope.row)">{{ $t('ttsModel.edit') }}</el-button>
              <el-button type="text" class="tm-danger" @click="deleteRow(scope.row)">{{ $t('ttsModel.delete') }}</el-button>
            </template>
            <template v-else>
              <el-button type="text" @click="cancelEdit(scope.row)">{{ $t('xn.common.cancel') }}</el-button>
              <el-button type="primary" size="mini" @click="saveEdit(scope.row)">{{ $t('ttsModel.save') }}</el-button>
            </template>
          </template>
        </el-table-column>
        <template slot="empty">
          <xn-empty icon="voice" :title="searchQuery ? $t('xn.admin.voice.noMatch') : $t('xn.admin.voice.empty')"
            :description="searchQuery ? '' : $t('xn.admin.voice.emptyDesc')" />
        </template>
      </el-table>
    </div>
    <p class="tm-foot xn-muted">{{ $t('xn.admin.voice.total', { n: filteredTtsModels.length }) }}</p>
  </el-dialog>
</template>

<script>
import Api from "@/apis/api";
import AudioPlayer from './AudioPlayer.vue';

export default {
  components: { AudioPlayer },
  props: {
    visible: {
      type: Boolean,
      default: false
    },
    ttsModelId: {
      type: String,
      required: true
    },
    modelConfig: {
      type: Object,
      default: null
    }
  },
  data() {
    return {
      localVisible: this.visible,
      searchQuery: '',
      editDialogVisible: false,
      editVoiceData: {},
      ttsModels: [],
      currentPage: 1,
      pageSize: 10000,
      total: 0,
      isDragging: false,
      startY: 0,
      scrollTop: 0,
      selectAll: false,
      selectedRows: [],
      loading: false,
      showReferenceColumns: false, // 控制是否显示参考列
    };
  },
  watch: {
    visible(newVal) {
      this.localVisible = newVal;
      if (newVal) {
        this.currentPage = 1;
        this.updateShowReferenceColumns(); // 更新显示状态
        this.loadData(); // 对话框显示时加载数据
        this.$nextTick(() => {
          this.updateScrollbar();
        });
      }
    },
    modelConfig: {
      handler(newVal) {
        this.updateShowReferenceColumns();
      },
      immediate: true
    },
    filteredTtsModels() {
      this.$nextTick(() => {
        this.updateScrollbar();
      });
    }
  },
  computed: {
    selectedCount() {
      return this.filteredTtsModels.filter((r) => r.selected).length;
    },
    allSelected() {
      return this.filteredTtsModels.length > 0 && this.filteredTtsModels.every((r) => r.selected);
    },
    filteredTtsModels() {
      return this.ttsModels.filter(model =>
        model.voiceName.toLowerCase().includes(this.searchQuery.toLowerCase())
      );
    }
  },
  mounted() {
    this.updateScrollbar();
    window.addEventListener('resize', this.updateScrollbar);
    window.addEventListener('mouseup', this.stopDrag);
    window.addEventListener('mousemove', this.handleDrag);
  },
  beforeDestroy() {
    window.removeEventListener('resize', this.updateScrollbar);
    window.removeEventListener('mouseup', this.stopDrag);
    window.removeEventListener('mousemove', this.handleDrag);
  },
  methods: {
    // 更新是否显示参考列
    updateShowReferenceColumns() {
      if (this.modelConfig && this.modelConfig.configJson) {
        const providerType = this.modelConfig.configJson.type;
        this.showReferenceColumns = ['fishspeech', 'gpt_sovits_v2', 'gpt_sovits_v3'].includes(providerType);
      } else {
        this.showReferenceColumns = false;
      }
    },

    loadData() {
      this.loading = true;
      const params = {
        ttsModelId: this.ttsModelId,
        page: this.currentPage,
        limit: this.pageSize,
        name: this.searchQuery
      };
      Api.timbre.getVoiceList(params, (data) => {
        if (data.code === 0) {
          this.ttsModels = data.data.list
            .map(item => ({
              id: item.id || '',
              voiceCode: item.ttsVoice || '',
              voiceName: item.name || this.$t('ttsModel.unnamedVoice'),
              languageType: item.languages || '',
              remark: item.remark || '',
              referenceAudio: item.referenceAudio || '',
              referenceText: item.referenceText || '',
              voiceDemo: item.voiceDemo || '',
              selected: false,
              editing: false,
              sort: Number(item.sort)
            }))
            .sort((a, b) => a.sort - b.sort);
          this.total = data.total;
        } else {
          this.$message.error({
            message: data.msg || this.$t('ttsModel.getVoiceListFailed'),
            showClose: true
          });
        }
        this.loading = false;
      }, (err) => {
        console.error('加载失败:', err);
        this.$message.error({
          message: this.$t('ttsModel.loadVoiceDataFailed'),
          showClose: true
        });
        this.loading = false;
      });
    },

    handleClose() {
      // 重置状态
      this.ttsModels = [];
      this.currentPage = 1;
      this.total = 0;
      this.selectAll = false;
      this.searchQuery = '';
      this.showReferenceColumns = false;

      this.localVisible = false;
      this.$emit('update:visible', false);
    },

    updateScrollbar() {
      const container = this.$refs.tableContainer;
      const scrollbarThumb = this.$refs.scrollbarThumb;
      const scrollbarTrack = this.$refs.scrollbarTrack;

      if (!container || !scrollbarThumb || !scrollbarTrack) return;

      const { scrollHeight, clientHeight } = container;
      const trackHeight = scrollbarTrack.clientHeight;
      const thumbHeight = Math.max((clientHeight / scrollHeight) * trackHeight, 20);

      scrollbarThumb.style.height = `${thumbHeight}px`;
      this.updateThumbPosition();
    },

    updateThumbPosition() {
      const container = this.$refs.tableContainer;
      const scrollbarThumb = this.$refs.scrollbarThumb;
      const scrollbarTrack = this.$refs.scrollbarTrack;

      if (!container || !scrollbarThumb || !scrollbarTrack) return;

      const { scrollHeight, clientHeight, scrollTop } = container;
      const trackHeight = scrollbarTrack.clientHeight;
      const thumbHeight = scrollbarThumb.clientHeight;
      const maxTop = trackHeight - thumbHeight;
      const thumbTop = (scrollTop / (scrollHeight - clientHeight)) * (trackHeight - thumbHeight);

      scrollbarThumb.style.top = `${Math.min(thumbTop, maxTop)}px`;
    },

    handleScroll() {
      const container = this.$refs.tableContainer;
      if (container.scrollTop + container.clientHeight >= container.scrollHeight - 50) {
        if (this.currentPage * this.pageSize < this.total) {
          this.currentPage++;
          this.loadData();
        }
      }
      this.updateThumbPosition();
    },

    startDrag(e) {
      this.isDragging = true;
      this.startY = e.clientY;
      this.scrollTop = this.$refs.tableContainer.scrollTop;
      e.preventDefault();
    },

    stopDrag() {
      this.isDragging = false;
    },

    handleDrag(e) {
      if (!this.isDragging) return;

      const container = this.$refs.tableContainer;
      const scrollbarTrack = this.$refs.scrollbarTrack;
      const scrollbarThumb = this.$refs.scrollbarThumb;
      const deltaY = e.clientY - this.startY;
      const trackHeight = scrollbarTrack.clientHeight;
      const thumbHeight = scrollbarThumb.clientHeight;
      const maxScrollTop = container.scrollHeight - container.clientHeight;

      const scrollRatio = (trackHeight - thumbHeight) / maxScrollTop;
      container.scrollTop = this.scrollTop + deltaY / scrollRatio;
    },

    handleTrackClick(e) {
      const container = this.$refs.tableContainer;
      const scrollbarTrack = this.$refs.scrollbarTrack;
      const scrollbarThumb = this.$refs.scrollbarThumb;

      if (!container || !scrollbarTrack || !scrollbarThumb) return;

      const trackRect = scrollbarTrack.getBoundingClientRect();
      const thumbHeight = scrollbarThumb.clientHeight;
      const clickPosition = e.clientY - trackRect.top;
      const thumbCenter = clickPosition - thumbHeight / 2;

      const trackHeight = scrollbarTrack.clientHeight;
      const maxTop = trackHeight - thumbHeight;
      const newTop = Math.max(0, Math.min(thumbCenter, maxTop));

      scrollbarThumb.style.top = `${newTop}px`;
      container.scrollTop = (newTop / (trackHeight - thumbHeight)) * (container.scrollHeight - container.clientHeight);
    },

    startEdit(row) {
      row.editing = true;
      this.$set(row, 'originalData', { ...row });
    },

    saveEdit(row) {
      if (!row.voiceCode || !row.voiceName || !row.languageType) {
        this.$message.error({
          message: this.$t('ttsModel.voiceCodeNameLanguageRequired'),
          showClose: true
        });
        return;
      }

      try {
        const params = {
          id: row.id,
          voiceCode: row.voiceCode,
          voiceName: row.voiceName,
          languageType: row.languageType,
          remark: row.remark,
          ttsModelId: this.ttsModelId,
          voiceDemo: row.voiceDemo || '',
          sort: row.sort
        };

        // 只有在显示参考列的情况下才添加参考字段
        if (this.showReferenceColumns) {
          params.referenceAudio = row.referenceAudio;
          params.referenceText = row.referenceText;
        }

        let res;
        if (row.id) {
          // 已有ID，执行更新操作
          Api.timbre.updateVoice(params, (response) => {
            res = response;
            this.handleResponse(res, row);
          });
        } else {
          // 没有ID，执行新增操作
          Api.timbre.saveVoice(params, (response) => {
            res = response;
            this.handleResponse(res, row);
          });
        }
      } catch (error) {
        console.error('操作失败:', error);
        // 异常情况下也恢复原始数据
        if (row.originalData) {
          Object.assign(row, row.originalData);
          row.editing = false;
          delete row.originalData;
        }
        this.$message.error({
          message: this.$t('ttsModel.operationFailed'),
          showClose: true
        });
      }
    },

    handleResponse(res, row) {
      if (res.code === 0) {
        this.$message.success({
          message: row.id ? this.$t('ttsModel.updateSuccess') : this.$t('ttsModel.saveSuccess'),
          showClose: true
        });
        row.editing = false;
        delete row.originalData;
        this.loadData(); // 刷新数据
      } else {
        // 保存失败时恢复原始数据
        if (row.originalData) {
          Object.assign(row, row.originalData);
          row.editing = false;
          delete row.originalData;
        }
        this.$message.error({
            message: res.msg || (row.id ? this.$t('ttsModel.updateFailed') : this.$t('ttsModel.saveFailed')),
            showClose: true
          });
      }
    },

    // 取消编辑：已有音色恢复原值，新增的空行直接移除
    cancelEdit(row) {
      if (!row.id) {
        this.ttsModels = this.ttsModels.filter((r) => r !== row);
        return;
      }
      if (row.originalData) {
        const { originalData, ...orig } = row.originalData;
        Object.assign(row, orig);
        delete row.originalData;
      }
      row.editing = false;
    },

    toggleSelectAll() {
      this.selectAll = !this.allSelected;
      this.filteredTtsModels.forEach(row => {
        row.selected = this.selectAll;
      });
    },

    addNew() {
      const hasEditing = this.ttsModels.some(row => row.editing);
      if (hasEditing) {
        this.$message.warning(this.$t('ttsModel.finishEditingFirst'));
        return;
      }

      const maxSort = this.ttsModels.length > 0
        ? Math.max(...this.ttsModels.map(item => Number(item.sort) || 0))
        : 0;

      const newRow = {
        voiceCode: '',
        voiceName: '',
        languageType: this.$t('editVoiceDialog.defaultLanguageType'),
        voiceDemo: '',
        remark: '',
        referenceAudio: '',
        referenceText: '',
        selected: false,
        editing: true,
        sort: maxSort + 1
      };

      this.ttsModels.unshift(newRow);
    },

    deleteRow(row) {
      // 处理单个音色或音色数组
      const voices = Array.isArray(row) ? row : [row];

      if (Array.isArray(row) && row.length === 0) {
        this.$message.warning(this.$t('ttsModel.selectVoiceToDelete'));
        return;
      }


      const voiceCount = voices.length;
      this.$confirm(this.$t('ttsModel.confirmDeleteVoice', {count: voiceCount}), this.$t('ttsModel.warning'), {
        confirmButtonText: this.$t('common.confirm'),
        cancelButtonText: this.$t('common.cancel'),
        type: "warning",
        distinguishCancelAndClose: true
      }).then(() => {
        const ids = voices.map(voice => voice.id);
        if (ids.some(id => !id)) {
          this.$message.error(this.$t('ttsModel.invalidVoiceId'));
          return;
        }

        Api.timbre.deleteVoice(ids, ({ data }) => {
          if (data.code === 0) {
            this.$message.success({
              message: this.$t('ttsModel.deleteVoiceSuccess', {count: voiceCount}),
              showClose: true
            });
            this.loadData(); // 刷新参数列表
          } else {
            this.$message.error({
              message: data.msg || this.$t('ttsModel.deleteFailed'),
              showClose: true
            });
          }
        });
      }).catch(action => {
        if (action === 'cancel') {
          this.$message({
            type: 'info',
            message: this.$t('ttsModel.deleteCancelled'),
            duration: 1000
          });
        } else {
          this.$message({
            type: 'info',
            message: this.$t('ttsModel.operationClosed'),
            duration: 1000
          });
        }
      });
    },

    isValidAudioUrl(url) {
      return url && (url.endsWith('.mp3') || url.endsWith('.ogg') || url.endsWith('.wav'));
    }
  }
};
</script>

<style scoped>
.tm-toolbar { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin-bottom: 12px; }
.tm-search { width: 240px; }
.tm-search-icon { height: 100%; margin: 0 2px 0 4px; font-size: 15px; color: var(--xn-ink-3); }
.tm-grow { flex: 1; }
.tm-table { max-height: 60vh; overflow: auto; border: 1px solid var(--xn-line); border-radius: var(--xn-r); }
.tm-table ::v-deep .el-table::before { display: none; }
.tm-mono, .tm-code ::v-deep .el-input__inner { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 13px; word-break: break-all; }
.tm-strong { font-weight: 500; }
.tm-danger { color: var(--xn-danger); }
.tm-danger:hover, .tm-danger:focus { color: #8D3523; }
.tm-foot { margin: 10px 0 0; font-size: 13px; }
</style>
