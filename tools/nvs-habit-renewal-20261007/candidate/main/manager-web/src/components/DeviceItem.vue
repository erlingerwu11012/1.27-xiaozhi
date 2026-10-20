<template>
  <div class="device-item glass-panel" :class="{ 'has-bound-device': hasBoundDevice }">
    <!-- 已绑定设备时出现：旋转彩虹描边（与官方语音输入框同一套做法） -->
    <span v-if="hasBoundDevice" class="device-item__ring" aria-hidden="true"></span>
    <div class="device-item-header">
      <div class="device-title">
        {{ device.agentName }}
      </div>
      <div class="device-actions">
        <img src="@/assets/home/delete.png" alt="" class="device-icon" @click.stop="handleDelete" />
        <el-tooltip class="item" effect="dark" :content="device.systemPrompt" placement="top"
          popper-class="custom-tooltip">
          <img src="@/assets/home/info.png" alt="" class="device-icon" />
        </el-tooltip>
      </div>
    </div>
    <div class="device-name">
      {{ $t('home.languageModel') }}：{{ device.llmModelName }}
    </div>
    <div class="device-name">
      {{ $t('home.voiceModel') }}：{{ device.ttsModelName }} ({{ device.ttsVoiceName }})
    </div>
    <div class="btn-group">
      <div class="settings-btn" @click="handleConfigure">
        {{ $t('home.configureRole') }}
      </div>
      <div class="settings-btn" @click="handleUnifiedUserManagement">
        用户管理
      </div>
      <div class="settings-btn" @click="handleDeviceManage">
        {{ $t('home.deviceManagement') }}({{ device.deviceCount }})
      </div>
      <div :class="['settings-btn', { 'disabled-btn': device.memModelId === 'Memory_nomem' }]"
        @click="handleChatHistory">
        <el-tooltip v-if="device.memModelId === 'Memory_nomem'" :content="$t('home.enableMemory')" placement="top">
          <span>{{ $t('home.chatHistory') }}</span>
        </el-tooltip>
        <span v-else>{{ $t('home.chatHistory') }}</span>
      </div>
    </div>
    <div class="version-info">
      <div>{{ $t('home.lastConversation') }}：{{ formattedLastConnectedTime }}</div>
    </div>
  </div>
</template>

<script>
import i18n from '@/i18n';

export default {
  name: 'DeviceItem',
  props: {
    device: { type: Object, required: true }
  },
  data() {
    return { switchValue: false }
  },
  computed: {
    // 该智能体名下是否已绑定设备（deviceCount 由 /agent/list 下发）
    // 大于 0 时卡片显示旋转彩虹描边，用于一眼区分「有设备」的智能体
    hasBoundDevice() {
      const count = Number(this.device && this.device.deviceCount);
      return Number.isFinite(count) && count > 0;
    },
    formattedLastConnectedTime() {
      if (!this.device.lastConnectedAt) return this.$t('home.noConversation');

      const lastTime = new Date(this.device.lastConnectedAt);
      const now = new Date();
      const diffMinutes = Math.floor((now - lastTime) / (1000 * 60));

      if (diffMinutes <= 1) {
        return this.$t('home.justNow');
      } else if (diffMinutes < 60) {
        return this.$t('home.minutesAgo', { minutes: diffMinutes });
      } else if (diffMinutes < 24 * 60) {
        const hours = Math.floor(diffMinutes / 60);
        const minutes = diffMinutes % 60;
        return this.$t('home.hoursAgo', { hours, minutes });
      } else {
        return this.device.lastConnectedAt;
      }
    }
  },
  methods: {
    handleDelete() {
      this.$emit('delete', this.device.agentId)
    },
    handleConfigure() {
      this.$router.push({ path: '/role-config', query: { agentId: this.device.agentId } });
    },
    handleVoicePrint() {
      this.$router.push({ path: '/voice-print', query: { agentId: this.device.agentId } });
    },
    handleUnifiedUserManagement() {
      this.$router.push({ path: '/unified-user-management', query: { agentId: this.device.agentId } });
    },
    handleFaceManagement() {
      this.$router.push({ path: '/face-management', query: { agentId: this.device.agentId } });
    },
    handleDeviceManage() {
      this.$router.push({ path: '/device-management', query: { agentId: this.device.agentId } });
    },
    handleChatHistory() {
      if (this.device.memModelId === 'Memory_nomem') {
        return
      }
      this.$emit('chat-history', { agentId: this.device.agentId, agentName: this.device.agentName })
    }
  }
}
</script>
<style scoped>
.device-item.glass-panel {
  background: #fff;
  border: none;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.06);
  border-radius: 12px;
}

/* ===== 已绑定设备：旋转彩虹描边 =====
   与「官方语音」输入框（styles/official-tts-studio.scss 的 .ot-composer__ring）同一套做法：
   外层裁出圆角矩形，内部一张更大的渐变盘持续自转，视觉上是「彩虹彗星绕边跑」。
   描边 = 卡片圆角矩形 与 ::after 白底内芯（inset 2px）之间露出的那 2px。 */
.device-item.has-bound-device {
  position: relative;
  /* 裁掉旋转到卡片外的渐变盘 */
  overflow: hidden;
  /* 自成层叠上下文：把内部 ring/内容 的 z-index 关在卡片里，
     避免逃逸到全局盖住相邻卡片或顶栏 */
  isolation: isolate;
  /* 有设备的卡片给一圈柔和外发光，与描边呼应 */
  box-shadow:
    0 0 18px rgba(167, 139, 250, 0.22),
    0 0 34px rgba(125, 211, 252, 0.14),
    0 2px 12px rgba(0, 0, 0, 0.06);
}

.device-item__ring {
  position: absolute;
  inset: 0;
  border-radius: inherit;
  overflow: hidden;
  z-index: 0;
  pointer-events: none;
}

.device-item__ring::before {
  content: "";
  position: absolute;
  left: 50%;
  top: 50%;
  width: 220%;
  aspect-ratio: 1 / 1;
  /* 渐变里带一段浅灰，转动时就是「彩虹彗星 + 灰尾巴」 */
  background: conic-gradient(
    from 0deg,
    #dfe2e8 0deg,
    #7dd3fc 40deg,
    #a78bfa 95deg,
    #f9a8d4 150deg,
    #fcd34d 205deg,
    #86efac 260deg,
    #7dd3fc 305deg,
    #dfe2e8 350deg,
    #dfe2e8 360deg
  );
  animation: device-ring-spin 5s linear infinite;
  will-change: transform;
}

.device-item.has-bound-device::after {
  content: "";
  position: absolute;
  inset: 2px;
  border-radius: 10px;
  background: #fff;
  z-index: 1;
  pointer-events: none;
}

/* 内容提到描边与白底内芯之上（::after 不会被 * 选中，层级不变） */
.device-item.has-bound-device > *:not(.device-item__ring) {
  position: relative;
  z-index: 2;
}

@keyframes device-ring-spin {
  from {
    transform: translate(-50%, -50%) rotate(0deg);
  }
  to {
    transform: translate(-50%, -50%) rotate(360deg);
  }
}

/* 尊重系统的「减少动态效果」偏好 */
@media (prefers-reduced-motion: reduce) {
  .device-item__ring::before {
    animation: none;
    transform: translate(-50%, -50%) rotate(0deg);
  }
}

.device-item {
  width: 100%;
  padding: 24px;
  box-sizing: border-box;
  color: #1a1a2e;
}

.device-item-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.device-title {
  font-weight: 600;
  font-size: 17px;
  text-align: left;
  color: #1a1a2e;
}

.device-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.device-icon {
  width: 18px;
  height: 18px;
  cursor: pointer;
}

.device-name {
  margin: 7px 0 10px;
  font-weight: 400;
  font-size: 12px;
  color: #6b7280;
  text-align: left;
}

.btn-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}

.settings-btn {
  font-size: 12px;
  color: #2563eb;
  background: rgba(37, 99, 235, 0.08);
  width: auto;
  padding: 0 14px;
  height: 26px;
  line-height: 26px;
  cursor: pointer;
  border-radius: 999px;
  border: 1px solid rgba(37, 99, 235, 0.15);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.settings-btn:hover {
  background: rgba(37, 99, 235, 0.15);
}

.version-info {
  display: flex;
  justify-content: space-between;
  margin-top: 15px;
  font-size: 12px;
  color: #9ca3af;
  font-weight: 400;
}

.disabled-btn {
  background: rgba(148, 163, 184, 0.1);
  color: #9ca3af;
  cursor: not-allowed;
  border-color: rgba(148, 163, 184, 0.3);
  box-shadow: none;
}
</style>

<style>
.custom-tooltip {
  max-width: 400px;
  word-break: break-word;
}
</style>
