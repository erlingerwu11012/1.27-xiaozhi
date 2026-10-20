<template>
  <div class="auth">
    <header class="auth__top">
      <span class="auth-brand">
        <span class="auth-brand__mark" aria-hidden="true"><i></i></span>
        <span class="auth-brand__name">{{ $t('xn.brand') }}</span>
        <span class="auth-brand__sub">{{ $t('xn.brandSub') }}</span>
      </span>
      <el-dropdown trigger="click" @command="changeLanguage">
        <button type="button" class="auth-lang"><xn-icon name="globe" /> {{ currentLanguageText }} <xn-icon name="chevronDown" /></button>
        <el-dropdown-menu slot="dropdown">
          <el-dropdown-item command="zh_CN">{{ $t("language.zhCN") }}</el-dropdown-item>
          <el-dropdown-item command="zh_TW">{{ $t("language.zhTW") }}</el-dropdown-item>
          <el-dropdown-item command="en">{{ $t("language.en") }}</el-dropdown-item>
          <el-dropdown-item command="de">{{ $t("language.de") }}</el-dropdown-item>
          <el-dropdown-item command="vi">{{ $t("language.vi") }}</el-dropdown-item>
        </el-dropdown-menu>
      </el-dropdown>
    </header>

    <main class="auth__main">
      <section class="auth-card">
        <h1 class="auth-card__title">{{ isRegisterMode ? $t("register.title") : $t("login.title") }}</h1>
        <p class="auth-card__sub">{{ isRegisterMode ? $t("register.welcome") : $t("login.welcome") }}</p>

        <!-- 登录 -->
        <template v-if="!isRegisterMode">
          <div v-if="enableMobileRegister" class="auth-tabs" role="tablist">
            <button type="button" role="tab" class="auth-tab" :class="{ 'is-on': !isMobileLogin }" :aria-selected="String(!isMobileLogin)"
              @click="isMobileLogin && switchLoginType('username')">{{ $t("login.usernameLogin") }}</button>
            <button type="button" role="tab" class="auth-tab" :class="{ 'is-on': isMobileLogin }" :aria-selected="String(isMobileLogin)"
              @click="!isMobileLogin && switchLoginType('mobile')">{{ $t("login.mobileLogin") }}</button>
          </div>
          <form key="login-form" class="auth-form" autocomplete="on" @submit.prevent="handleSubmit">
            <label v-if="!isMobileLogin" class="auth-field">
              <span class="auth-field__label">{{ $t('xn.auth.username') }}</span>
              <el-input ref="loginUsername" v-model="form.username" :placeholder="$t('login.usernamePlaceholder')" name="username" autocomplete="username" id="username" />
            </label>
            <div v-else class="auth-field">
              <span class="auth-field__label">{{ $t('xn.auth.mobile') }}</span>
              <div class="auth-mobile">
                <el-select v-model="form.areaCode" class="auth-mobile__area">
                  <el-option v-for="item in mobileAreaList" :key="item.key" :label="`${item.name} (${item.key})`" :value="item.key" />
                </el-select>
                <el-input v-model="form.mobile" :placeholder="$t('login.mobilePlaceholder')" autocomplete="tel" />
              </div>
            </div>
            <label class="auth-field">
              <span class="auth-field__label">{{ $t('xn.auth.password') }}</span>
              <el-input ref="loginPassword" v-model="form.password" :placeholder="$t('login.passwordPlaceholder')" type="password" name="password"
                autocomplete="current-password" id="password" show-password @mousedown.native="syncLoginCredentials" />
            </label>
            <div class="auth-field">
              <span class="auth-field__label">{{ $t('xn.auth.captcha') }}</span>
              <div class="auth-captcha">
                <el-input v-model="form.captcha" :placeholder="$t('login.captchaPlaceholder')" autocomplete="off" />
                <button type="button" class="auth-captcha__img" :title="$t('xn.auth.refreshCaptcha')" :aria-label="$t('xn.auth.refreshCaptcha')" @click="fetchCaptcha">
                  <img v-if="captchaUrl" :src="captchaUrl" alt="" />
                  <xn-icon v-else name="refresh" />
                </button>
              </div>
            </div>
            <el-button type="primary" native-type="submit" class="auth-submit submit-btn">{{ $t("login.login") }}</el-button>
            <div class="auth-links">
              <a v-if="allowUserRegister" href="javascript:void(0)" @click.prevent="switchToRegister">{{ $t("login.register") }}</a>
              <a v-if="enableMobileRegister" href="javascript:void(0)" @click.prevent="goToForgetPassword">{{ $t("login.forgetPassword") }}</a>
            </div>
          </form>
        </template>

        <!-- 注册 -->
        <form v-else key="register-form" class="auth-form" @submit.prevent="handleSubmit">
          <label class="auth-field">
            <span class="auth-field__label">{{ $t('xn.auth.username') }}</span>
            <el-input v-model="form.username" :placeholder="$t('register.usernamePlaceholder')" name="username" autocomplete="username" id="register-username" />
          </label>
          <label class="auth-field">
            <span class="auth-field__label">{{ $t('xn.auth.password') }}</span>
            <el-input v-model="form.password" :placeholder="$t('register.passwordPlaceholder')" type="password" name="password" autocomplete="new-password" id="register-password" show-password />
          </label>
          <label class="auth-field">
            <span class="auth-field__label">{{ $t('xn.auth.confirmPassword') }}</span>
            <el-input v-model="form.confirmPassword" :placeholder="$t('register.confirmPasswordPlaceholder')" type="password" name="confirmPassword" autocomplete="new-password" id="register-confirm-password" show-password />
          </label>
          <div class="auth-field">
            <span class="auth-field__label">{{ $t('xn.auth.captcha') }}</span>
            <div class="auth-captcha">
              <el-input v-model="form.captcha" :placeholder="$t('register.captchaPlaceholder')" autocomplete="off" />
              <button type="button" class="auth-captcha__img" :title="$t('xn.auth.refreshCaptcha')" :aria-label="$t('xn.auth.refreshCaptcha')" @click="fetchCaptcha">
                <img v-if="captchaUrl" :src="captchaUrl" alt="" />
                <xn-icon v-else name="refresh" />
              </button>
            </div>
          </div>
          <el-button type="primary" native-type="submit" class="auth-submit submit-btn">{{ $t("register.registerButton") }}</el-button>
          <div class="auth-links">
            <a href="javascript:void(0)" @click.prevent="switchToLogin">{{ $t("register.goToLogin") }}</a>
          </div>
        </form>

        <p class="auth-agree">
          {{ $t("login.agreeTo") }} <span>{{ $t("login.userAgreement") }}</span> {{ $t("login.and") }} <span>{{ $t("login.privacyPolicy") }}</span>
        </p>
      </section>

      <aside v-if="isMock" class="auth-demo" role="note">
        <span class="xn-tag xn-tag--demo">{{ $t('xn.auth.demoTitle') }}</span>
        <p>{{ $t('xn.mock.accounts') }}</p>
      </aside>
    </main>

    <footer class="auth__foot"><version-footer /></footer>
  </div>
</template>

<script>
import Api from "@/apis/api";
import VersionFooter from "@/components/VersionFooter.vue";
import i18n, { changeLanguage } from "@/i18n";
import { getUUID, goToPage, showDanger, showSuccess, sm2Encrypt, validateMobile } from "@/utils";
import { mapState } from "vuex";
import { isMockMode } from "@/mock/config";

export default {
  name: "login",
  components: {
    VersionFooter,
  },
  computed: {
    ...mapState({
      allowUserRegister: (state) => state.pubConfig.allowUserRegister,
      enableMobileRegister: (state) => state.pubConfig.enableMobileRegister,
      mobileAreaList: (state) => state.pubConfig.mobileAreaList,
      sm2PublicKey: (state) => state.pubConfig.sm2PublicKey,
    }),
    isMock() {
      return isMockMode();
    },
    currentLanguage() {
      return i18n.locale || "zh_CN";
    },
    currentLanguageText() {
      const currentLang = this.currentLanguage;
      switch (currentLang) {
        case "zh_CN":
          return this.$t("language.zhCN");
        case "zh_TW":
          return this.$t("language.zhTW");
        case "en":
          return this.$t("language.en");
        case "de":
          return this.$t("language.de");
        case "vi":
          return this.$t("language.vi");
        default:
          return this.$t("language.zhCN");
      }
    },
  },
  data() {
    return {
      activeName: "username",
      showLogin: true,   // 新版直接显示表单（原版需先点胶囊菜单里的“登录”）
      isRegisterMode: false,
      form: {
        username: "",
        password: "",
        confirmPassword: "",
        captcha: "",
        captchaId: "",
        areaCode: "+86",
        mobile: "",
      },
      captchaUuid: "",
      captchaUrl: "",
      isMobileLogin: false,
      fetchCaptchaTimer: null,
    };
  },
  mounted() {
    this.fetchCaptcha();
    this.$store.dispatch("fetchPubConfig").then(() => {
      // A delayed response must not replace fields the user is already using.
      // 配置晚到时不覆盖用户已经开始填写的内容；未填写时按原逻辑默认手机号登录
      if (!this.form.username && !this.form.password && !this.form.mobile) this.isMobileLogin = this.enableMobileRegister;
    });
  },
  beforeDestroy() {
    if (this.fetchCaptchaTimer) {
      clearTimeout(this.fetchCaptchaTimer);
      this.fetchCaptchaTimer = null;
    }
  },
  methods: {
    openLogin() {
      this.showLogin = true;
      this.isRegisterMode = false;
    },
    openRegister() {
      this.showLogin = true;
      this.isRegisterMode = true;
      this.fetchCaptcha();
    },
    closeLogin() {
      this.showLogin = false;
    },
    switchToRegister() {
      this.isRegisterMode = true;
      this.form.confirmPassword = "";
      this.fetchCaptcha();
    },
    switchToLogin() {
      this.isRegisterMode = false;
      this.form.confirmPassword = "";
    },
    credentialInput(field) {
      const component = this.$refs[field === 'username' ? 'loginUsername' : 'loginPassword'];
      return component && component.getInput ? component.getInput() : null;
    },
    syncLoginCredentials() {
      if (!this.showLogin || this.isRegisterMode) return;
      // Password managers may fill DOM values without emitting input events.
      // Adopt those values before submission or toggling password visibility.
      for (const field of ['username', 'password']) {
        const input = this.credentialInput(field);
        if (input && !input.composing) this.form[field] = input.value;
      }
    },
    handleSubmit() {
      if (this.isRegisterMode) {
        this.register();
      } else {
        this.login();
      }
    },


    fetchCaptcha() {
      if (this.$store.getters.getToken) {
        if (this.$route.path !== "/home") {
          this.$router.push("/home");
        }
      } else {
        this.captchaUuid = getUUID();
        Api.user.getCaptcha(this.captchaUuid, (res) => {
          if (res.status === 200) {
            const blob = new Blob([res.data], { type: res.data.type });
            this.captchaUrl = URL.createObjectURL(blob);
          } else {
            showDanger("验证码加载失败，点击刷新");
          }
        });
      }
    },


    changeLanguage(lang) {
      changeLanguage(lang);
      this.$message.success({
        message: this.$t("message.success"),
        showClose: true,
      });
    },

    switchLoginType(type) {
      this.isMobileLogin = type === "mobile";
      this.form.username = "";
      this.form.mobile = "";
      this.form.password = "";
      this.form.captcha = "";
      this.fetchCaptcha();
    },

    validateInput(input, messageKey) {
      if (!input.trim()) {
        showDanger(this.$t(messageKey));
        return false;
      }
      return true;
    },

    async login() {
      this.syncLoginCredentials();
      if (this.isMobileLogin) {
        if (!validateMobile(this.form.mobile, this.form.areaCode)) {
          showDanger(this.$t("login.requiredMobile"));
          return;
        }
        this.form.username = this.form.areaCode + this.form.mobile;
      } else {
        if (!this.validateInput(this.form.username, "login.requiredUsername")) {
          return;
        }
      }

      if (!this.validateInput(this.form.password, "login.requiredPassword")) {
        return;
      }
      if (!this.validateInput(this.form.captcha, "login.requiredCaptcha")) {
        return;
      }

      let encryptedPassword;
      try {
        const captchaAndPassword = this.form.captcha + this.form.password;
        encryptedPassword = sm2Encrypt(this.sm2PublicKey, captchaAndPassword);
      } catch (error) {
        console.error("密码加密失败:", error);
        showDanger(this.$t("sm2.encryptionFailed"));
        return;
      }

      const plainUsername = this.form.username;
      this.form.captchaId = this.captchaUuid;

      const loginData = {
        username: plainUsername,
        password: encryptedPassword,
        captchaId: this.form.captchaId,
      };

      Api.user.login(
        loginData,
        ({ data }) => {
          if (this.fetchCaptchaTimer) {
            clearTimeout(this.fetchCaptchaTimer);
            this.fetchCaptchaTimer = null;
          }
          this.handleLoginSuccess(data);
        },
        (err) => {
          let errorMessage = err.data.msg || "登录失败";
          showDanger(errorMessage);
          if (
            (err.data != null && err.data.msg != null && err.data.msg.indexOf("图形验证码") > -1) ||
            (err.data.msg && err.data.msg.indexOf("Captcha") > -1)
          ) {
            this.fetchCaptcha();
          }
        }
      );

      this.fetchCaptchaTimer = setTimeout(() => {
        this.fetchCaptcha();
      }, 1000);
    },

    async register() {
      if (!this.validateInput(this.form.username, "register.requiredUsername")) {
        return;
      }
      if (!this.validateInput(this.form.password, "register.requiredPassword")) {
        return;
      }
      if (this.form.password !== this.form.confirmPassword) {
        showDanger(this.$t("register.passwordsNotMatch"));
        return;
      }
      if (!this.validateInput(this.form.captcha, "register.requiredCaptcha")) {
        return;
      }

      let encryptedPassword;
      try {
        const captchaAndPassword = this.form.captcha + this.form.password;
        encryptedPassword = sm2Encrypt(this.sm2PublicKey, captchaAndPassword);
      } catch (error) {
        console.error("密码加密失败:", error);
        showDanger(this.$t("sm2.encryptionFailed"));
        return;
      }

      this.form.captchaId = this.captchaUuid;
      const registerData = {
        username: this.form.username,
        password: encryptedPassword,
        captchaId: this.form.captchaId,
        mobileCaptcha: "",
      };

      Api.user.register(
        registerData,
        () => {
          showSuccess(this.$t("register.registerSuccess"));
          this.switchToLogin();
          this.fetchCaptcha();
        },
        (err) => {
          showDanger(err.data?.msg || this.$t("register.registerFailed"));
          if (err.data?.msg && (err.data.msg.indexOf("图形验证码") > -1 || err.data.msg.indexOf("Captcha") > -1)) {
            this.fetchCaptcha();
          }
        }
      );

      setTimeout(() => {
        this.fetchCaptcha();
      }, 1000);
    },

    /** 登录成功：提示 → 保存 token → 进入首页（去掉原来的代码雨与全屏穿梭转场，逻辑顺序不变） */
    handleLoginSuccess(data) {
      showSuccess(this.$t("login.loginSuccess"));
      const tokenData = JSON.stringify(data.data);
      this.$store.commit("setToken", tokenData);
      const redirect = this.$route.query && this.$route.query.redirect;
      goToPage(redirect && redirect.indexOf('/') === 0 ? redirect : "/home");
    },

    goToForgetPassword() {
      goToPage("/retrieve-password");
    },


  },
};
</script>

<style scoped>
.auth { min-height: 100vh; display: flex; flex-direction: column; background: var(--xn-mist); }
.auth__top { display: flex; align-items: center; justify-content: space-between; padding: 22px 32px; }
.auth-brand { display: flex; align-items: baseline; gap: 8px; color: var(--xn-ink); }
.auth-brand__mark { position: relative; align-self: center; width: 14px; height: 20px; }
.auth-brand__mark::before { content: ""; position: absolute; left: 6px; top: 0; width: 2px; height: 8px; border-radius: 1px; background: var(--xn-lake); }
.auth-brand__mark i { position: absolute; left: 1px; top: 7px; width: 12px; height: 12px; border-radius: 50%; border: 2.5px solid var(--xn-ink); box-sizing: border-box; }
.auth-brand__name { font: 600 22px/1 var(--xn-serif); letter-spacing: 0.04em; }
.auth-brand__sub { font-size: 13px; color: var(--xn-ink-3); }
.auth-lang { display: inline-flex; align-items: center; gap: 6px; height: 36px; padding: 0 12px; border: 1px solid var(--xn-line); border-radius: 999px; background: #fff; color: var(--xn-ink-2); font: inherit; font-size: 13px; cursor: pointer; }
.auth-lang:hover { color: var(--xn-ink); border-color: #AEBBC8; }

.auth__main { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; padding: 24px 16px 40px; }
.auth-card { width: 100%; max-width: 420px; padding: 36px 36px 28px; background: #fff; border: 1px solid var(--xn-line); border-radius: var(--xn-r-xl); box-sizing: border-box; }
.auth-card__title { margin: 0; font: 600 28px/1.25 var(--xn-serif); color: var(--xn-ink); letter-spacing: 0.02em; }
.auth-card__sub { margin: 8px 0 24px; color: var(--xn-ink-3); font-size: 14px; }

.auth-tabs { display: flex; gap: 4px; padding: 4px; margin-bottom: 20px; border-radius: 10px; background: var(--xn-mist); }
.auth-tab { flex: 1; height: 34px; border: 0; border-radius: 8px; background: none; color: var(--xn-ink-2); font: inherit; font-size: 14px; cursor: pointer; }
.auth-tab.is-on { background: #fff; color: var(--xn-ink); font-weight: 600; box-shadow: 0 1px 2px rgba(30, 43, 64, 0.08); }

.auth-form { display: flex; flex-direction: column; gap: 16px; }
.auth-field { display: flex; flex-direction: column; gap: 6px; }
.auth-field__label { font-size: 14px; font-weight: 500; color: var(--xn-ink-2); }
.auth-mobile { display: grid; grid-template-columns: 148px minmax(0, 1fr); gap: 8px; }
.auth-captcha { display: grid; grid-template-columns: minmax(0, 1fr) 120px; gap: 8px; }
.auth-captcha__img { display: grid; place-items: center; height: 40px; padding: 0; overflow: hidden; border: 1px solid var(--xn-line); border-radius: var(--xn-r); background: var(--xn-mist-2); color: var(--xn-ink-3); cursor: pointer; }
.auth-captcha__img img { width: 100%; height: 100%; object-fit: cover; }
.auth-submit { width: 100%; height: 44px; margin-top: 4px; font-size: 15px; }
.auth-links { display: flex; justify-content: space-between; font-size: 14px; }
.auth-agree { margin: 22px 0 0; padding-top: 16px; border-top: 1px solid var(--xn-line-2); font-size: 12px; color: var(--xn-ink-3); }
.auth-agree span { color: var(--xn-ink-2); }

.auth-demo { display: flex; align-items: flex-start; gap: 10px; width: 100%; max-width: 420px; padding: 12px 14px; border: 1px dashed #D9B48E; border-radius: var(--xn-r-lg); background: #FFFBF6; box-sizing: border-box; }
.auth-demo p { margin: 0; font-size: 13px; line-height: 1.7; color: var(--xn-ink-2); }
.auth__foot { padding: 16px; text-align: center; font-size: 12px; color: var(--xn-ink-3); }

@media (max-width: 480px) {
  .auth__top { padding: 16px; }
  .auth-card { padding: 28px 20px 22px; }
  .auth-mobile { grid-template-columns: 1fr; }
}
</style>
