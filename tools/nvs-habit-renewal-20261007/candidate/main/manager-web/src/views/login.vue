<template>
  <div class="welcome login-dark-theme">
    <!-- 背景画板 (代码雨) - 包裹层用于 Matrix dive-in 变换 -->
    <div
      class="matrix-bg-wrap"
      :class="{ 'dive-in': isDiving }"
    >
      <canvas id="bgCanvas" ref="bgCanvas"></canvas>
    </div>

    <!-- 前景容器 -->
    <div class="ui-container">
      <!-- Logo 与语言切换 (固定在左上) -->
      <div class="top-bar">
        <img loading="lazy" alt="" src="@/assets/xiaozhi-logo.png" class="logo-img" />
        <img loading="lazy" alt="" src="@/assets/xiaozhi-ai.png" class="logo-text" />
        <el-dropdown trigger="click" class="title-language-dropdown"
          @visible-change="handleLanguageDropdownVisibleChange">
          <span class="el-dropdown-link">
            <span class="current-language-text">{{ currentLanguageText }}</span>
            <i class="el-icon-arrow-down el-icon--right" :class="{ 'rotate-down': languageDropdownVisible }"></i>
          </span>
          <el-dropdown-menu slot="dropdown">
            <el-dropdown-item @click.native="changeLanguage('zh_CN')">{{ $t("language.zhCN") }}</el-dropdown-item>
            <el-dropdown-item @click.native="changeLanguage('zh_TW')">{{ $t("language.zhTW") }}</el-dropdown-item>
            <el-dropdown-item @click.native="changeLanguage('en')">{{ $t("language.en") }}</el-dropdown-item>
            <el-dropdown-item @click.native="changeLanguage('de')">{{ $t("language.de") }}</el-dropdown-item>
            <el-dropdown-item @click.native="changeLanguage('vi')">{{ $t("language.vi") }}</el-dropdown-item>
          </el-dropdown-menu>
        </el-dropdown>
      </div>

      <!-- 状态一：初始胶囊菜单 -->
      <div :class="['pill-menu', 'glass-panel', { hidden: showLogin }]">
        <button v-if="allowUserRegister" type="button" class="pill-btn btn-register" @click="openRegister">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M18 9v3m0 0v3m0-3h3m-3 0h-3m-2-5a4 4 0 11-8 0 4 4 0 018 0zM3 20a6 6 0 0112 0v1H3v-1z"></path></svg>
          {{ $t("login.register") }}
        </button>
        <button type="button" class="pill-btn btn-login" @click="openLogin">
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1"></path></svg>
          {{ $t("login.login") }}
        </button>
        <button type="button" class="pill-btn btn-explore" @click.prevent>
          <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
          探索
        </button>
      </div>

      <!-- 状态二：登录/注册表单弹窗 -->
      <div
        :class="[
          'login-modal',
          'glass-panel',
          {
            active: showLogin,
            preparing: isPreparing,
            'dive-in': isDiving
          }
        ]"
      >
        <button type="button" class="close-btn" @click="closeLogin">
          <svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
        </button>

        <!-- 登录模式 -->
        <template v-if="!isRegisterMode">
          <div class="modal-header">
            <div class="hi-icon">Hi</div>
            <div class="title-box">
              <h2>{{ $t("login.title") }}</h2>
              <span>{{ $t("login.welcome") }}</span>
            </div>
          </div>

          <form v-if="showLogin" key="login-form" class="form-body" autocomplete="off" @submit.prevent="handleSubmit" @keyup.enter="handleSubmit">
            <!-- 用户名登录 -->
            <template v-if="!isMobileLogin">
              <div class="input-group">
                <svg class="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
                <el-input ref="loginUsername" :value="form.username" :placeholder="$t('login.usernamePlaceholder')" name="username" autocomplete="off" id="username"
                  :readonly="!credentialEditing.username" @focus="beginCredentialEdit('username')" @blur="endCredentialEdit('username')"
                  @input="updateLoginCredential('username', $event)" @change="updateLoginCredential('username', $event)" />
              </div>
            </template>

            <!-- 手机号登录 -->
            <template v-else>
              <div class="input-group input-group-mobile">
                <svg class="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"></path></svg>
                <el-select v-model="form.areaCode" class="area-select">
                  <el-option v-for="item in mobileAreaList" :key="item.key" :label="`${item.name} (${item.key})`" :value="item.key" />
                </el-select>
                <el-input v-model="form.mobile" :placeholder="$t('login.mobilePlaceholder')" />
              </div>
            </template>

            <div class="input-group">
              <svg class="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>
              <el-input ref="loginPassword" :value="form.password" :placeholder="$t('login.passwordPlaceholder')" type="password" name="password" autocomplete="off" id="password" show-password
                :readonly="!credentialEditing.password" @focus="beginCredentialEdit('password')" @blur="endCredentialEdit('password')"
                @input="updateLoginCredential('password', $event)" @change="updateLoginCredential('password', $event)" />
            </div>

            <div class="captcha-row">
              <div class="input-group">
                <svg class="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
                <el-input v-model="form.captcha" :placeholder="$t('login.captchaPlaceholder')" autocomplete="off" />
              </div>
              <div class="captcha-img-box" title="换一张" @click="fetchCaptcha">
                <img v-if="captchaUrl" loading="lazy" :src="captchaUrl" alt="验证码" />
                <span v-else class="captcha-loading">{{ $t('login.captchaPlaceholder') }}</span>
              </div>
            </div>

            <div class="action-row">
              <a v-if="allowUserRegister" href="javascript:void(0)" @click.prevent="switchToRegister">{{ $t("login.register") }}</a>
              <a v-if="enableMobileRegister" href="javascript:void(0)" class="forget-link" @click.prevent="goToForgetPassword">{{ $t("login.forgetPassword") }}</a>
            </div>

            <button type="button" class="submit-btn" @click="login">{{ $t("login.login") }}</button>

            <!-- 登录方式切换 -->
            <div v-if="enableMobileRegister" class="login-type-container">
              <el-tooltip :content="$t('login.mobileLogin')" placement="bottom">
                <el-button :type="isMobileLogin ? 'primary' : 'default'" icon="el-icon-mobile" circle @click="switchLoginType('mobile')"></el-button>
              </el-tooltip>
              <el-tooltip :content="$t('login.usernameLogin')" placement="bottom">
                <el-button :type="!isMobileLogin ? 'primary' : 'default'" icon="el-icon-user" circle @click="switchLoginType('username')"></el-button>
              </el-tooltip>
            </div>

            <div class="agree-text">
              {{ $t("login.agreeTo") }}
              <span class="link" @click.prevent>{{ $t("login.userAgreement") }}</span>
              {{ $t("login.and") }}
              <span class="link" @click.prevent>{{ $t("login.privacyPolicy") }}</span>
            </div>
          </form>
        </template>

        <!-- 注册模式 -->
        <template v-else>
          <div class="modal-header">
            <div class="hi-icon">Hi</div>
            <div class="title-box">
              <h2>{{ $t("register.title") }}</h2>
              <span>{{ $t("register.welcome") }}</span>
            </div>
          </div>

          <form v-if="showLogin" key="register-form" class="form-body" @submit.prevent="handleSubmit">
            <div class="input-group">
              <svg class="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"></path><circle cx="12" cy="7" r="4"></circle></svg>
              <el-input v-model="form.username" :placeholder="$t('register.usernamePlaceholder')" name="username" autocomplete="username" id="register-username" />
            </div>

            <div class="input-group">
              <svg class="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>
              <el-input v-model="form.password" :placeholder="$t('register.passwordPlaceholder')" type="password" name="password" autocomplete="new-password" id="register-password" show-password />
            </div>

            <div class="input-group">
              <svg class="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect><path d="M7 11V7a5 5 0 0 1 10 0v4"></path></svg>
              <el-input v-model="form.confirmPassword" :placeholder="$t('register.confirmPasswordPlaceholder')" type="password" name="confirmPassword" autocomplete="new-password" id="register-confirm-password" show-password />
            </div>

            <div class="captcha-row">
              <div class="input-group">
                <svg class="input-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"></path></svg>
                <el-input v-model="form.captcha" :placeholder="$t('register.captchaPlaceholder')" autocomplete="off" />
              </div>
              <div class="captcha-img-box" title="换一张" @click="fetchCaptcha">
                <img v-if="captchaUrl" loading="lazy" :src="captchaUrl" alt="验证码" />
                <span v-else class="captcha-loading">{{ $t('register.captchaPlaceholder') }}</span>
              </div>
            </div>

            <div class="action-row">
              <a href="javascript:void(0)" @click.prevent="switchToLogin">{{ $t("register.goToLogin") }}</a>
            </div>

            <button type="button" class="submit-btn" @click="register">{{ $t("register.registerButton") }}</button>

            <div class="agree-text">
              {{ $t("register.agreeTo") }}
              <span class="link" @click.prevent>{{ $t("register.userAgreement") }}</span>
              {{ $t("register.and") }}
              <span class="link" @click.prevent>{{ $t("register.privacyPolicy") }}</span>
            </div>
          </form>
        </template>
      </div>
    </div>

    <div class="footer-text">
      <version-footer />
    </div>
  </div>
</template>

<script>
import Api from "@/apis/api";
import VersionFooter from "@/components/VersionFooter.vue";
import i18n, { changeLanguage } from "@/i18n";
import store from "@/store";
import { getUUID, goToPage, showDanger, showSuccess, sm2Encrypt, validateMobile } from "@/utils";
import { mapState } from "vuex";

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
      showLogin: false,
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
      languageDropdownVisible: false,
      codeRainTimer: null,
      codeRainDrops: null,
      codeRainCtx: null,
      isPreparing: false,
      isDiving: false,
      fetchCaptchaTimer: null,
      credentialEditing: { username: false, password: false },
      credentialGuardTimer: null,
      // Values live only in this component. Never persist credentials in storage.
      credentialGuardReady: false,
    };
  },
  mounted() {
    this.fetchCaptcha();
    this.$store.dispatch("fetchPubConfig").then(() => {
      // A delayed response must not replace fields the user is already using.
      if (!this.showLogin) this.isMobileLogin = this.enableMobileRegister;
    });
    this.initCodeRain();
    window.addEventListener("resize", this.resizeCodeRain);
  },
  updated() {
    this.restoreInactiveCredentials();
  },
  beforeDestroy() {
    this.stopCredentialGuard();
    if (this.codeRainTimer) clearInterval(this.codeRainTimer);
    if (this.fetchCaptchaTimer) {
      clearTimeout(this.fetchCaptchaTimer);
      this.fetchCaptchaTimer = null;
    }
    window.removeEventListener("resize", this.resizeCodeRain);
  },
  methods: {
    openLogin() {
      this.showLogin = true;
      this.isRegisterMode = false;
      this.startCredentialGuard();
    },
    openRegister() {
      this.stopCredentialGuard();
      this.showLogin = true;
      this.isRegisterMode = true;
      this.fetchCaptcha();
    },
    closeLogin() {
      this.stopCredentialGuard();
      this.showLogin = false;
    },
    switchToRegister() {
      this.stopCredentialGuard();
      this.isRegisterMode = true;
      this.form.confirmPassword = "";
      this.fetchCaptcha();
    },
    switchToLogin() {
      this.isRegisterMode = false;
      this.form.confirmPassword = "";
      this.startCredentialGuard();
    },
    credentialInput(field) {
      const component = this.$refs[field === 'username' ? 'loginUsername' : 'loginPassword'];
      return component && component.getInput ? component.getInput() : null;
    },
    startCredentialGuard() {
      this.stopCredentialGuard();
      this.credentialGuardReady = true;
      this.credentialGuardTimer = setInterval(() => this.restoreInactiveCredentials(), 200);
      this.$nextTick(() => this.restoreInactiveCredentials());
    },
    stopCredentialGuard() {
      if (this.credentialGuardTimer) clearInterval(this.credentialGuardTimer);
      this.credentialGuardTimer = null;
      this.credentialGuardReady = false;
      this.credentialEditing.username = false;
      this.credentialEditing.password = false;
    },
    beginCredentialEdit(field) {
      if (!this.credentialGuardReady) return;
      // Remove readonly immediately so the first key/paste does not get lost.
      this.credentialEditing[field] = true;
      const input = this.credentialInput(field);
      if (input) { input.readOnly = false; input.value = this.form[field]; }
    },
    endCredentialEdit(field) {
      this.credentialEditing[field] = false;
      this.restoreInactiveCredentials();
    },
    updateLoginCredential(field, value) {
      const input = this.credentialInput(field);
      // Browser/extension fills arriving after focus moved to captcha must not
      // replace the selected account, or pair it with a different password.
      if (!this.credentialGuardReady || !this.credentialEditing[field] ||
          !input || document.activeElement !== input) {
        this.$nextTick(() => this.restoreInactiveCredentials());
        return;
      }
      this.form[field] = value;
    },
    restoreInactiveCredentials() {
      if (!this.credentialGuardReady || !this.showLogin || this.isRegisterMode) return;
      for (const field of ['username', 'password']) {
        const component = this.$refs[field === 'username' ? 'loginUsername' : 'loginPassword'];
        const input = this.credentialInput(field);
        if (input) {
          input.readOnly = !this.credentialEditing[field];
          // Silent fills must not desynchronise the shown value and Vue state.
          if (!input.composing && !component.isComposing && input.value !== this.form[field]) input.value = this.form[field];
        }
      }
    },
    handleSubmit() {
      if (this.isRegisterMode) {
        this.register();
      } else {
        this.login();
      }
    },

    initCodeRain() {
      const canvas = this.$refs.bgCanvas;
      if (!canvas) return;
      canvas.width = window.innerWidth;
      canvas.height = window.innerHeight;
      const ctx = canvas.getContext("2d");
      this.codeRainCtx = ctx;

      const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/<>{}[]!@#$%^&*".split("");
      const fontSize = 14;
      const columns = Math.floor(canvas.width / fontSize);
      const drops = Array(Math.max(columns, 1)).fill(1);
      this.codeRainDrops = drops;

      const draw = (speed = 1, glow = false) => {
        const canvas = this.$refs.bgCanvas;
        const ctx = this.codeRainCtx;
        const drops = this.codeRainDrops;
        if (!canvas || !ctx || !drops) return;

        ctx.fillStyle = "rgba(6, 5, 29, 0.08)";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.font = fontSize + "px monospace";

        if (glow) {
          ctx.shadowBlur = 12;
          ctx.shadowColor = "rgba(129, 140, 248, 0.9)";
        }

        for (let i = 0; i < drops.length; i++) {
          const text = chars[Math.floor(Math.random() * chars.length)];
          if (Math.random() > 0.98) ctx.fillStyle = "rgba(255, 255, 255, 0.9)";
          else if (Math.random() > 0.8) ctx.fillStyle = "rgba(129, 140, 248, 0.65)";
          else ctx.fillStyle = "rgba(255, 255, 255, 0.25)";

          ctx.fillText(text, i * fontSize, drops[i] * fontSize);
          if (drops[i] * fontSize > canvas.height && Math.random() > 0.975) drops[i] = 0;
          drops[i] += speed;
        }

        if (glow) {
          ctx.shadowBlur = 0;
          ctx.shadowColor = "transparent";
        }
      };

      const normalDraw = () => draw(1, false);
      this.codeRainTimer = setInterval(normalDraw, 45);
    },
    accelerateCodeRain() {
      if (!this.codeRainDrops || !this.codeRainCtx) return;
      if (this.codeRainTimer) {
        clearInterval(this.codeRainTimer);
        this.codeRainTimer = null;
      }

      const draw = (speed, glow) => {
        const canvas = this.$refs.bgCanvas;
        const ctx = this.codeRainCtx;
        const drops = this.codeRainDrops;
        if (!canvas || !ctx || !drops) return;

        ctx.fillStyle = "rgba(6, 5, 29, 0.06)";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.font = "14px monospace";

        if (glow) {
          ctx.shadowBlur = 14;
          ctx.shadowColor = "rgba(129, 140, 248, 0.9)";
        }

        const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/<>{}[]!@#$%^&*".split("");
        const fontSize = 14;
        for (let i = 0; i < drops.length; i++) {
          const text = chars[Math.floor(Math.random() * chars.length)];
          if (Math.random() > 0.95) ctx.fillStyle = "rgba(255, 255, 255, 0.95)";
          else if (Math.random() > 0.7) ctx.fillStyle = "rgba(129, 140, 248, 0.75)";
          else ctx.fillStyle = "rgba(255, 255, 255, 0.35)";

          ctx.fillText(text, i * fontSize, drops[i] * fontSize);
          if (drops[i] * fontSize > canvas.height && Math.random() > 0.95) drops[i] = 0;
          drops[i] += speed;
        }

        if (glow) {
          ctx.shadowBlur = 0;
          ctx.shadowColor = "transparent";
        }
      };

      const fastDraw = () => draw(12, true);
      this.codeRainTimer = setInterval(fastDraw, 6);
    },
    slowCodeRain() {
      if (!this.codeRainDrops || !this.codeRainCtx) return;
      if (this.codeRainTimer) {
        clearInterval(this.codeRainTimer);
        this.codeRainTimer = null;
      }

      const draw = (speed) => {
        const canvas = this.$refs.bgCanvas;
        const ctx = this.codeRainCtx;
        const drops = this.codeRainDrops;
        if (!canvas || !ctx || !drops) return;

        ctx.fillStyle = "rgba(6, 5, 29, 0.1)";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.font = "14px monospace";

        const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789/<>{}[]!@#$%^&*".split("");
        const fontSize = 14;
        for (let i = 0; i < drops.length; i++) {
          const text = chars[Math.floor(Math.random() * chars.length)];
          if (Math.random() > 0.98) ctx.fillStyle = "rgba(255, 255, 255, 0.8)";
          else if (Math.random() > 0.8) ctx.fillStyle = "rgba(129, 140, 248, 0.5)";
          else ctx.fillStyle = "rgba(255, 255, 255, 0.15)";

          ctx.fillText(text, i * fontSize, drops[i] * fontSize);
          if (drops[i] * fontSize > canvas.height && Math.random() > 0.975) drops[i] = 0;
          drops[i] += speed;
        }
      };

      const slowDraw = () => draw(0.15);
      this.codeRainTimer = setInterval(slowDraw, 80);
    },
    resizeCodeRain() {
      const canvas = this.$refs.bgCanvas;
      if (canvas) {
        canvas.width = window.innerWidth;
        canvas.height = window.innerHeight;
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

    handleLanguageDropdownVisibleChange(visible) {
      this.languageDropdownVisible = visible;
    },

    changeLanguage(lang) {
      changeLanguage(lang);
      this.languageDropdownVisible = false;
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
      this.restoreInactiveCredentials();
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

    goToForgetPassword() {
      goToPage("/retrieve-password");
    },

    /**
     * 登录成功后的 Matrix 风格转场 - 严格异步时序，防止提前跳转
     * 关键：setToken 必须延后到 T=2600ms 执行，否则 fetchCaptcha 会检测到 token 并立即跳转
     *
     * T=0ms:    isPreparing=true，代码雨减速、登录框发光，绝不跳转
     * T=400ms:  isDiving=true，3D 穿梭（scale 5 + opacity 0，1.8s transition）
     * T=2200ms: isFlashing=true，全屏爆白（白屏 div opacity 1）
     * T=2600ms: setToken + router.push，此时屏幕已纯白，完美掩盖 DOM 切换
     */
    handleLoginSuccess(data) {
      showSuccess(this.$t("login.loginSuccess"));
      const tokenData = JSON.stringify(data.data);

      // T=0ms：蓄力与锁定，绝不设置 token，绝不跳转
      this.isPreparing = true;
      this.slowCodeRain();

      // T=400ms：开始 3D 穿梭
      setTimeout(() => {
        this.isPreparing = false;
        this.isDiving = true;
        this.accelerateCodeRain();
      }, 400);

      // T=2200ms：全屏爆白（白屏 div 在 App.vue，不受路由切换影响）
      setTimeout(() => {
        this.isDiving = false;
        if (this.codeRainTimer) {
          clearInterval(this.codeRainTimer);
          this.codeRainTimer = null;
        }
        store.commit("setMatrixFlash", { phase: "burst" });
      }, 2200);

      // T=2600ms：此时屏幕已完全变白，才允许 setToken 和路由跳转
      setTimeout(() => {
        this.$store.commit("setToken", tokenData);
        store.commit("setMatrixFlash", { phase: "fadeout" });
        goToPage("/home");
      }, 2600);

      // 收尾：清理闪光状态 (3000ms)
      setTimeout(() => {
        store.commit("setMatrixFlash", null);
      }, 3000);
    },
  },
};
</script>

<style lang="scss" scoped>
.login-dark-theme {
  margin: 0;
  padding: 0;
  width: 100%;
  height: 100vh;
  min-height: 100vh;
  overflow: hidden;
  background-color: #06051d;
  font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
  color: #ffffff;
}

/* 数字雨背景包裹层 - 用于 Matrix dive-in 伪 3D 变换 */
.matrix-bg-wrap {
  position: absolute;
  top: 0;
  left: 0;
  z-index: 1;
  width: 100%;
  height: 100%;
  transform-origin: center center;
  transition: transform 1.8s cubic-bezier(0.85, 0, 0.15, 1),
    filter 1.8s cubic-bezier(0.85, 0, 0.15, 1);
}

.matrix-bg-wrap.dive-in {
  transform: scale(2);
  filter: blur(4px);
}

#bgCanvas {
  display: block;
  width: 100%;
  height: 100%;
  pointer-events: none;
}

.ui-container {
  position: relative;
  z-index: 10;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  pointer-events: none;
  perspective: 1200px;
  transform-style: preserve-3d;
}

.top-bar {
  position: absolute;
  top: 20px;
  left: 20px;
  display: flex;
  align-items: center;
  gap: 10px;
  pointer-events: auto;
  z-index: 20;
}

.logo-img {
  width: 45px;
  height: 45px;
}

.logo-text {
  height: 18px;
}

.title-language-dropdown {
  margin-left: 10px;
}

.el-dropdown-link {
  color: #d1d5db;
  font-size: 12px;
  cursor: pointer;
}

.current-language-text {
  margin: 0 4px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.8);
}

.rotate-down {
  transform: rotate(180deg);
}

.el-icon-arrow-down {
  transition: transform 0.3s ease;
}

.glass-panel {
  pointer-events: auto;
  background: rgba(255, 255, 255, 0.45);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  border: 1px solid rgba(255, 255, 255, 0.7);
  box-shadow: 0 20px 40px rgba(0, 0, 0, 0.6), inset 0 1px 0 rgba(255, 255, 255, 0.1);
}

/* 全息科幻入口 - Holo-Panel */
/* 全息科幻入口 - 深色半透明玻璃，星际静谧蓝 */
.pill-menu {
  display: flex;
  gap: 0;
  padding: 14px 28px;
  border-radius: 50px;
  transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
  background: linear-gradient(135deg, rgba(255, 255, 255, 0.1), rgba(0, 70, 150, 0.2));
  backdrop-filter: blur(25px);
  -webkit-backdrop-filter: blur(25px);
  border: 1px solid rgba(255, 255, 255, 0.3);
  box-shadow: 0 0 20px rgba(0, 140, 255, 0.3), inset 0 0 15px rgba(255, 255, 255, 0.05);
}

.pill-menu.hidden {
  opacity: 0;
  transform: scale(0.9) translateY(20px);
  pointer-events: none;
  position: absolute;
}

.pill-btn {
  display: flex;
  align-items: center;
  gap: 12px;
  background: transparent;
  border: none;
  color: #e2e8f0;
  padding: 10px 24px;
  border-radius: 50px;
  font-size: 14px;
  font-family: monospace, "SF Mono", "Fira Code", Consolas, monospace;
  letter-spacing: 1px;
  cursor: pointer;
  transition: all 0.3s ease;
  border-right: 1px solid rgba(255, 255, 255, 0.1);
  position: relative;
  z-index: 2;
}

.pill-btn:last-child {
  border-right: none;
}

.pill-btn svg {
  width: 18px;
  height: 18px;
  color: #00f2ff;
  stroke: #00f2ff;
}

.pill-btn:hover {
  background: rgba(255, 255, 255, 0.15);
  color: #ffffff;
  text-shadow: 0 0 12px rgba(0, 242, 255, 0.6);
  transform: translateY(-2px);
  box-shadow: 0 4px 0 0 rgba(0, 242, 255, 0.6);
}

.pill-btn:hover svg {
  color: #00f2ff;
  filter: drop-shadow(0 0 4px rgba(0, 242, 255, 0.8));
}

/* 深海全息透镜 - 暗黑科幻弹窗主体 */
.login-modal,
:deep(.el-dialog),
:deep(.ant-modal-content) {
  background: rgba(15, 23, 42, 0.6) !important;
  backdrop-filter: blur(24px) !important;
  -webkit-backdrop-filter: blur(24px) !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.8), inset 0 1px 0 rgba(255, 255, 255, 0.1) !important;
}

.login-modal {
  width: 400px;
  border-radius: 20px;
  padding: 40px 40px 32px 40px;
  position: absolute;
  opacity: 0;
  transform: scale(0.95) translateY(10px);
  pointer-events: none;
  transition: all 0.5s cubic-bezier(0.4, 0, 0.2, 1);
}

.login-modal.active {
  opacity: 1;
  transform: scale(1) translateY(0);
  pointer-events: auto;
}

/* 阶段 1：蓄力与锁定 - 登录框强烈发光 */
.login-modal.preparing {
  box-shadow: 0 0 60px rgba(0, 242, 255, 0.8),
    0 0 120px rgba(56, 189, 248, 0.6),
    inset 0 0 30px rgba(255, 255, 255, 0.2) !important;
  border-color: rgba(0, 242, 255, 0.8) !important;
  transition: box-shadow 400ms ease, border-color 400ms ease;
}

.login-modal.preparing .form-body,
.login-modal.preparing .modal-header {
  opacity: 0.3;
  transition: opacity 400ms ease;
}

/* 阶段 2：Z 轴急速穿梭 - 使用 transition 确保 1.8s 平滑过渡，避免瞬间变大 */
.login-modal.dive-in {
  transform-origin: center center;
  transition: all 1.8s cubic-bezier(0.85, 0, 0.15, 1);
  transform: scale(5) translateZ(100px);
  filter: blur(8px);
  opacity: 0;
  pointer-events: none;
}

.close-btn {
  position: absolute;
  top: 20px;
  right: 20px;
  background: none;
  border: none;
  color: #9ca3af;
  cursor: pointer;
  width: 30px;
  height: 30px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: 0.3s;
}

.close-btn:hover {
  background: rgba(255, 255, 255, 0.1);
  color: white;
}

.modal-header {
  display: flex;
  align-items: center;
  gap: 15px;
  margin-bottom: 30px;
}

.hi-icon {
  background: linear-gradient(135deg, #0ea5e9 0%, #3b82f6 100%) !important;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: bold;
  font-style: italic;
  font-size: 18px;
  text-shadow: 0 2px 4px rgba(0, 0, 0, 0.3);
}

.title-box h2 {
  margin: 0;
  font-size: 22px;
  font-weight: 500;
  letter-spacing: 1px;
  color: #ffffff !important;
}

.title-box span {
  font-size: 10px;
  color: #94a3b8 !important;
  letter-spacing: 2px;
}

.form-body {
  padding: 0;
}

.input-group {
  display: flex;
  align-items: center;
  background: rgba(0, 0, 0, 0.4) !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  border-radius: 12px;
  padding: 14px 16px;
  margin-bottom: 16px;
  transition: 0.3s;
}

.input-group:focus-within {
  border-color: rgba(56, 189, 248, 0.6) !important;
  box-shadow: 0 0 15px rgba(56, 189, 248, 0.15) !important;
  background: rgba(0, 0, 0, 0.6) !important;
}

.input-group .input-icon,
.input-group svg {
  width: 18px;
  height: 18px;
  color: #64748b !important;
  margin-right: 12px;
  flex-shrink: 0;
  transition: 0.3s;
  stroke: #64748b !important;
  pointer-events: none; /* 防止图标遮挡输入框，确保点击可触发 autofill */
}

.input-group .el-input {
  flex: 1;
  min-width: 0;
}

.input-group .el-input__inner {
  width: 100% !important;
}

.input-group:focus-within .input-icon,
.input-group:focus-within svg {
  color: #38bdf8 !important;
  stroke: #38bdf8 !important;
}

.input-group-mobile {
  flex-wrap: wrap;
}

.input-group-mobile .area-select {
  width: 100px;
  margin-right: 8px;
}

.input-group-mobile .el-input {
  flex: 1;
  min-width: 120px;
}

.captcha-row {
  display: flex;
  gap: 12px;
  margin-bottom: 24px;
}

.captcha-row .input-group {
  margin-bottom: 0;
  flex: 1;
}

.captcha-img-box {
  width: 120px;
  height: 48px;
  background: rgba(0, 0, 0, 0.5) !important;
  border: 1px solid rgba(255, 255, 255, 0.1) !important;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  flex-shrink: 0;
  overflow: hidden;
}

.captcha-img-box img {
  width: 100%;
  height: 100%;
  object-fit: contain;
}

.captcha-loading {
  font-size: 12px;
  color: #94a3b8 !important;
}

.action-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  font-size: 13px;
}

.action-row a {
  color: #818cf8;
  text-decoration: none;
  cursor: pointer;
  transition: 0.3s;
}

.action-row a:hover {
  color: #a5b4fc;
  text-shadow: 0 0 8px rgba(129, 140, 248, 0.5);
}

.forget-link {
  color: #6b7280 !important;
}

.submit-btn {
  width: 100%;
  background: linear-gradient(135deg, #0ea5e9 0%, #3b82f6 100%) !important;
  color: white !important;
  border: none !important;
  padding: 14px;
  border-radius: 12px;
  font-size: 16px;
  font-weight: 500;
  cursor: pointer;
  transition: 0.3s;
  box-shadow: 0 4px 15px rgba(59, 130, 246, 0.3) !important;
}

.submit-btn:hover {
  filter: brightness(1.1);
  box-shadow: 0 6px 20px rgba(59, 130, 246, 0.4) !important;
  transform: translateY(-1px);
}

.login-type-container {
  margin: 16px 0;
  display: flex;
  justify-content: center;
  gap: 10px;
}

.agree-text {
  font-size: 14px;
  color: rgba(255, 255, 255, 0.55);
  text-align: center;
  margin-top: 32px;
  padding-bottom: 0;
}

.agree-text .link {
  color: #818cf8;
  cursor: pointer;
}

.footer-text {
  position: fixed;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 15;
  text-align: center;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.3);
  pointer-events: auto;
}

/* 强制接管输入框样式 - 消灭死白，赛博朋克深渊暗槽 */
:deep(.login-modal .input-group),
:deep(.login-modal .el-input),
:deep(.login-modal .el-input__wrapper),
:deep(.login-modal .ant-input-affix-wrapper),
:deep(.login-modal .el-input-group__append),
:deep(.login-modal .el-input-group__prepend) {
  background-color: rgba(0, 0, 0, 0.4) !important;
  border: 1px solid rgba(255, 255, 255, 0.08) !important;
  box-shadow: none !important;
  border-radius: 8px !important;
}

:deep(.login-modal .el-input__inner) {
  border: none !important;
}

/* 聚焦时的外框发光效果 */
:deep(.login-modal .input-group:focus-within),
:deep(.login-modal .el-input__wrapper.is-focus),
:deep(.login-modal .ant-input-affix-wrapper-focused) {
  background-color: rgba(0, 0, 0, 0.6) !important;
  border-color: rgba(56, 189, 248, 0.8) !important;
  box-shadow: 0 0 0 1px rgba(56, 189, 248, 0.5), 0 0 15px rgba(56, 189, 248, 0.2) !important;
}

:deep(.login-modal .input-group input),
:deep(.login-modal .el-input__inner),
:deep(.login-modal .ant-input) {
  background: transparent !important;
  color: #e2e8f0 !important;
  -webkit-text-fill-color: #e2e8f0 !important; /* 覆盖浏览器 autofill 黑色文字 */
  caret-color: #e2e8f0 !important;
  height: 40px !important;
}

/* 覆盖浏览器自动填充的黑色文字和背景 */
:deep(.login-modal input:-webkit-autofill),
:deep(.login-modal input:-webkit-autofill:hover),
:deep(.login-modal input:-webkit-autofill:focus),
:deep(.login-modal input:-webkit-autofill:active),
:deep(.login-modal .el-input__inner:-webkit-autofill),
:deep(.login-modal .el-input__inner:-webkit-autofill:hover),
:deep(.login-modal .el-input__inner:-webkit-autofill:focus),
:deep(.login-modal .el-input__inner:-webkit-autofill:active) {
  -webkit-text-fill-color: #e2e8f0 !important;
  -webkit-box-shadow: 0 0 0 1000px rgba(0, 0, 0, 0.4) inset !important; /* 覆盖 autofill 的黄白背景 */
  transition: background-color 5000s ease-in-out 0s, color 5000s ease-in-out 0s;
}

:deep(.login-modal input::placeholder),
:deep(.login-modal .el-input__inner::placeholder) {
  color: #475569 !important;
}

:deep(.login-modal .el-select .el-input__inner) {
  background: transparent !important;
  color: #e2e8f0 !important;
}

:v-deep(.login-modal .el-button--primary) {
  background: linear-gradient(135deg, #0ea5e9 0%, #3b82f6 100%) !important;
  border-color: transparent !important;
}

:v-deep(.login-modal .el-button--default) {
  background: rgba(255, 255, 255, 0.08) !important;
  border-color: rgba(255, 255, 255, 0.15) !important;
  color: #94a3b8 !important;
}

:v-deep(.copyright .beian-text),
:v-deep(.footer-content),
:v-deep(.footer-content span) {
  color: rgba(255, 255, 255, 0.5) !important;
}

:v-deep(.beian-link) {
  color: rgba(255, 255, 255, 0.6) !important;
}
</style>
