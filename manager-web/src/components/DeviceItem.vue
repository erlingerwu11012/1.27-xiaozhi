<template>
  <article class="ac">
    <header class="ac__head">
      <span class="ac__ava" aria-hidden="true">{{ initial }}</span>
      <div class="ac__id">
        <h3 class="ac__name xn-clip" :title="device.agentName">{{ device.agentName }}</h3>
        <p class="ac__meta">
          <span v-if="count > 0" class="ac__bound"><i class="dot"></i>{{ $t('xn.home.boundN', { n: count }) }}</span>
          <span v-else class="ac__unbound"><i class="dot"></i>{{ $t('xn.home.unbound') }}</span>
          <span>{{ $t('xn.home.lastTalk', { t: lastTime }) }}</span>
        </p>
      </div>
      <el-tooltip :content="$t('xn.home.deleteAgent')" placement="top">
        <button type="button" class="ac__del" :aria-label="$t('xn.home.deleteAgent')" @click.stop="handleDelete">
          <xn-icon name="trash" />
        </button>
      </el-tooltip>
    </header>

    <p class="ac__prompt" :class="{ 'is-empty': !device.systemPrompt }">{{ device.systemPrompt || $t('xn.home.noPrompt') }}</p>

    <dl class="ac__spec">
      <div><dt>{{ $t('xn.home.llm') }}</dt><dd class="xn-clip">{{ device.llmModelName || '—' }}</dd></div>
      <div>
        <dt>{{ $t('xn.home.voice') }}</dt>
        <dd class="xn-clip">{{ device.ttsVoiceName || '—' }}<span v-if="device.ttsModelName" class="xn-muted">（{{ device.ttsModelName }}）</span></dd>
      </div>
      <div><dt>{{ $t('xn.home.memory') }}</dt><dd class="xn-clip">{{ device.memName || '—' }}</dd></div>
    </dl>

    <!-- 绑定的设备：已绑定 ≠ 在线，这里只显示绑定关系与最后对话时间 -->
    <div class="ac__devices">
      <template v-if="device.devices && device.devices.length">
        <div v-for="d in device.devices.slice(0, 2)" :key="d.id" class="ac__dev">
          <xn-icon name="device" class="xn-muted" />
          <span class="ac__dev-name xn-clip">{{ d.alias || d.boardName || d.board }}</span>
          <span class="ac__dev-mac xn-num xn-clip">{{ d.macAddress }}</span>
          <span class="ac__dev-time">{{ relTime(d.lastConnectedAt) }}</span>
        </div>
        <router-link v-if="device.devices.length > 2" class="ac__more" :to="devicesRoute">
          {{ $t('xn.home.moreDevices', { n: device.devices.length - 2 }) }}
        </router-link>
      </template>
      <div v-else-if="count === 0" class="ac__nodev">
        <span>{{ $t('xn.home.noDevice') }}</span>
        <el-button type="text" @click="$emit('bind', device.agentId)">{{ $t('xn.home.bindDevice') }}</el-button>
      </div>
      <div v-else class="ac__nodev xn-muted">{{ $t('xn.home.loadingDevices') }}</div>
    </div>

    <footer class="ac__actions">
      <el-button type="primary" size="small" @click="handleConfigure">
        <xn-icon name="tune" /> {{ $t('home.configureRole') }}
      </el-button>
      <el-button type="text" @click="handleDeviceManage">{{ $t('xn.home.devices') }} <span class="xn-num">{{ count }}</span></el-button>
      <el-button type="text" @click="handleUnifiedUserManagement">{{ $t('xn.home.identities') }}</el-button>
      <el-tooltip :disabled="!noMemory" :content="$t('home.enableMemory')" placement="top">
        <span class="ac__chat-wrap">
          <el-button type="text" :disabled="noMemory" @click="handleChatHistory">{{ $t('home.chatHistory') }}</el-button>
        </span>
      </el-tooltip>
    </footer>
  </article>
</template>

<script>
/**
 * 首页的智能体卡片（沿用原 DeviceItem 的跳转与事件：配置角色、设备管理、人员身份、聊天记录、删除）。
 * 记忆为“无记忆”(Memory_nomem) 时聊天记录不可用，原逻辑不变，只是把原因直接写在提示里。
 */
export function relativeTime(vm, value) {
  if (!value) return vm.$t('home.noConversation');
  const diffMinutes = Math.floor((Date.now() - new Date(value).getTime()) / 60000);
  if (diffMinutes <= 1) return vm.$t('home.justNow');
  if (diffMinutes < 60) return vm.$t('home.minutesAgo', { minutes: diffMinutes });
  if (diffMinutes < 24 * 60) return vm.$t('home.hoursAgo', { hours: Math.floor(diffMinutes / 60), minutes: diffMinutes % 60 });
  return String(value).slice(0, 16);
}

export default {
  name: 'DeviceItem',
  props: {
    device: { type: Object, required: true },
  },
  computed: {
    count() { return Number(this.device.deviceCount) || 0; },
    noMemory() { return this.device.memModelId === 'Memory_nomem'; },
    initial() { return Array.from(this.device.agentName || '?')[0]; },
    lastTime() { return relativeTime(this, this.device.lastConnectedAt); },
    devicesRoute() { return { path: '/device-management', query: { agentId: this.device.agentId } }; },
  },
  methods: {
    relTime(v) { return relativeTime(this, v); },
    handleDelete() {
      this.$emit('delete', this.device.agentId);
    },
    handleConfigure() {
      this.$router.push({ path: '/role-config', query: { agentId: this.device.agentId } });
    },
    handleUnifiedUserManagement() {
      this.$router.push({ path: '/unified-user-management', query: { agentId: this.device.agentId } });
    },
    handleDeviceManage() {
      this.$router.push(this.devicesRoute);
    },
    handleChatHistory() {
      if (this.noMemory) return;
      this.$emit('chat-history', { agentId: this.device.agentId, agentName: this.device.agentName });
    },
  },
};
</script>

<style scoped>
.ac {
  display: flex; flex-direction: column; min-width: 0; padding: 20px 20px 14px;
  background: #fff; border: 1px solid var(--xn-line); border-radius: var(--xn-r-lg);
}
.ac:hover { border-color: #C9D4DE; }
.ac__head { display: flex; align-items: flex-start; gap: 12px; }
.ac__ava {
  display: grid; place-items: center; flex: none; width: 44px; height: 44px; border-radius: 50%;
  background: var(--xn-lake-soft); color: var(--xn-lake-ink); font: 600 19px/1 var(--xn-serif);
}
.ac__id { flex: 1; min-width: 0; }
.ac__name { margin: 0; font: 600 19px/1.35 var(--xn-serif); letter-spacing: 0.02em; color: var(--xn-ink); }
.ac__meta { display: flex; align-items: center; flex-wrap: wrap; gap: 2px 14px; margin: 4px 0 0; font-size: 13px; color: var(--xn-ink-3); }
.ac__bound, .ac__unbound { display: inline-flex; align-items: center; gap: 6px; }
.ac__bound { color: var(--xn-lake); font-weight: 500; }
.dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; }
.ac__unbound .dot { background: transparent; box-shadow: inset 0 0 0 1.5px var(--xn-ink-4); }
.ac__del {
  display: grid; place-items: center; flex: none; width: 32px; height: 32px; margin: -4px -6px 0 0;
  border: 0; border-radius: var(--xn-r); background: none; color: var(--xn-ink-3); font-size: 18px; cursor: pointer;
}
.ac__del:hover { background: var(--xn-danger-soft); color: var(--xn-danger); }

.ac__prompt {
  margin: 14px 0 0; font-size: 14px; line-height: 1.7; color: var(--xn-ink-2);
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; min-height: 3.4em;
}
.ac__prompt.is-empty { color: var(--xn-ink-4); }

.ac__spec { margin: 14px 0 0; padding: 12px 14px; display: grid; gap: 6px; border-radius: var(--xn-r); background: var(--xn-mist-2); }
.ac__spec div { display: grid; grid-template-columns: 72px minmax(0, 1fr); gap: 8px; font-size: 13px; }
.ac__spec dt { color: var(--xn-ink-3); }
.ac__spec dd { margin: 0; color: var(--xn-ink); }

.ac__devices { margin-top: 12px; min-height: 64px; }
.ac__dev { display: grid; grid-template-columns: 16px minmax(0, max-content) minmax(96px, 1fr) auto; align-items: center; gap: 8px; padding: 7px 0; font-size: 13px; border-bottom: 1px dashed var(--xn-line-2); }
.ac__dev:last-of-type { border-bottom: 0; }
.ac__dev .xn-icon { font-size: 15px; }
.ac__dev-name { font-weight: 600; color: var(--xn-ink); }
.ac__dev-mac { color: var(--xn-ink-3); }
.ac__dev-time { color: var(--xn-ink-3); white-space: nowrap; }
.ac__more { display: inline-block; margin-top: 4px; font-size: 13px; }
.ac__nodev {
  display: flex; align-items: center; justify-content: space-between; gap: 8px; min-height: 44px; padding: 4px 6px 4px 14px;
  border: 1px dashed var(--xn-line); border-radius: var(--xn-r); font-size: 13px; color: var(--xn-ink-3);
}

.ac__actions { display: flex; align-items: center; flex-wrap: wrap; gap: 2px 14px; margin-top: auto; padding-top: 14px; }
.ac__actions .el-button + .el-button { margin-left: 0; }
.ac__chat-wrap { display: inline-block; }
</style>
