<template>
  <div class="xn-page home">
    <page-header :title="$t('xn.home.title')">
      <template #description>
        <span class="home-stats">
          <span>{{ $t('xn.home.agents', { n: agents.length }) }}</span>
          <span class="home-stats__bound">{{ $t('xn.home.bound', { n: totalBound }) }}</span>
          <span class="home-stats__online">
            {{ $t('xn.home.online') }}：<strong>{{ $t('xn.home.onlineUnknown') }}</strong>
            <el-tooltip :content="$t('xn.home.onlineHint')" placement="bottom" popper-class="xn-tip-wide">
              <button type="button" class="home-hint" :aria-label="$t('xn.home.onlineHint')"><xn-icon name="info" /></button>
            </el-tooltip>
          </span>
        </span>
      </template>
      <el-button type="primary" @click="showAddDialog"><xn-icon name="plus" /> {{ $t('home.addAgent') }}</el-button>
    </page-header>

    <div class="xn-toolbar">
      <el-input v-model.trim="keyword" clearable :placeholder="$t('xn.home.searchPlaceholder')" class="home-search">
        <xn-icon slot="prefix" name="search" class="home-search__icon" />
      </el-input>
      <el-radio-group v-model="filter" size="medium" class="home-filter">
        <el-radio-button label="all">{{ $t('xn.home.filterAll') }} <span class="xn-num">{{ counts.all }}</span></el-radio-button>
        <el-radio-button label="bound">{{ $t('xn.home.filterBound') }} <span class="xn-num">{{ counts.bound }}</span></el-radio-button>
        <el-radio-button label="unbound">{{ $t('xn.home.filterUnbound') }} <span class="xn-num">{{ counts.unbound }}</span></el-radio-button>
      </el-radio-group>
      <span class="xn-toolbar__grow"></span>
      <div class="home-view" role="group">
        <el-tooltip :content="$t('xn.home.viewCards')" placement="top">
          <button type="button" class="home-view__btn" :class="{ 'is-on': view === 'card' }" :aria-pressed="String(view === 'card')"
            :aria-label="$t('xn.home.viewCards')" @click="setView('card')"><xn-icon name="grid" /></button>
        </el-tooltip>
        <el-tooltip :content="$t('xn.home.viewList')" placement="top">
          <button type="button" class="home-view__btn" :class="{ 'is-on': view === 'list' }" :aria-pressed="String(view === 'list')"
            :aria-label="$t('xn.home.viewList')" @click="setView('list')"><xn-icon name="list" /></button>
        </el-tooltip>
      </div>
    </div>

    <!-- 加载中：骨架 -->
    <div v-if="isLoading" class="home-grid">
      <div v-for="i in skeletonCount" :key="'sk' + i" class="home-skel" aria-hidden="true">
        <div class="home-skel__row"><span class="home-skel__ava"></span><span class="home-skel__line w40"></span></div>
        <span class="home-skel__line"></span><span class="home-skel__line w70"></span><span class="home-skel__block"></span>
      </div>
    </div>

    <div v-else-if="loadFailed" class="xn-panel"><xn-empty error @retry="fetchAgentList" /></div>

    <div v-else-if="!agents.length" class="xn-panel">
      <xn-empty icon="agent" :title="$t('xn.home.emptyTitle')" :description="$t('xn.home.emptyDesc')">
        <el-button type="primary" @click="showAddDialog"><xn-icon name="plus" /> {{ $t('home.addAgent') }}</el-button>
      </xn-empty>
    </div>

    <div v-else-if="!devices.length" class="xn-panel">
      <xn-empty icon="search" :title="$t('xn.home.noMatchTitle')" :description="$t('xn.home.noMatchDesc')">
        <el-button @click="clearFilters">{{ $t('xn.home.clearFilter') }}</el-button>
      </xn-empty>
    </div>

    <!-- 卡片视图 -->
    <div v-else-if="view === 'card'" class="home-grid">
      <DeviceItem v-for="item in devices" :key="item.agentId" :device="item"
        @delete="handleDeleteAgent" @chat-history="handleShowChatHistory" @bind="openBind" />
    </div>

    <!-- 列表视图：信息密集时用表格 -->
    <div v-else class="xn-panel xn-panel--flush home-table">
      <el-table :data="devices" row-key="agentId">
        <el-table-column :label="$t('xn.home.colAgent')" min-width="220">
          <template slot-scope="{ row }">
            <div class="home-agent">
              <span class="home-agent__ava" aria-hidden="true">{{ Array.from(row.agentName || '?')[0] }}</span>
              <div class="home-agent__text">
                <router-link :to="{ path: '/role-config', query: { agentId: row.agentId } }" class="home-agent__name xn-clip">{{ row.agentName }}</router-link>
                <span class="xn-muted home-agent__mem xn-clip">{{ row.memName }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column :label="$t('xn.home.colModel')" min-width="170" show-overflow-tooltip prop="llmModelName" />
        <el-table-column :label="$t('xn.home.colVoice')" min-width="170">
          <template slot-scope="{ row }">
            <div class="xn-clip">{{ row.ttsVoiceName || '—' }}</div>
            <div class="xn-muted xn-clip home-small">{{ row.ttsModelName }}</div>
          </template>
        </el-table-column>
        <el-table-column :label="$t('xn.home.colDevices')" min-width="130">
          <template slot-scope="{ row }">
            <span v-if="row.deviceCount > 0" class="xn-tag xn-tag--lake"><i class="dot"></i>{{ $t('xn.home.boundN', { n: row.deviceCount }) }}</span>
            <el-button v-else type="text" @click="openBind(row.agentId)">{{ $t('xn.home.bindDevice') }}</el-button>
          </template>
        </el-table-column>
        <el-table-column :label="$t('xn.home.colLast')" min-width="130">
          <template slot-scope="{ row }">{{ relTime(row.lastConnectedAt) }}</template>
        </el-table-column>
        <el-table-column :label="$t('xn.home.colActions')" min-width="330" align="right">
          <template slot-scope="{ row }">
            <div class="home-row-actions">
              <el-button type="primary" size="mini" @click="$router.push({ path: '/role-config', query: { agentId: row.agentId } })">{{ $t('home.configureRole') }}</el-button>
              <el-button type="text" @click="$router.push({ path: '/device-management', query: { agentId: row.agentId } })">{{ $t('xn.home.devices') }}</el-button>
              <el-button type="text" @click="$router.push({ path: '/unified-user-management', query: { agentId: row.agentId } })">{{ $t('xn.home.identities') }}</el-button>
              <el-tooltip :disabled="row.memModelId !== 'Memory_nomem'" :content="$t('home.enableMemory')" placement="top">
                <span><el-button type="text" :disabled="row.memModelId === 'Memory_nomem'"
                  @click="handleShowChatHistory({ agentId: row.agentId, agentName: row.agentName })">{{ $t('home.chatHistory') }}</el-button></span>
              </el-tooltip>
              <el-tooltip :content="$t('xn.home.deleteAgent')" placement="top">
                <button type="button" class="home-del" :aria-label="$t('xn.home.deleteAgent')" @click="handleDeleteAgent(row.agentId)"><xn-icon name="trash" /></button>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <chat-history-dialog :visible.sync="showChatHistory" :agent-id="currentAgentId" :agent-name="currentAgentName" />
    <AwakeningWizard :visible.sync="showCreateWizard" mode="create" @success="handleCreateAgentSuccess" />
  </div>
</template>

<script>
import Api from '@/apis/api';
import AwakeningWizard from '@/components/AwakeningWizard.vue';
import ChatHistoryDialog from '@/components/ChatHistoryDialog.vue';
import DeviceItem, { relativeTime } from '@/components/DeviceItem.vue';

const VIEW_KEY = 'xn.home.view';   // 只记界面偏好（卡片 / 列表），不含任何账号数据
const norm = (v) => String(v == null ? '' : v).toLowerCase().replace(/[\s:：-]/g, '');

export default {
  name: 'HomePage',
  components: { DeviceItem, AwakeningWizard, ChatHistoryDialog },
  data() {
    let view = 'card';
    try { view = localStorage.getItem(VIEW_KEY) === 'list' ? 'list' : 'card'; } catch (e) { /* ignore */ }
    return {
      showCreateWizard: false,
      originalDevices: [],      // /agent/list 原始行（字段名沿用原页面：每一行是一个智能体）
      deviceMap: {},            // agentId → 绑定设备列表（/device/bind/{agentId}）
      memNames: {},             // 记忆模型 id → 名称（/models/names?modelType=Memory）
      boardNames: {},           // 固件类型 key → 名称（字典 FIRMWARE_TYPE）
      keyword: '',
      filter: 'all',
      view,
      isLoading: true,
      loadFailed: false,
      skeletonCount: 4,
      showChatHistory: false,
      currentAgentId: '',
      currentAgentName: '',
    };
  },
  computed: {
    agents() {
      return this.originalDevices.map((a) => ({
        ...a,
        memName: this.memNames[a.memModelId] || '',
        devices: (this.deviceMap[a.agentId] || null) && this.deviceMap[a.agentId].map((d) => ({ ...d, boardName: this.boardNames[d.board] })),
      }));
    },
    searched() {
      const q = norm(this.keyword);
      if (!q) return this.agents;
      return this.agents.filter((a) => norm(a.agentName).includes(q)
        || (a.devices || []).some((d) => norm(d.alias).includes(q) || norm(d.macAddress).includes(q)));
    },
    counts() {
      const bound = this.searched.filter((a) => Number(a.deviceCount) > 0).length;
      return { all: this.searched.length, bound, unbound: this.searched.length - bound };
    },
    /** 页面展示的智能体（沿用原变量名 devices） */
    devices() {
      if (this.filter === 'bound') return this.searched.filter((a) => Number(a.deviceCount) > 0);
      if (this.filter === 'unbound') return this.searched.filter((a) => !(Number(a.deviceCount) > 0));
      return this.searched;
    },
    totalBound() {
      return this.originalDevices.reduce((n, a) => n + (Number(a.deviceCount) || 0), 0);
    },
  },
  watch: {
    '$route.query.create': {
      immediate: true,
      handler(v) {
        if (v === '1') {
          this.showCreateWizard = true;
          this.$router.replace({ path: '/home' }).catch(() => {});
        }
      },
    },
  },
  mounted() {
    this.fetchAgentList();
    this.fetchMemoryNames();
    this.fetchBoardNames();
    this.$eventBus.$on('xn:devices-changed', this.fetchAgentList);
  },
  beforeDestroy() {
    this.$eventBus.$off('xn:devices-changed', this.fetchAgentList);
  },
  methods: {
    persistCurrentAgentId(agentId) {
      try { if (agentId) localStorage.setItem('currentAgentId', String(agentId)); } catch (e) { /* ignore */ }
    },
    relTime(v) { return relativeTime(this, v); },
    setView(v) {
      this.view = v;
      try { localStorage.setItem(VIEW_KEY, v); } catch (e) { /* ignore */ }
    },
    clearFilters() {
      this.keyword = '';
      this.filter = 'all';
    },
    showAddDialog() {
      this.showCreateWizard = true;
    },
    openBind(agentId) {
      this.$eventBus.$emit('xn:open-bind', { agentId });
    },
    handleCreateAgentSuccess() {
      this.fetchAgentList();
      this.$eventBus.$emit('xn:devices-changed');
    },
    // 获取智能体列表（原逻辑：无智能体时自动弹出创建向导）
    fetchAgentList() {
      this.isLoading = !this.originalDevices.length;
      this.loadFailed = false;
      Api.agent.getAgentList(({ data }) => {
        if (data && data.code === 0 && Array.isArray(data.data)) {
          this.originalDevices = data.data.map((item) => ({ ...item, agentId: item.id }));
          this.skeletonCount = Math.min(Math.max(this.originalDevices.length, 2), 6);
          if (this.originalDevices.length > 0) {
            if (!localStorage.getItem('currentAgentId')) this.persistCurrentAgentId(this.originalDevices[0].agentId);
            this.fetchBoundDevices();
          } else {
            this.showCreateWizard = true;
          }
        } else {
          this.loadFailed = true;
          if (data && data.msg) this.$message.error(data.msg);
        }
        this.isLoading = false;
      });
    },
    /** 每个智能体的绑定设备，用于卡片里的设备行与按 MAC / 备注搜索 */
    fetchBoundDevices() {
      this.originalDevices.forEach((a) => {
        if (!(Number(a.deviceCount) > 0)) { this.$set(this.deviceMap, a.agentId, []); return; }
        Api.device.getAgentBindDevices(a.agentId, ({ data }) => {
          if (data && data.code === 0) this.$set(this.deviceMap, a.agentId, data.data || []);
        });
      });
    },
    fetchMemoryNames() {
      Api.model.getModelNames('Memory', '', ({ data }) => {
        if (data && data.code === 0) {
          this.memNames = (data.data || []).reduce((m, x) => { m[x.id] = x.modelName; return m; }, {});
        }
      });
    },
    async fetchBoardNames() {
      try {
        const res = await Api.dict.getDictDataByType('FIRMWARE_TYPE');
        this.boardNames = (res.data || []).reduce((m, x) => { m[x.key] = x.name; return m; }, {});
      } catch (e) { /* 读不到型号名称时显示原始型号 */ }
    },
    handleDeleteAgent(agentId) {
      const a = this.originalDevices.find((x) => x.agentId === agentId) || {};
      const n = Number(a.deviceCount) || 0;
      const msg = n > 0
        ? this.$t('xn.home.deleteConfirm', { name: a.agentName, n })
        : this.$t('xn.home.deleteConfirmNoDevice', { name: a.agentName });
      this.$confirm(msg, this.$t('xn.home.deleteAgent'), {
        confirmButtonText: this.$t('xn.home.deleteAgent'),
        cancelButtonText: this.$t('button.cancel'),
        type: 'warning',
      }).then(() => {
        Api.agent.deleteAgent(agentId, (res) => {
          if (res.data.code === 0) {
            this.$message.success({ message: this.$t('home.deleteSuccess'), showClose: true });
            this.fetchAgentList();
            this.$eventBus.$emit('xn:devices-changed');
          } else {
            this.$message.error({ message: res.data.msg || this.$t('home.deleteFailed'), showClose: true });
          }
        });
      }).catch(() => {});
    },
    handleShowChatHistory({ agentId, agentName }) {
      this.persistCurrentAgentId(agentId);
      this.currentAgentId = agentId;
      this.currentAgentName = agentName;
      this.showChatHistory = true;
    },
  },
};
</script>

<style scoped>
.home-stats { display: inline-flex; flex-wrap: wrap; align-items: center; gap: 6px 16px; }
.home-stats__bound { color: var(--xn-lake-ink); font-weight: 500; }
.home-stats__online strong { font-weight: 500; color: var(--xn-ink-2); }
.home-hint { display: inline-grid; place-items: center; width: 22px; height: 22px; margin-left: 2px; padding: 0; border: 0; border-radius: 50%; background: none; color: var(--xn-ink-3); font-size: 15px; cursor: help; vertical-align: -5px; }
.home-hint:hover { color: var(--xn-ink); }

.home-search { width: 320px; }
.home-search__icon { margin: 0 2px 0 4px; height: 100%; font-size: 16px; color: var(--xn-ink-3); }
.home-filter .xn-num { margin-left: 4px; opacity: 0.7; }
.home-view { display: inline-flex; padding: 3px; border-radius: 10px; background: var(--xn-mist); }
.home-view__btn { display: grid; place-items: center; width: 34px; height: 34px; border: 0; border-radius: 8px; background: none; color: var(--xn-ink-3); font-size: 17px; cursor: pointer; }
.home-view__btn.is-on { background: #fff; color: var(--xn-ink); box-shadow: 0 1px 2px rgba(30, 43, 64, 0.08); }

.home-grid { display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); }

.home-skel { padding: 20px; background: #fff; border: 1px solid var(--xn-line); border-radius: var(--xn-r-lg); }
.home-skel__row { display: flex; align-items: center; gap: 12px; margin-bottom: 16px; }
.home-skel__ava { width: 44px; height: 44px; border-radius: 50%; background: var(--xn-mist); }
.home-skel__line { display: block; height: 12px; margin-bottom: 10px; border-radius: 6px; background: var(--xn-mist); }
.home-skel__line.w40 { width: 40%; margin: 0; }
.home-skel__line.w70 { width: 70%; }
.home-skel__block { display: block; height: 76px; margin-top: 14px; border-radius: var(--xn-r); background: var(--xn-mist-2); }

.home-table { overflow: hidden; }
.home-agent { display: flex; align-items: center; gap: 10px; min-width: 0; }
.home-agent__ava { display: grid; place-items: center; flex: none; width: 34px; height: 34px; border-radius: 50%; background: var(--xn-lake-soft); color: var(--xn-lake-ink); font: 600 15px/1 var(--xn-serif); }
.home-agent__text { display: flex; flex-direction: column; min-width: 0; }
.home-agent__name { font: 600 15px/1.4 var(--xn-serif); color: var(--xn-ink); }
.home-agent__name:hover { color: var(--xn-lake); }
.home-agent__mem, .home-small { font-size: 12px; }
.home-row-actions { display: inline-flex; align-items: center; gap: 2px 12px; flex-wrap: wrap; justify-content: flex-end; }
.home-row-actions .el-button + .el-button { margin-left: 0; }
.home-del { display: inline-grid; place-items: center; width: 30px; height: 30px; border: 0; border-radius: var(--xn-r); background: none; color: var(--xn-ink-3); font-size: 17px; cursor: pointer; }
.home-del:hover { background: var(--xn-danger-soft); color: var(--xn-danger); }
.dot { width: 6px; height: 6px; border-radius: 50%; background: currentColor; }

@media (max-width: 640px) {
  .home-search { width: 100%; }
  .home-grid { grid-template-columns: 1fr; }
}
</style>

<style>
.xn-tip-wide { max-width: 320px; line-height: 1.6; }
</style>
