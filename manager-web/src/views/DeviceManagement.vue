<template>
  <div class="xn-page">
    <page-header :title="$t('device.management')" :description="$t('xn.devices.desc')">
      <el-button @click="handleRecoverDevice" :disabled="!currentAgentId"><xn-icon name="refresh" /> {{ $t('xn.devices.recover') }}</el-button>
      <el-button @click="handleManualAddDevice" :disabled="!currentAgentId"><xn-icon name="edit" /> {{ $t('xn.devices.manual') }}</el-button>
      <el-button type="primary" @click="handleAddDevice" :disabled="!currentAgentId"><xn-icon name="plus" /> {{ $t('xn.top.addDevice') }}</el-button>
    </page-header>

    <div v-if="agentsLoaded && !agents.length" class="xn-panel">
      <xn-empty icon="agent" :title="$t('xn.devices.noAgentTitle')" :description="$t('xn.devices.noAgentDesc')">
        <el-button type="primary" @click="$router.push({ path: '/home', query: { create: '1' } })">{{ $t('home.addAgent') }}</el-button>
      </xn-empty>
    </div>

    <template v-else>
      <div class="xn-toolbar">
        <label class="dm-agent">
          <span class="xn-muted">{{ $t('xn.devices.agent') }}</span>
          <el-select :value="currentAgentId" filterable :loading="!agentsLoaded" @change="selectAgent">
            <el-option v-for="a in agents" :key="a.id" :label="a.agentName" :value="a.id">
              <span>{{ a.agentName }}</span><span class="dm-opt-count xn-num">{{ a.deviceCount || 0 }}</span>
            </el-option>
          </el-select>
        </label>
        <el-input v-model="searchKeyword" :placeholder="$t('xn.devices.searchPlaceholder')" clearable
          @keyup.enter.native="handleSearch" @clear="handleSearch" @input="handleSearch">
          <xn-icon slot="prefix" name="search" class="dm-search-icon" />
        </el-input>
        <span class="xn-toolbar__grow"></span>
        <template v-if="selectedCount">
          <span class="xn-muted">{{ $t('xn.devices.selected', { n: selectedCount }) }}</span>
          <el-button type="danger" plain size="small" @click="deleteSelected"><xn-icon name="link" /> {{ $t('xn.devices.unbindSelected') }}</el-button>
        </template>
      </div>

      <div class="xn-panel xn-panel--flush dm-panel">
        <xn-empty v-if="loadFailed && !loading" error @retry="fetchBindDevices(currentAgentId)" />
        <template v-else>
          <el-table ref="deviceTable" :data="paginatedDeviceList" v-loading="loading" row-key="device_id">
            <el-table-column width="52" align="center">
              <template slot="header" slot-scope="{}">
                <el-checkbox :value="isCurrentPageAllSelected" :disabled="!paginatedDeviceList.length"
                  :aria-label="isCurrentPageAllSelected ? $t('common.deselectAll') : $t('common.selectAll')" @change="handleSelectAll" />
              </template>
              <template slot-scope="scope">
                <el-checkbox v-model="scope.row.selected" />
              </template>
            </el-table-column>
            <el-table-column :label="$t('device.remark')" min-width="200">
              <template #default="{ row }">
                <el-input v-if="row.isEdit" v-model="row.remark" size="small" maxlength="64" show-word-limit autofocus
                  @blur="onRemarkBlur(row)" @keyup.enter.native="onRemarkEnter(row)" />
                <button v-else type="button" class="dm-remark" :title="$t('xn.devices.editRemark')" @click="row.isEdit = true">
                  <span :class="{ 'xn-muted': !row.remark }">{{ row.remark || $t('xn.devices.noRemark') }}</span>
                  <xn-icon name="edit" class="dm-remark__icon" />
                </button>
              </template>
            </el-table-column>
            <el-table-column :label="$t('device.model')" min-width="150">
              <template slot-scope="scope">{{ getFirmwareTypeName(scope.row.model) }}</template>
            </el-table-column>
            <el-table-column :label="$t('device.macAddress')" min-width="160">
              <template slot-scope="{ row }"><span class="xn-num">{{ row.macAddress }}</span></template>
            </el-table-column>
            <el-table-column :label="$t('device.firmwareVersion')" prop="firmwareVersion" min-width="100" />
            <el-table-column :label="$t('device.bindTime')" min-width="160" class-name="dm-nowrap">
              <template slot-scope="{ row }"><span class="xn-num">{{ (row.bindTime || '').slice(0, 16) }}</span></template>
            </el-table-column>
            <el-table-column :label="$t('device.lastConversation')" min-width="140">
              <template slot-scope="{ row }">{{ relTime(row.lastConversation) }}</template>
            </el-table-column>
            <el-table-column :label="$t('device.operation')" width="170" align="right">
              <template slot-scope="scope">
                <el-button type="text" @click="handleOpenAssets(scope.row.device_id)">{{ $t('deviceAssets.entry') }}</el-button>
                <el-button type="text" class="dm-danger" @click="handleUnbind(scope.row.device_id)">{{ $t('device.unbind') }}</el-button>
              </template>
            </el-table-column>
            <template slot="empty">
              <xn-empty v-if="!deviceList.length" icon="device" :title="$t('xn.devices.emptyTitle')" :description="$t('xn.devices.emptyDesc')">
                <el-button type="primary" @click="handleAddDevice"><xn-icon name="plus" /> {{ $t('xn.top.addDevice') }}</el-button>
              </xn-empty>
              <xn-empty v-else icon="search" :title="$t('xn.devices.noMatch')" />
            </template>
          </el-table>
          <div v-if="filteredDeviceList.length" class="dm-foot">
            <span class="xn-muted dm-note"><xn-icon name="info" /> {{ $t('xn.devices.boundNotOnline') }}</span>
            <el-pagination background layout="total, sizes, prev, pager, next" :total="filteredDeviceList.length"
              :page-size="pageSize" :page-sizes="pageSizeOptions" :current-page="currentPage"
              @size-change="handlePageSizeChange" @current-change="goToPage" />
          </div>
        </template>
      </div>
    </template>

    <DeviceAssetsDialog :visible.sync="assetsDialogVisible" :device-id="selectedDeviceIdForAssets" />
  </div>
</template>

<script>
import Api from '@/apis/api';
import DeviceAssetsDialog from "@/components/DeviceAssetsDialog.vue";
import { relativeTime } from "@/components/DeviceItem.vue";

export default {
  components: {
    DeviceAssetsDialog
  },
  data() {
    return {
      agents: [],
      agentsLoaded: false,
      loadFailed: false,
      assetsDialogVisible: false,
      selectedDeviceIdForAssets: '',
      selectedDeviceId: '',
      searchKeyword: "",
      activeSearchKeyword: "",
      currentAgentId: this.$route.query.agentId || '',
      currentPage: 1,
      pageSize: 10,
      pageSizeOptions: [10, 20, 50, 100],
      deviceList: [],
      loading: false,
      userApi: null,
      firmwareTypes: [],
    };
  },
  computed: {
    filteredDeviceList() {
      const keyword = this.activeSearchKeyword.toLowerCase();
      if (!keyword) return this.deviceList;
      return this.deviceList.filter(device =>
        (device.model && device.model.toLowerCase().includes(keyword)) ||
        (device.macAddress && device.macAddress.toLowerCase().includes(keyword)) ||
        (device.remark && device.remark.toLowerCase().includes(keyword))
      );
    },

    paginatedDeviceList() {
      const start = (this.currentPage - 1) * this.pageSize;
      const end = start + this.pageSize;
      return this.filteredDeviceList.slice(start, end);
    },
    selectedCount() {
      return this.deviceList.filter((d) => d.selected).length;
    },
    pageCount() {
      return Math.ceil(this.filteredDeviceList.length / this.pageSize);
    },
    // 计算当前页是否全选
    isCurrentPageAllSelected() {
      return this.paginatedDeviceList.length > 0 &&
        this.paginatedDeviceList.every(device => device.selected);
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
  mounted() {
    // 原页面依赖 ?agentId；新版从侧栏进入时没有 agentId，则读取智能体列表并默认选第一个
    this.fetchAgents();
    this.$eventBus.$on('xn:devices-changed', this.onDevicesChanged);
  },
  beforeDestroy() {
    this.$eventBus.$off('xn:devices-changed', this.onDevicesChanged);
  },
  watch: {
    '$route.query.agentId'(id) {
      if (id && id !== this.currentAgentId) {
        this.currentAgentId = id;
        this.currentPage = 1;
        this.fetchBindDevices(id);
      }
    },
  },
  created() {
    this.getFirmwareTypes()
  },
  methods: {
    async getFirmwareTypes() {
      try {
        const res = await Api.dict.getDictDataByType('FIRMWARE_TYPE')
        this.firmwareTypes = res.data
      } catch (error) {
        console.error(this.$t('device.getFirmwareTypeFailed') + ':', error)
        this.$message.error(error.message || this.$t('device.getFirmwareTypeFailed'))
      }
    },
    handlePageSizeChange(val) {
      this.pageSize = val;
      this.currentPage = 1;
    },
    handleSearch() {
      this.activeSearchKeyword = this.searchKeyword;
      this.currentPage = 1;
    },

    handleSelectAll() {
      const shouldSelectAll = !this.isCurrentPageAllSelected;
      this.paginatedDeviceList.forEach(row => {
        row.selected = shouldSelectAll;
      });
    },

    deleteSelected() {
      const selectedDevices = this.paginatedDeviceList.filter(device => device.selected);
      if (selectedDevices.length === 0) {
        this.$message.warning({
          message: this.$t('device.selectAtLeastOne'),
          showClose: true
        });
        return;
      }

      this.$confirm(this.$t('device.confirmBatchUnbind').replace('{count}', selectedDevices.length), this.$t('message.warning'), {
        confirmButtonText: this.$t('button.ok'),
        cancelButtonText: this.$t('button.cancel'),
        type: 'warning'
      }).then(() => {
        const deviceIds = selectedDevices.map(device => device.device_id);
        this.batchUnbindDevices(deviceIds);
      });
    },
    batchUnbindDevices(deviceIds) {
      const promises = deviceIds.map(id => {
        return new Promise((resolve, reject) => {
          Api.device.unbindDevice(id, ({ data }) => {
            if (data.code === 0) {
              resolve();
            } else {
              reject(data.msg || this.$t('device.bindFailed'));
            }
          });
        });
      });
      Promise.all(promises)
        .then(() => {
          this.$message.success({
            message: this.$t('device.batchUnbindSuccess').replace('{count}', deviceIds.length),
            showClose: true
          });
          this.fetchBindDevices(this.currentAgentId);
        })
        .catch(error => {
          this.$message.error({
            message: error || this.$t('device.batchUnbindError'),
            showClose: true
          });
        });
    },
    fetchAgents() {
      Api.agent.getAgentList(({ data }) => {
        this.agentsLoaded = true;
        if (!data || data.code !== 0) { this.loadFailed = true; return; }
        this.agents = data.data || [];
        const wanted = this.$route.query.agentId;
        const id = wanted && this.agents.some((a) => a.id === wanted) ? wanted : (this.agents[0] && this.agents[0].id);
        if (id) this.selectAgent(id);
      });
    },
    selectAgent(id) {
      this.currentAgentId = id;
      this.currentPage = 1;
      if (this.$route.query.agentId !== id) this.$router.replace({ query: { ...this.$route.query, agentId: id } }).catch(() => {});
      this.fetchBindDevices(id);
    },
    onDevicesChanged() {
      if (this.currentAgentId) this.fetchBindDevices(this.currentAgentId);
    },
    relTime(v) {
      return relativeTime(this, v);
    },
    // 添加 / 恢复 / 手动添加：统一打开外壳里的“添加设备”弹窗（DeviceBindDialog），预选当前智能体
    handleAddDevice() {
      this.$eventBus.$emit('xn:open-bind', { agentId: this.currentAgentId });
    },
    handleRecoverDevice() {
      this.$eventBus.$emit('xn:open-bind', { agentId: this.currentAgentId, mode: 'recovery' });
    },
    handleManualAddDevice() {
      this.$eventBus.$emit('xn:open-bind', { agentId: this.currentAgentId, mode: 'manual' });
    },
    handleOpenAssets(deviceId) {
      this.selectedDeviceIdForAssets = deviceId || '';
      this.assetsDialogVisible = true;
    },
    submitRemark(row) {
      if (row._submitting) return;

      const text = (row.remark || '').trim();
      if (text.length > 64) {
        this.$message.warning(this.$t('device.remarkTooLong'));
        return;
      }
      if (text === row._originalRemark) {
        return;
      }

      row._submitting = true;
      this.updateDeviceInfo(row.device_id, { alias: text }, (ok, resp) => {
        if (ok) {
          row._originalRemark = text;
          this.$message.success(this.$t('device.remarkSaved'));
        } else {
          row.remark = row._originalRemark;
          this.$message.error(resp.msg || this.$t('device.remarkSaveFailed'));
        }
        row._submitting = false;
      });
    },
    // 备注输入框：失焦时提交
    onRemarkBlur(row) {
      row.isEdit = false;
      setTimeout(() => {
        this.submitRemark(row);
      }, 100); // 延迟 100ms，避开 enter+blur 同时触发的窗口
    },
    // 备注输入框：按回车时提交
    onRemarkEnter(row) {
      row.isEdit = false;
      this.submitRemark(row);
    },
    handleUnbind(device_id) {
      this.$confirm(this.$t('device.confirmUnbind'), this.$t('message.warning'), {
        confirmButtonText: this.$t('button.ok'),
        cancelButtonText: this.$t('button.cancel'),
        type: 'warning'
      }).then(() => {
        Api.device.unbindDevice(device_id, ({ data }) => {
          if (data.code === 0) {
            this.$message.success({
              message: this.$t('device.unbindSuccess'),
              showClose: true
            });
            this.fetchBindDevices(this.$route.query.agentId);
          } else {
            this.$message.error({
              message: data.msg || this.$t('device.unbindFailed'),
              showClose: true
            });
          }
        });
      });
    },
    goFirst() {
      this.currentPage = 1;
    },
    goPrev() {
      if (this.currentPage > 1) this.currentPage--;
    },
    goNext() {
      if (this.currentPage < this.pageCount) this.currentPage++;
    },
    goToPage(page) {
      this.currentPage = page;
    },

    fetchBindDevices(agentId) {
      this.loading = true;
      this.loadFailed = false;
      Api.device.getAgentBindDevices(agentId, ({ data }) => {
        this.loading = false;
        if (data.code === 0) {
          this.deviceList = data.data.map(device => {
            return {
              device_id: device.id,
              model: device.board,
              firmwareVersion: device.appVersion,
              macAddress: device.macAddress,
              bindTime: device.createDate,
              lastConversation: device.lastConnectedAt,
              remark: device.alias,
              _originalRemark: device.alias,
              isEdit: false,
              _submitting: false,
              rawBindTime: new Date(device.createDate).getTime(),
              selected: false,
            };
          })
            .sort((a, b) => a.rawBindTime - b.rawBindTime);
          this.activeSearchKeyword = "";
          this.searchKeyword = "";
        } else {
          this.loadFailed = true;
          this.$message.error(data.msg || this.$t('device.getListFailed'));
        }
      });
    },

    headerCellClassName({ columnIndex }) {
      if (columnIndex === 0) {
        return "custom-selection-header";
      }
      return "";
    },
    getFirmwareTypeName(type) {
      const firmwareType = this.firmwareTypes.find(item => item.key === type)
      return firmwareType ? firmwareType.name : type
    },
    updateDeviceInfo(device_id, payload, callback) {
      return Api.device.updateDeviceInfo(device_id, payload, ({ data }) => {
        callback(data.code === 0, data);
      })
    },
  }
};
</script>

<style scoped>
.dm-agent { display: inline-flex; align-items: center; gap: 8px; }
.dm-agent .el-select { width: 220px; }
.dm-opt-count { float: right; margin-left: 16px; color: var(--xn-ink-3); font-size: 12px; }
.dm-search-icon { height: 100%; margin: 0 2px 0 4px; font-size: 16px; color: var(--xn-ink-3); }
.dm-panel { overflow: hidden; }
.dm-remark { display: inline-flex; align-items: center; gap: 6px; max-width: 100%; padding: 4px 6px; margin-left: -6px; border: 0; border-radius: 6px; background: none; color: var(--xn-ink); font: inherit; font-weight: 500; cursor: pointer; text-align: left; }
.dm-remark:hover { background: var(--xn-mist-2); }
.dm-remark__icon { color: var(--xn-ink-4); }
.dm-remark:hover .dm-remark__icon { color: var(--xn-lake); }
.dm-panel ::v-deep .dm-nowrap .cell { white-space: nowrap; }
.dm-danger { color: var(--xn-danger); }
.dm-danger:hover, .dm-danger:focus { color: #8D3523; }
.dm-foot { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; padding: 4px 16px 14px; border-top: 1px solid var(--xn-line-2); }
.dm-note { display: inline-flex; align-items: center; gap: 6px; padding-top: 10px; font-size: 13px; }
@media (max-width: 760px) { .dm-agent, .dm-agent .el-select { width: 100%; } }
</style>
