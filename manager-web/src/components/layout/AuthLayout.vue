<template>
  <div class="auth">
    <header class="auth__top">
      <router-link to="/login" class="auth-brand">
        <span class="auth-brand__mark" aria-hidden="true"><i></i></span>
        <span class="auth-brand__name">{{ $t('xn.brand') }}</span>
        <span class="auth-brand__sub">{{ $t('xn.brandSub') }}</span>
      </router-link>
      <el-dropdown trigger="click" @command="setLang">
        <button type="button" class="auth-lang"><xn-icon name="globe" /> {{ langLabel }} <xn-icon name="chevronDown" /></button>
        <el-dropdown-menu slot="dropdown">
          <el-dropdown-item v-for="l in langs" :key="l" :command="l">{{ $t(labels[l]) }}</el-dropdown-item>
        </el-dropdown-menu>
      </el-dropdown>
    </header>
    <main class="auth__main">
      <section class="auth-card">
        <h1 class="auth-card__title">{{ title }}</h1>
        <p v-if="subtitle" class="auth-card__sub">{{ subtitle }}</p>
        <slot />
      </section>
      <aside v-if="mock" class="auth-demo" role="note">
        <span class="xn-tag xn-tag--demo">{{ $t('xn.auth.demoTitle') }}</span>
        <p>{{ $t('xn.mock.accounts') }}</p>
      </aside>
    </main>
    <footer class="auth__foot"><version-footer /></footer>
  </div>
</template>

<script>
/* 认证页外框（注册、找回密码）：品牌、语言切换、居中表单卡片、演示模式说明、页脚。 */
import { changeLanguage } from '@/i18n';
import { isMockMode } from '@/mock/config';
import VersionFooter from '@/components/VersionFooter.vue';

const LABELS = { zh_CN: 'language.zhCN', zh_TW: 'language.zhTW', en: 'language.en', de: 'language.de', vi: 'language.vi' };

export default {
  name: 'AuthLayout',
  components: { VersionFooter },
  props: { title: { type: String, required: true }, subtitle: { type: String, default: '' } },
  data: () => ({ langs: Object.keys(LABELS), labels: LABELS, mock: isMockMode() }),
  computed: { langLabel() { return this.$t(LABELS[this.$i18n.locale] || 'language.zhCN'); } },
  methods: { setLang(l) { changeLanguage(l); } },
};
</script>

<style>
/* 与 login.vue 共用的认证页样式（非 scoped，类名以 auth 开头） */
.auth { min-height: 100vh; display: flex; flex-direction: column; background: var(--xn-mist); }
.auth__top { display: flex; align-items: center; justify-content: space-between; padding: 22px 32px; }
.auth-brand { display: flex; align-items: baseline; gap: 8px; color: var(--xn-ink); }
.auth-brand:hover { color: var(--xn-ink); }
.auth-brand__mark { position: relative; align-self: center; width: 14px; height: 20px; }
.auth-brand__mark::before { content: ""; position: absolute; left: 6px; top: 0; width: 2px; height: 8px; border-radius: 1px; background: var(--xn-lake); }
.auth-brand__mark i { position: absolute; left: 1px; top: 7px; width: 12px; height: 12px; border-radius: 50%; border: 2.5px solid var(--xn-ink); box-sizing: border-box; }
.auth-brand__name { font: 600 22px/1 var(--xn-serif); letter-spacing: 0.04em; }
.auth-brand__sub { font-size: 13px; color: var(--xn-ink-3); }
.auth-lang { display: inline-flex; align-items: center; gap: 6px; height: 36px; padding: 0 12px; border: 1px solid var(--xn-line); border-radius: 999px; background: #fff; color: var(--xn-ink-2); font: inherit; font-size: 13px; cursor: pointer; }
.auth-lang:hover { color: var(--xn-ink); border-color: #AEBBC8; }
.auth__main { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; padding: 24px 16px 40px; }
.auth-card { width: 100%; max-width: 440px; padding: 36px 36px 28px; background: #fff; border: 1px solid var(--xn-line); border-radius: var(--xn-r-xl); box-sizing: border-box; }
.auth-card__title { margin: 0; font: 600 28px/1.25 var(--xn-serif); color: var(--xn-ink); letter-spacing: 0.02em; }
.auth-card__sub { margin: 8px 0 24px; color: var(--xn-ink-3); font-size: 14px; }
.auth-form { display: flex; flex-direction: column; gap: 16px; }
.auth-field { display: flex; flex-direction: column; gap: 6px; }
.auth-field__label { font-size: 14px; font-weight: 500; color: var(--xn-ink-2); }
.auth-mobile { display: grid; grid-template-columns: 148px minmax(0, 1fr); gap: 8px; }
.auth-captcha { display: grid; grid-template-columns: minmax(0, 1fr) 120px; gap: 8px; }
.auth-captcha__img { display: grid; place-items: center; height: 40px; padding: 0; overflow: hidden; border: 1px solid var(--xn-line); border-radius: var(--xn-r); background: var(--xn-mist-2); color: var(--xn-ink-3); cursor: pointer; }
.auth-captcha__img img { width: 100%; height: 100%; object-fit: cover; }
.auth-sms { display: grid; grid-template-columns: minmax(0, 1fr) 120px; gap: 8px; }
.auth-sms .el-button { padding: 0 8px; }
.auth-submit { width: 100%; height: 44px; margin-top: 4px; font-size: 15px; }
.auth-links { display: flex; justify-content: space-between; font-size: 14px; }
.auth-agree { margin: 22px 0 0; padding-top: 16px; border-top: 1px solid var(--xn-line-2); font-size: 12px; color: var(--xn-ink-3); }
.auth-agree span { color: var(--xn-ink-2); }
.auth-demo { display: flex; align-items: flex-start; gap: 10px; width: 100%; max-width: 440px; padding: 12px 14px; border: 1px dashed #D9B48E; border-radius: var(--xn-r-lg); background: #FFFBF6; box-sizing: border-box; }
.auth-demo p { margin: 0; font-size: 13px; line-height: 1.7; color: var(--xn-ink-2); }
.auth__foot { padding: 16px; text-align: center; font-size: 12px; color: var(--xn-ink-3); }
@media (max-width: 480px) {
  .auth__top { padding: 16px; }
  .auth-card { padding: 28px 20px 22px; }
  .auth-mobile { grid-template-columns: 1fr; }
}
</style>
