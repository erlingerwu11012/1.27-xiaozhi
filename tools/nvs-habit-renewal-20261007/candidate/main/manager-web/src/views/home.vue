<template>
  <div class="home-page">
    <div class="welcome opal-dashboard">
    <HeaderBar :devices="devices" @search="handleSearch" @search-reset="handleSearchReset" />

    <el-main class="opal-main">
      <div>
        <!-- 首页内容：欢迎横幅 -->
        <div class="add-device glass-panel opal-hero">
          <div class="add-device-bg">
            <div class="hellow-text">
              {{ $t('home.greeting') }}
            </div>
            <div class="hellow-text sub">
              {{ $t('home.wish') }}
            </div>
            <div class="hi-hint">
              let's have a wonderful day!
            </div>
            <button type="button" class="modern-add-btn" @click="showAddDialog">
              <span>{{ $t('home.addAgent') }}</span>
              <i class="el-icon-right"></i>
            </button>
          </div>
        </div>

        <!-- 智能体列表 -->
        <div class="device-list-container">
          <template v-if="isLoading">
            <div v-for="i in skeletonCount" :key="'skeleton-' + i" class="skeleton-item">
              <div class="skeleton-image"></div>
              <div class="skeleton-content">
                <div class="skeleton-line"></div>
                <div class="skeleton-line-short"></div>
              </div>
            </div>
          </template>

          <template v-else>
            <DeviceItem v-for="(item, index) in devices" :key="index" :device="item" @configure="goToRoleConfig"
              @deviceManage="handleDeviceManage" @delete="handleDeleteAgent" @chat-history="handleShowChatHistory" />
          </template>
        </div>
      </div>
    </el-main>
    <el-footer>
      <version-footer />
    </el-footer>
    <chat-history-dialog :visible.sync="showChatHistory" :agent-id="currentAgentId" :agent-name="currentAgentName" />
    </div>
    <AwakeningWizard
      :visible.sync="showCreateWizard"
      mode="create"
      @success="handleCreateAgentSuccess"
    />
  </div>
</template>

<script>
import Api from '@/apis/api';
import AwakeningWizard from '@/components/AwakeningWizard.vue';
import ChatHistoryDialog from '@/components/ChatHistoryDialog.vue';
import DeviceItem from '@/components/DeviceItem.vue';
import HeaderBar from '@/components/HeaderBar.vue';
import VersionFooter from '@/components/VersionFooter.vue';

export default {
  name: 'HomePage',
  components: { DeviceItem, AwakeningWizard, HeaderBar, VersionFooter, ChatHistoryDialog },
  data() {
    return {
      showCreateWizard: false,
      devices: [],
      originalDevices: [],
      isSearching: false,
      searchRegex: null,
      isLoading: true,
      skeletonCount: localStorage.getItem('skeletonCount') || 8,
      showChatHistory: false,
      currentAgentId: '',
      currentAgentName: ''
    }
  },

  mounted() {
    this.fetchAgentList();
  },

  methods: {
    persistCurrentAgentId(agentId) {
      try {
        if (agentId) {
          localStorage.setItem('currentAgentId', String(agentId));
        }
      } catch (e) {
        // ignore storage errors
      }
    },
    showAddDialog() {
      this.showCreateWizard = true;
    },
    goToRoleConfig() {
      // 点击配置角色后跳转到角色配置页
      this.$router.push('/role-config')
    },
    handleCreateAgentSuccess() {
      this.fetchAgentList();
    },
    handleDeviceManage() {
      this.$router.push('/device-management');
    },
    handleSearch(regex) {
      this.isSearching = true;
      this.searchRegex = regex;
      this.applySearchFilter();
    },
    handleSearchReset() {
      this.isSearching = false;
      this.searchRegex = null;
      this.devices = [...this.originalDevices];
    },
    applySearchFilter() {
      if (!this.isSearching || !this.searchRegex) {
        this.devices = [...this.originalDevices];
        return;
      }

      this.devices = this.originalDevices.filter(device => {
        return this.searchRegex.test(device.agentName);
      });
    },
    // 搜索更新智能体列表
    handleSearchResult(filteredList) {
      this.devices = filteredList; // 更新设备列表
    },
    // 获取智能体列表
    fetchAgentList() {
      this.isLoading = true;
      Api.agent.getAgentList(({ data }) => {
        if (data?.data) {
          this.originalDevices = data.data.map(item => ({
            ...item,
            agentId: item.id
          }));

          // 动态设置骨架屏数量（可选）
          this.skeletonCount = Math.min(
            Math.max(this.originalDevices.length, 3), // 最少3个
            10 // 最多10个
          );

          this.handleSearchReset();

          // 兜底：如果还没有 currentAgentId，则默认选择第一个智能体
          if (this.originalDevices.length > 0) {
            const firstId = this.originalDevices[0].agentId;
            const stored = localStorage.getItem('currentAgentId');
            if (!stored) {
              this.persistCurrentAgentId(firstId);
            }
          } else {
            // 首次注册：用户无智能体时，自动弹出创建向导（每个用户仅此一次，创建后即有智能体，不再自动弹出）
            this.showCreateWizard = true;
          }
        }
        this.isLoading = false;
      }, (error) => {
        console.error('Failed to fetch agent list:', error);
        this.isLoading = false;
      });
    },
    // 删除智能体
    handleDeleteAgent(agentId) {
      this.$confirm(this.$t('home.confirmDeleteAgent'), '提示', {
        confirmButtonText: this.$t('button.ok'),
        cancelButtonText: this.$t('button.cancel'),
        type: 'warning'
      }).then(() => {
        Api.agent.deleteAgent(agentId, (res) => {
          if (res.data.code === 0) {
            this.$message.success({
              message: this.$t('home.deleteSuccess'),
              showClose: true
            });
            this.fetchAgentList(); // 刷新列表
          } else {
            this.$message.error({
              message: res.data.msg || this.$t('home.deleteFailed'),
              showClose: true
            });
          }
        });
      }).catch(() => { });
    },
    handleShowChatHistory({ agentId, agentName }) {
      this.persistCurrentAgentId(agentId);
      this.currentAgentId = agentId;
      this.currentAgentName = agentName;
      this.showChatHistory = true;
    }
  }
}
</script>

<style scoped>
.home-page {
  min-height: 100vh;
  background: #f5f7fb;
  position: relative;
}

.opal-dashboard {
  min-width: 900px;
  min-height: 506px;
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: transparent;
  position: relative;
  overflow: hidden;
  color: #1a1a2e;
}

.opal-main {
  padding: 16px 32px;
  display: flex;
  flex-direction: column;
}

/* 头部直接作为根容器第一子元素，位置与其余页面完全一致（top:0） */
.opal-dashboard > .header {
  flex: 0 0 auto;
}

/* 统一卡片：白底 + 12px 圆角 + 轻阴影（对齐习惯管理页） */
.glass-panel {
  background: #fff;
  border: none;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  border-radius: 12px;
  pointer-events: auto;
}

/* 欢迎横幅 */
.add-device {
  height: 176px;
  position: relative;
  overflow: hidden;
  margin-bottom: 24px;
}

.opal-hero {
  padding: 26px 32px;
  box-sizing: border-box;
}

.add-device-bg {
  width: 100%;
  height: 100%;
  text-align: left;
  position: relative;
  box-sizing: border-box;
  pointer-events: auto;
}

.hellow-text {
  margin-left: 0;
  color: #1a1a2e;
  font-size: 26px;
  font-weight: 600;
  letter-spacing: 0;
}

.hellow-text.sub {
  margin-top: 6px;
  font-size: 18px;
  color: #6b7280;
  font-weight: 500;
}

.hi-hint {
  font-weight: 400;
  font-size: 13px;
  text-align: left;
  color: #9ca3af;
  margin-left: 0;
  margin-top: 8px;
}

.modern-add-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 36px;
  padding: 0 18px;
  margin-left: 0;
  margin-top: 18px;
  background: #4f6ef6;
  border: none;
  border-radius: 8px;
  color: #fff;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.2s ease;
}

.modern-add-btn:hover {
  background: #3a5bd9;
}

.modern-add-btn .el-icon-right {
  font-size: 14px;
}

.hero-illustration {
  position: absolute;
  right: -20px;
  bottom: -10px;
  width: 260px;
  pointer-events: none;
  opacity: 0.95;
}

.device-list-container {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 20px;
  padding: 24px 0;
}

/* 在 DeviceItem.vue 的样式中 */
.device-item {
  margin: 0 !important;
  /* 避免冲突 */
  width: auto !important;
}

.footer {
  font-size: 12px;
  font-weight: 400;
  margin-top: auto;
  padding-top: 30px;
  color: #9ca3af;
  text-align: center;
  /* 居中显示 */
}

/* 骨架屏动画 */
@keyframes shimmer {
  100% {
    transform: translateX(100%);
  }
}

.skeleton-item {
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  padding: 20px;
  height: 120px;
  position: relative;
  overflow: hidden;
  margin-bottom: 20px;
}

.skeleton-image {
  width: 80px;
  height: 80px;
  background: #f0f2f5;
  border-radius: 4px;
  float: left;
  position: relative;
  overflow: hidden;
}

.skeleton-content {
  margin-left: 100px;
}

.skeleton-line {
  height: 16px;
  background: #f0f2f5;
  border-radius: 4px;
  margin-bottom: 12px;
  width: 70%;
  position: relative;
  overflow: hidden;
}

.skeleton-line-short {
  height: 12px;
  background: #f0f2f5;
  border-radius: 4px;
  width: 50%;
}

.skeleton-item::after {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 50%;
  height: 100%;
  background: linear-gradient(90deg,
      rgba(255, 255, 255, 0),
      rgba(255, 255, 255, 0.3),
      rgba(255, 255, 255, 0));
  animation: shimmer 1.5s infinite;
}
</style>