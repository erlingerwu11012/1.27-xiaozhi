<template>
  <div class="xn-shell" :class="{ 'is-nav-open': navOpen }">
    <!-- 侧栏 -->
    <aside class="xn-side" :aria-label="$t('xn.nav.menu')">
      <router-link to="/home" class="xn-brand" @click.native="navOpen = false">
        <span class="xn-brand__mark" aria-hidden="true"><i></i></span>
        <span class="xn-brand__name">{{ $t('xn.brand') }}</span>
        <span class="xn-brand__sub">{{ $t('xn.brandSub') }}</span>
      </router-link>

      <nav class="xn-nav">
        <section v-for="g in visibleGroups" :key="g.key" class="xn-nav__group" :class="{ 'is-admin': g.adminOnly }">
          <h2 class="xn-nav__head">{{ $t(g.label) }}</h2>
          <router-link v-for="it in g.items" :key="it.key" :to="it.path" class="xn-nav__item"
            :class="{ 'is-on': active.key === it.key && !active.sub }" @click.native="navOpen = false">
            <xn-icon :name="it.icon" class="xn-nav__icon" />
            <span>{{ $t(it.label) }}</span>
            <span v-if="it.key === 'devices' && deviceTotal !== null" class="xn-nav__count xn-num">{{ deviceTotal }}</span>
          </router-link>
          <div v-for="s in g.subs || []" :key="s.key" class="xn-nav__sub">
            <button type="button" class="xn-nav__item xn-nav__toggle" :aria-expanded="String(isSubOpen(s.key))"
              @click="toggleSub(s.key)">
              <xn-icon :name="s.icon" class="xn-nav__icon" />
              <span>{{ $t(s.label) }}</span>
              <xn-icon name="chevronDown" class="xn-nav__caret" />
            </button>
            <div v-show="isSubOpen(s.key)" class="xn-nav__subitems">
              <router-link v-for="it in s.items" :key="it.key" :to="it.path" class="xn-nav__item xn-nav__item--sub"
                :class="{ 'is-on': active.key === it.key }" @click.native="navOpen = false">{{ $t(it.label) }}</router-link>
            </div>
          </div>
        </section>
      </nav>

      <div class="xn-side__foot">
        <button v-if="mock" type="button" class="xn-mockbtn" @click="mockPanel = true">
          <span class="xn-tag xn-tag--demo">{{ $t('xn.mock.badge') }}</span>
          <span>{{ $t('xn.mock.title') }}</span>
        </button>
        <version-footer class="xn-side__version" />
      </div>
    </aside>
    <div class="xn-scrim" @click="navOpen = false"></div>

    <!-- 主区 -->
    <div class="xn-main">
      <header class="xn-top">
        <button type="button" class="xn-iconbtn xn-top__menu" :aria-label="$t('xn.nav.menu')" @click="navOpen = true">
          <xn-icon name="menu" size="20" />
        </button>
        <nav class="xn-crumb" aria-label="breadcrumb">
          <span v-if="crumb.group" class="xn-crumb__group">{{ $t(crumb.group) }}</span>
          <template v-if="crumb.parentLabel">
            <span class="xn-crumb__sep">/</span>
            <router-link :to="crumb.parentPath" class="xn-crumb__link">{{ $t(crumb.parentLabel) }}</router-link>
          </template>
          <template v-if="crumb.item">
            <span class="xn-crumb__sep">/</span>
            <span class="xn-crumb__here">{{ $t(crumb.item) }}</span>
          </template>
        </nav>

        <div class="xn-top__right">
          <el-button class="xn-top__add" @click="openBind()">
            <xn-icon name="plus" /> {{ $t('xn.top.addDevice') }}
          </el-button>

          <router-link to="/billing/packages" class="xn-balance" :class="'is-' + balanceState"
            :title="balanceTitle">
            <xn-icon name="wallet" />
            <template v-if="balanceState === 'loading'"><span class="xn-muted">{{ $t('xn.top.balanceLoading') }}</span></template>
            <template v-else-if="balanceState === 'unavailable'"><span>{{ $t('xn.top.balanceUnavailable') }}</span></template>
            <template v-else>
              <span class="xn-balance__num xn-num">{{ formatPoints(quota.balance) }}</span>
              <span class="xn-balance__unit">{{ $t('billing.pointsUnit') }}</span>
              <span v-if="balanceState === 'stale'" class="xn-balance__flag">{{ $t('xn.top.balanceStale') }}</span>
            </template>
            <span v-if="mock" class="xn-balance__demo">{{ $t('xn.mock.badge') }}</span>
          </router-link>

          <el-dropdown trigger="click" placement="bottom-end" @command="onAccount">
            <button type="button" class="xn-account">
              <span class="xn-account__dot" aria-hidden="true">{{ initial }}</span>
              <span class="xn-account__name xn-clip">{{ userInfo.username || '…' }}</span>
              <xn-icon name="chevronDown" class="xn-muted" />
            </button>
            <el-dropdown-menu slot="dropdown" class="xn-account-menu">
              <li class="xn-account-menu__head">
                <span class="xn-muted">{{ $t('xn.top.signedInAs') }}</span>
                <strong class="xn-clip">{{ userInfo.username }}</strong>
                <span v-if="isSuperAdmin" class="xn-tag xn-tag--lake">{{ $t('xn.top.admin') }}</span>
              </li>
              <el-dropdown-item command="packages"><xn-icon name="wallet" /> {{ $t('xn.top.recharge') }}</el-dropdown-item>
              <el-dropdown-item command="orders"><xn-icon name="receipt" /> {{ $t('xn.top.orders') }}</el-dropdown-item>
              <el-dropdown-item divided disabled class="xn-account-menu__label"><xn-icon name="globe" /> {{ $t('xn.top.language') }}</el-dropdown-item>
              <el-dropdown-item v-for="l in languages" :key="l.value" :command="'lang:' + l.value"
                class="xn-account-menu__lang" :class="{ 'is-on': l.value === $i18n.locale }">
                {{ l.label }}<xn-icon v-if="l.value === $i18n.locale" name="check" />
              </el-dropdown-item>
              <el-dropdown-item divided command="password"><xn-icon name="lock" /> {{ $t('header.changePassword') }}</el-dropdown-item>
              <el-dropdown-item command="logout" class="xn-account-menu__danger"><xn-icon name="logout" /> {{ $t('header.logout') }}</el-dropdown-item>
            </el-dropdown-menu>
          </el-dropdown>
        </div>
      </header>

      <main class="xn-content">
        <no-permission v-if="denied" />
        <slot v-else />
      </main>
    </div>

    <device-bind-dialog :visible.sync="bindVisible" :agent-id="bindAgentId" :mode="bindMode" @bound="onDevicesChanged" />
    <change-password-dialog v-model="passwordVisible" />
    <mock-panel v-if="mock" :visible.sync="mockPanel" :is-admin="isSuperAdmin" />
  </div>
</template>

<script>
import Api from '@/apis/api';
import { changeLanguage } from '@/i18n';
import { isMockMode } from '@/mock/config';
import { NAV_GROUPS, locate } from '@/config/navigation';
import ChangePasswordDialog from '@/components/ChangePasswordDialog.vue';
import DeviceBindDialog from '@/components/DeviceBindDialog.vue';
import VersionFooter from '@/components/VersionFooter.vue';
import NoPermission from './NoPermission.vue';

export default {
  name: 'AppLayout',
  components: {
    ChangePasswordDialog, DeviceBindDialog, VersionFooter, NoPermission,
    // 构建期常量：real 构建时整段剔除，演示面板与演示数据不会进入正式包
    MockPanel: process.env.VUE_APP_DATA_MODE !== 'real' ? () => import('./MockPanel.vue') : { render: () => null },
  },
  data() {
    return {
      navOpen: false,
      openSubs: {},
      userInfo: {},
      quota: null,
      quotaFailed: false,
      deviceTotal: null,
      bindVisible: false,
      bindAgentId: '',
      bindMode: 'code',
      passwordVisible: false,
      mockPanel: false,
      mock: isMockMode(),
      languages: [
        { value: 'zh_CN', label: this.$t('language.zhCN') },
        { value: 'zh_TW', label: this.$t('language.zhTW') },
        { value: 'en', label: this.$t('language.en') },
        { value: 'de', label: this.$t('language.de') },
        { value: 'vi', label: this.$t('language.vi') },
      ],
    };
  },
  computed: {
    isSuperAdmin() { return this.$store.getters.getIsSuperAdmin; },
    visibleGroups() { return NAV_GROUPS.filter((g) => !g.adminOnly || this.isSuperAdmin); },
    active() { return locate(this.$route.path) || {}; },
    crumb() { return this.denied ? {} : (locate(this.$route.path) || {}); },   // 无权限时不显示管理员页面名称
    denied() { return this.$route.meta && this.$route.meta.adminOnly && !this.isSuperAdmin; },
    initial() { return (this.userInfo.username || 'U').slice(0, 1).toUpperCase(); },
    balanceState() {
      if (this.quotaFailed) return 'unavailable';
      if (!this.quota) return 'loading';
      if (this.quota.balance == null || this.quota.balanceSource == null) return 'unavailable';
      if (this.quota.balanceRealtime === false || this.quota.balanceSource === 'cache') return 'stale';
      return 'ok';
    },
    balanceTitle() {
      if (this.balanceState === 'stale') return this.$t('billing.balanceCacheHint');
      if (this.balanceState === 'unavailable') return this.$t('xn.top.balanceUnavailable');
      return this.$t('xn.top.recharge');
    },
  },
  watch: {
    '$route.path': {
      immediate: true,
      handler(path) {
        const loc = locate(path);
        if (loc && loc.sub) this.$set(this.openSubs, loc.sub, true);
        if (/^\/billing/.test(path)) this.fetchQuota();
      },
    },
  },
  created() {
    this.fetchUserInfo();
    this.fetchQuota();
    this.fetchDeviceTotal();
    this.$eventBus.$on('xn:open-bind', this.openBind);
    this.$eventBus.$on('xn:devices-changed', this.fetchDeviceTotal);
    this.$eventBus.$on('xn:quota-changed', this.fetchQuota);
  },
  beforeDestroy() {
    this.$eventBus.$off('xn:open-bind', this.openBind);
    this.$eventBus.$off('xn:devices-changed', this.fetchDeviceTotal);
    this.$eventBus.$off('xn:quota-changed', this.fetchQuota);
  },
  methods: {
    isSubOpen(key) { return !!this.openSubs[key]; },
    toggleSub(key) { this.$set(this.openSubs, key, !this.openSubs[key]); },
    fetchUserInfo() {
      Api.user.getUserInfo(({ data }) => {
        if (data && data.data) {
          this.userInfo = data.data;
          if (data.data.superAdmin !== undefined) this.$store.commit('setUserInfo', data.data);
        }
      });
    },
    fetchQuota() {
      Api.pay.myQuota((res) => {
        if (res && res.code === 0 && res.data) {
          this.quota = res.data;
          this.quotaFailed = false;
        } else {
          // 失败时清空，避免把旧余额当成最新（与原账单页的处理一致）
          this.quota = null;
          this.quotaFailed = true;
        }
      });
    },
    /** 侧栏“设备管理”旁的数字：所有智能体已绑定设备之和（/agent/list 的 deviceCount），不代表在线 */
    fetchDeviceTotal() {
      Api.agent.getAgentList(({ data }) => {
        if (data && Array.isArray(data.data)) {
          this.deviceTotal = data.data.reduce((n, a) => n + (Number(a.deviceCount) || 0), 0);
        }
      });
    },
    formatPoints(v) {
      const n = Number(v);
      return Number.isFinite(n) ? n.toLocaleString('zh-CN', { maximumFractionDigits: 2 }) : '--';
    },
    openBind(payload) {
      this.bindAgentId = (payload && payload.agentId) || '';
      this.bindMode = (payload && payload.mode) || 'code';
      this.bindVisible = true;
    },
    onDevicesChanged(info) {
      this.fetchDeviceTotal();
      this.$eventBus.$emit('xn:devices-changed-done', info);
    },
    onAccount(cmd) {
      if (cmd === 'packages') this.$router.push('/billing/packages');
      else if (cmd === 'orders') this.$router.push('/billing/orders');
      else if (cmd === 'password') this.passwordVisible = true;
      else if (cmd === 'logout') this.logout();
      else if (cmd.indexOf('lang:') === 0) changeLanguage(cmd.slice(5));
    },
    logout() {
      this.$store.dispatch('logout');
    },
  },
};
</script>

<style scoped>
.xn-shell { position: relative; display: flex; min-height: 100vh; }
/* 侧栏本身是 sticky + 100vh；这条底色让长页面下侧栏一列始终延伸到页面底部 */
.xn-shell::before {
  content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: var(--xn-sidebar-w);
  background: #fff; border-right: 1px solid var(--xn-line); pointer-events: none;
}

/* 侧栏 */
.xn-side {
  position: sticky; top: 0; z-index: 40; flex: 0 0 var(--xn-sidebar-w); width: var(--xn-sidebar-w); height: 100vh;
  display: flex; flex-direction: column; background: #fff; border-right: 1px solid var(--xn-line);
}
.xn-brand { display: flex; align-items: baseline; gap: 8px; padding: 22px 22px 18px; color: var(--xn-ink); }
.xn-brand__mark { position: relative; align-self: center; width: 14px; height: 20px; }
.xn-brand__mark::before { content: ""; position: absolute; left: 6px; top: 0; width: 2px; height: 8px; border-radius: 1px; background: var(--xn-lake); }
.xn-brand__mark i { position: absolute; left: 1px; top: 7px; width: 12px; height: 12px; border-radius: 50%; border: 2.5px solid var(--xn-ink); box-sizing: border-box; }
.xn-brand__name { font: 600 21px/1 var(--xn-serif); letter-spacing: 0.04em; }
.xn-brand__sub { font-size: 13px; color: var(--xn-ink-3); }

.xn-nav { flex: 1; overflow-y: auto; padding: 4px 12px 16px; }
.xn-nav__group + .xn-nav__group { margin-top: 18px; }
.xn-nav__group.is-admin { padding-top: 16px; border-top: 1px dashed var(--xn-line); }
.xn-nav__head { margin: 0 0 6px; padding: 0 10px; font-size: 12px; font-weight: 500; color: var(--xn-ink-3); }
.xn-nav__item {
  display: flex; align-items: center; gap: 10px; width: 100%; min-height: 38px; padding: 0 10px;
  border: 0; border-radius: var(--xn-r); background: none; color: var(--xn-ink-2);
  font: inherit; font-size: 14px; text-align: left; cursor: pointer; box-sizing: border-box;
}
.xn-nav__item:hover { background: var(--xn-mist-2); color: var(--xn-ink); }
.xn-nav__item.is-on { background: var(--xn-lake-soft); color: var(--xn-ink); font-weight: 600; }
.xn-nav__item.is-on .xn-nav__icon { color: var(--xn-lake); }
.xn-nav__icon { font-size: 18px; color: var(--xn-ink-3); }
.xn-nav__count { margin-left: auto; font-size: 12px; color: var(--xn-ink-3); }
.xn-nav__caret { margin-left: auto; font-size: 16px; color: var(--xn-ink-3); transition: transform 0.15s ease; }
.xn-nav__toggle[aria-expanded="true"] .xn-nav__caret { transform: rotate(180deg); }
.xn-nav__subitems { padding: 2px 0 4px; }
.xn-nav__item--sub { min-height: 34px; padding-left: 38px; font-size: 13px; }

.xn-side__foot { padding: 12px 16px 14px; border-top: 1px solid var(--xn-line-2); }
.xn-mockbtn {
  display: flex; align-items: center; gap: 8px; width: 100%; padding: 8px 10px; margin-bottom: 8px;
  border: 1px dashed #D9B48E; border-radius: var(--xn-r); background: #FFFBF6; color: var(--xn-demo);
  font: inherit; font-size: 13px; cursor: pointer;
}
.xn-mockbtn:hover { background: var(--xn-demo-soft); }
.xn-side__version { font-size: 12px; color: var(--xn-ink-3); }
.xn-scrim { display: none; }

/* 主区 */
.xn-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.xn-top {
  position: sticky; top: 0; z-index: 30; display: flex; align-items: center; gap: 16px;
  height: var(--xn-topbar-h); padding: 0 32px; background: rgba(238, 242, 245, 0.92);
  backdrop-filter: blur(8px); border-bottom: 1px solid transparent;
}
.xn-top .xn-top__menu { display: none; }
.xn-crumb { display: flex; align-items: center; gap: 6px; min-width: 0; font-size: 14px; color: var(--xn-ink-3); white-space: nowrap; }
.xn-crumb__link { color: var(--xn-ink-3); }
.xn-crumb__link:hover { color: var(--xn-ink); }
.xn-crumb__here { color: var(--xn-ink); font-weight: 600; overflow: hidden; text-overflow: ellipsis; }
.xn-crumb__sep { color: var(--xn-ink-4); }
.xn-top__right { margin-left: auto; display: flex; align-items: center; gap: 12px; }
.xn-top__add { display: inline-flex; align-items: center; }

.xn-balance {
  display: inline-flex; align-items: center; gap: 6px; height: 40px; padding: 0 12px;
  border: 1px solid var(--xn-line); border-radius: 999px; background: #fff; color: var(--xn-ink); font-size: 13px;
}
.xn-balance:hover { border-color: #AEBBC8; color: var(--xn-ink); }
.xn-balance .xn-icon { font-size: 16px; color: var(--xn-ink-3); }
.xn-balance__num { font-weight: 600; font-size: 14px; }
.xn-balance__unit { color: var(--xn-ink-3); }
.xn-balance__flag, .xn-balance.is-unavailable { color: var(--xn-warning); }
.xn-balance__flag { font-size: 12px; }
.xn-balance__demo { margin-left: 2px; padding: 1px 6px; border-radius: 6px; background: var(--xn-demo-soft); color: var(--xn-demo); font-size: 11px; }

.xn-account {
  display: flex; align-items: center; gap: 8px; height: 40px; max-width: 220px; padding: 0 12px 0 4px;
  border: 1px solid var(--xn-line); border-radius: 999px; background: #fff; color: var(--xn-ink);
  font: inherit; font-size: 13px; cursor: pointer;
}
.xn-account:hover { border-color: #AEBBC8; }
.xn-account__dot { display: grid; place-items: center; flex: none; width: 30px; height: 30px; border-radius: 50%; background: var(--xn-ink); color: #fff; font-weight: 600; }
.xn-account__name { max-width: 140px; }
.xn-iconbtn { display: grid; place-items: center; width: 38px; height: 38px; border: 0; border-radius: var(--xn-r); background: none; color: var(--xn-ink-2); cursor: pointer; }
.xn-iconbtn:hover { background: #fff; }

.xn-content { flex: 1; min-width: 0; }

@media (max-width: 1100px) {
  .xn-balance__flag, .xn-balance__demo { display: none; }
}
@media (max-width: 960px) {
  .xn-shell::before { display: none; }
  .xn-side { position: fixed; left: 0; top: 0; transform: translateX(-100%); transition: transform 0.2s ease; }
  .is-nav-open .xn-side { transform: none; box-shadow: var(--xn-shadow-pop); }   /* 收起时不留阴影，否则左边缘会透出一条灰影 */
  .is-nav-open .xn-scrim { display: block; position: fixed; inset: 0; z-index: 35; background: rgba(30, 43, 64, 0.32); }
  .xn-top { padding: 0 16px; gap: 8px; }
  .xn-top .xn-top__menu { display: grid; }
  .xn-crumb__group, .xn-crumb__group + .xn-crumb__sep, .xn-account__name { display: none; }
}
@media (max-width: 640px) {
  .xn-top__add { padding: 0 12px; }
  .xn-balance__unit { display: none; }
  .xn-crumb { display: none; }
}
</style>

<style>
.xn-account-menu { min-width: 240px; padding: 6px 0; }
.xn-account-menu .el-dropdown-menu__item { display: flex; align-items: center; gap: 10px; line-height: 38px; }
.xn-account-menu__head { display: flex; align-items: center; gap: 8px; padding: 6px 20px 10px; list-style: none; border-bottom: 1px solid var(--xn-line-2); margin-bottom: 6px; font-size: 13px; }
.xn-account-menu__head strong { max-width: 110px; }
.xn-account-menu__label.is-disabled { color: var(--xn-ink-3) !important; cursor: default; font-size: 12px; line-height: 30px !important; }
.xn-account-menu__lang { padding-left: 44px !important; line-height: 34px !important; justify-content: space-between; }
.xn-account-menu__lang.is-on { color: var(--xn-lake) !important; font-weight: 600; }
.xn-account-menu__danger { color: var(--xn-danger) !important; }
</style>
