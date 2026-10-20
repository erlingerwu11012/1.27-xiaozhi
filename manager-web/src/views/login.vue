<template>
  <auth-layout :title="isRegisterMode ? $t('register.title') : $t('login.title')"
    :subtitle="isRegisterMode ? $t('register.welcome') : $t('login.welcome')">
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
  </auth-layout>
</template>

<script>
import Api from "@/apis/api";
import AuthLayout from "@/components/layout/AuthLayout.vue";
import i18n, { changeLanguage } from "@/i18n";
import { getUUID, goToPage, showDanger, showSuccess, sm2Encrypt, validateMobile } from "@/utils";
import { mapState } from "vuex";
import { isMockMode } from "@/mock/config";

export default {
  name: "login",
  components: {
    AuthLayout,
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
