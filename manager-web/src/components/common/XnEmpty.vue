<template>
  <div class="xn-empty" :class="{ 'xn-empty--error': error }" role="status">
    <xn-icon :name="error ? 'alert' : icon" class="xn-empty__icon" />
    <p class="xn-empty__title">{{ title || (error ? $t('xn.common.loadFailed') : '') }}</p>
    <p v-if="description || error" class="xn-empty__desc">{{ description || $t('xn.common.loadFailedDesc') }}</p>
    <div v-if="$slots.default || error" class="xn-empty__actions">
      <slot>
        <el-button v-if="error" @click="$emit('retry')"><xn-icon name="refresh" /> {{ $t('xn.common.retry') }}</el-button>
      </slot>
    </div>
  </div>
</template>

<script>
/* 空状态 / 加载失败：说明发生了什么、下一步做什么。error 为 true 时显示失败样式与重试按钮（触发 retry 事件）。 */
export default {
  name: 'XnEmpty',
  props: {
    icon: { type: String, default: 'info' },
    title: { type: String, default: '' },
    description: { type: String, default: '' },
    error: { type: Boolean, default: false },
  },
};
</script>

<style scoped>
.xn-empty--error .xn-empty__icon { color: var(--xn-danger); }
.xn-empty__actions { display: flex; justify-content: center; gap: 8px; }
</style>
