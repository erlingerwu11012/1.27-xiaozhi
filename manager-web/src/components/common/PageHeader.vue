<template>
  <header class="xn-page-header">
    <div class="xn-page-header__text">
      <router-link v-if="back" :to="back" class="xn-page-header__back">
        <xn-icon name="chevron" class="flip" />{{ backLabel || $t('xn.common.back') }}
      </router-link>
      <h1 class="xn-page-header__title">{{ title }}</h1>
      <p v-if="description || $slots.description" class="xn-page-header__desc">
        <slot name="description">{{ description }}</slot>
      </p>
    </div>
    <div v-if="$slots.default" class="xn-page-header__actions"><slot /></div>
  </header>
</template>

<script>
/* 页面标题区：标题（衬线）+ 一句说明 + 右侧操作。所有页面统一使用。 */
export default {
  name: 'PageHeader',
  props: {
    title: { type: String, required: true },
    description: { type: String, default: '' },
    back: { type: [String, Object], default: null },
    backLabel: { type: String, default: '' },
  },
};
</script>

<style scoped>
.xn-page-header__back {
  display: inline-flex; align-items: center; gap: 4px; margin-bottom: 6px;
  font-size: 13px; color: var(--xn-ink-3);
}
.xn-page-header__back:hover { color: var(--xn-ink); }
.flip { transform: rotate(180deg); }
</style>
