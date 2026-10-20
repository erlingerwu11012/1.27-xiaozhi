<template>
  <auth-layout :title="$t('register.title')" :subtitle="$t('register.welcome')">
    <form class="auth-form" @submit.prevent="register">
      <label v-if="!enableMobileRegister" class="auth-field">
        <span class="auth-field__label">{{ $t('xn.auth.username') }}</span>
        <el-input v-model="form.username" :placeholder="$t('register.usernamePlaceholder')" autocomplete="username" />
      </label>
      <template v-else>
        <div class="auth-field">
          <span class="auth-field__label">{{ $t('xn.auth.mobile') }}</span>
          <div class="auth-mobile">
            <el-select v-model="form.areaCode">
              <el-option v-for="item in mobileAreaList" :key="item.key" :label="`${item.name} (${item.key})`" :value="item.key" />
            </el-select>
            <el-input v-model="form.mobile" :placeholder="$t('register.mobilePlaceholder')" autocomplete="tel" />
          </div>
        </div>
        <div class="auth-field">
            <span class="auth-field__label">{{ $t('xn.auth.captcha') }}</span>
            <div class="auth-captcha">
              <el-input v-model="form.captcha" :placeholder="$t('register.captchaPlaceholder')" autocomplete="off" />
              <button type="button" class="auth-captcha__img" :title="$t('xn.auth.refreshCaptcha')" :aria-label="$t('xn.auth.refreshCaptcha')" @click="fetchCaptcha">
                <img v-if="captchaUrl" :src="captchaUrl" alt="" /><xn-icon v-else name="refresh" />
              </button>
            </div>
          </div>
        <div class="auth-field">
          <span class="auth-field__label">{{ $t('retrievePassword.mobileCaptcha') }}</span>
          <div class="auth-sms">
            <el-input v-model="form.mobileCaptcha" :placeholder="$t('register.mobileCaptchaPlaceholder')" maxlength="6" autocomplete="one-time-code" />
            <el-button :disabled="!canSendMobileCaptcha" @click="sendMobileCaptcha">
              {{ countdown > 0 ? `${countdown}${$t('register.secondsLater')}` : $t('register.sendCaptcha') }}
            </el-button>
          </div>
        </div>
      </template>
      <label class="auth-field">
        <span class="auth-field__label">{{ $t('xn.auth.password') }}</span>
        <el-input v-model="form.password" :placeholder="$t('register.passwordPlaceholder')" type="password" show-password autocomplete="new-password" />
      </label>
      <label class="auth-field">
        <span class="auth-field__label">{{ $t('xn.auth.confirmPassword') }}</span>
        <el-input v-model="form.confirmPassword" :placeholder="$t('register.confirmPasswordPlaceholder')" type="password" show-password autocomplete="new-password" />
      </label>
      <template v-if="!enableMobileRegister">
          <div class="auth-field">
            <span class="auth-field__label">{{ $t('xn.auth.captcha') }}</span>
            <div class="auth-captcha">
              <el-input v-model="form.captcha" :placeholder="$t('register.captchaPlaceholder')" autocomplete="off" />
              <button type="button" class="auth-captcha__img" :title="$t('xn.auth.refreshCaptcha')" :aria-label="$t('xn.auth.refreshCaptcha')" @click="fetchCaptcha">
                <img v-if="captchaUrl" :src="captchaUrl" alt="" /><xn-icon v-else name="refresh" />
              </button>
            </div>
          </div>
      </template>
      <el-button type="primary" native-type="submit" class="auth-submit">{{ $t('register.registerButton') }}</el-button>
      <div class="auth-links">
        <a href="javascript:void(0)" @click.prevent="goToLogin">{{ $t('register.goToLogin') }}</a>
      </div>
    </form>
    <p class="auth-agree">
      {{ $t('register.agreeTo') }} <span>{{ $t('register.userAgreement') }}</span> {{ $t('login.and') }} <span>{{ $t('register.privacyPolicy') }}</span>
    </p>
  </auth-layout>
</template>

<script>
import Api from '@/apis/api';
import AuthLayout from '@/components/layout/AuthLayout.vue';
import { getUUID, goToPage, showDanger, showSuccess, sm2Encrypt, validateMobile } from '@/utils';
import { mapState } from 'vuex';

// 导入语言切换功能

export default {
  name: 'register',
  components: {
    AuthLayout
  },
  computed: {
    ...mapState({
      allowUserRegister: state => state.pubConfig.allowUserRegister,
      enableMobileRegister: state => state.pubConfig.enableMobileRegister,
      mobileAreaList: state => state.pubConfig.mobileAreaList,
      sm2PublicKey: state => state.pubConfig.sm2PublicKey,
    }),
    canSendMobileCaptcha() {
      return this.countdown === 0 && validateMobile(this.form.mobile, this.form.areaCode);
    }
  },
  data() {
    return {
      form: {
        username: '',
        password: '',
        confirmPassword: '',
        captcha: '',
        captchaId: '',
        areaCode: '+86',
        mobile: '',
        mobileCaptcha: ''
      },
      captchaUrl: '',
      countdown: 0,
      timer: null,
    }
  },
  mounted() {
    this.$store.dispatch('fetchPubConfig').then(() => {
      if (!this.allowUserRegister) {
        showDanger(this.$t('register.notAllowRegister'));
        setTimeout(() => {
          goToPage('/login');
        }, 1500);
      }
    });
    this.fetchCaptcha();
  },
  methods: {
    // 复用验证码获取方法
    fetchCaptcha() {
      this.form.captchaId = getUUID();
      Api.user.getCaptcha(this.form.captchaId, (res) => {
        if (res.status === 200) {
          const blob = new Blob([res.data], { type: res.data.type });
          this.captchaUrl = URL.createObjectURL(blob);

        } else {
          console.error('验证码加载异常:', error);
          showDanger(this.$t('register.captchaLoadFailed'));
        }
      });
    },

    // 封装输入验证逻辑
    validateInput(input, message) {
      if (!input.trim()) {
        showDanger(message);
        return false;
      }
      return true;
    },

    // 发送手机验证码
    sendMobileCaptcha() {
      if (!validateMobile(this.form.mobile, this.form.areaCode)) {
        showDanger(this.$t('register.inputCorrectMobile'));
        return;
      }

      // 验证图形验证码
      if (!this.validateInput(this.form.captcha, this.$t('register.inputCaptcha'))) {
        this.fetchCaptcha();
        return;
      }

      // 清除可能存在的旧定时器
      if (this.timer) {
        clearInterval(this.timer);
        this.timer = null;
      }

      // 开始倒计时
      this.countdown = 60;
      this.timer = setInterval(() => {
        if (this.countdown > 0) {
          this.countdown--;
        } else {
          clearInterval(this.timer);
          this.timer = null;
        }
      }, 1000);

      // 调用发送验证码接口
      Api.user.sendSmsVerification({
        phone: this.form.areaCode + this.form.mobile,
        captcha: this.form.captcha,
        captchaId: this.form.captchaId
      }, (res) => {
        showSuccess(this.$t('register.captchaSendSuccess'));
      }, (err) => {
        showDanger(err.data.msg || this.$t('register.captchaSendFailed'));
        this.countdown = 0;
        this.fetchCaptcha();
      });
    },

    // 注册逻辑
    async register() {
      if (this.enableMobileRegister) {
        // 手机号注册验证
        if (!validateMobile(this.form.mobile, this.form.areaCode)) {
          showDanger(this.$t('register.inputCorrectMobile'));
          return;
        }
        if (!this.form.mobileCaptcha) {
          showDanger(this.$t('register.requiredMobileCaptcha'));
          return;
        }
      } else {
        // 用户名注册验证
        if (!this.validateInput(this.form.username, this.$t('register.requiredUsername'))) {
          return;
        }
      }

      // 验证密码
      if (!this.validateInput(this.form.password, this.$t('register.requiredPassword'))) {
        return;
      }
      if (this.form.password !== this.form.confirmPassword) {
        showDanger(this.$t('register.passwordsNotMatch'))
        return
      }
      // 验证验证码
      if (!this.validateInput(this.form.captcha, this.$t('register.requiredCaptcha'))) {
        return;
      }
      // 加密
      let encryptedPassword;
      try {
        // 拼接验证码和密码
        const captchaAndPassword = this.form.captcha + this.form.password;
        encryptedPassword = sm2Encrypt(this.sm2PublicKey, captchaAndPassword);
      } catch (error) {
        console.error("密码加密失败:", error);
        showDanger(this.$t('sm2.encryptionFailed'));
        return;
      }

      let plainUsername;
      if (this.enableMobileRegister) {
        plainUsername = this.form.areaCode + this.form.mobile;
      } else {
        plainUsername = this.form.username;
      }

      // 准备注册数据
      const registerData = {
        username: plainUsername,
        password: encryptedPassword,
        captchaId: this.form.captchaId,
        mobileCaptcha: this.form.mobileCaptcha
      };

      Api.user.register(registerData, ({ data }) => {
        showSuccess(this.$t('register.registerSuccess'))
        goToPage('/login')
      }, (err) => {
        showDanger(err.data.msg || this.$t('register.registerFailed'))
        if (err.data != null && err.data.msg != null && err.data.msg.indexOf('图形验证码') > -1) {
          this.fetchCaptcha()
        }
      })
    },

    goToLogin() {
      goToPage('/login')
    }
  },
  beforeDestroy() {
    if (this.timer) {
      clearInterval(this.timer);
    }
  }
}
</script>
