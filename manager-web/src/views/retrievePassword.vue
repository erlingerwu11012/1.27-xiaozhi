<template>
  <auth-layout :title="$t('retrievePassword.title')" :subtitle="$t('xn.auth.retrieveSub')">
    <form class="auth-form" @submit.prevent="retrievePassword">
      <div class="auth-field">
        <span class="auth-field__label">{{ $t('retrievePassword.mobile') }}</span>
        <div class="auth-mobile">
          <el-select v-model="form.areaCode">
            <el-option v-for="item in mobileAreaList" :key="item.key" :label="`${item.name} (${item.key})`" :value="item.key" />
          </el-select>
          <el-input v-model="form.mobile" :placeholder="$t('retrievePassword.mobilePlaceholder')" autocomplete="tel" />
        </div>
      </div>
      <div class="auth-field">
            <span class="auth-field__label">{{ $t('xn.auth.captcha') }}</span>
            <div class="auth-captcha">
              <el-input v-model="form.captcha" :placeholder="$t('retrievePassword.captchaPlaceholder')" autocomplete="off" />
              <button type="button" class="auth-captcha__img" :title="$t('xn.auth.refreshCaptcha')" :aria-label="$t('xn.auth.refreshCaptcha')" @click="fetchCaptcha">
                <img v-if="captchaUrl" :src="captchaUrl" alt="" /><xn-icon v-else name="refresh" />
              </button>
            </div>
          </div>
      <div class="auth-field">
        <span class="auth-field__label">{{ $t('retrievePassword.mobileCaptcha') }}</span>
        <div class="auth-sms">
          <el-input v-model="form.mobileCaptcha" :placeholder="$t('retrievePassword.mobileCaptchaPlaceholder')" maxlength="6" autocomplete="one-time-code" />
          <el-button :disabled="!canSendMobileCaptcha" @click="sendMobileCaptcha">
            {{ countdown > 0 ? `${countdown}${$t('register.secondsLater')}` : $t('retrievePassword.getMobileCaptcha') }}
          </el-button>
        </div>
      </div>
      <label class="auth-field">
        <span class="auth-field__label">{{ $t('retrievePassword.newPassword') }}</span>
        <el-input v-model="form.newPassword" :placeholder="$t('retrievePassword.newPasswordPlaceholder')" type="password" show-password autocomplete="new-password" />
      </label>
      <label class="auth-field">
        <span class="auth-field__label">{{ $t('retrievePassword.confirmNewPassword') }}</span>
        <el-input v-model="form.confirmPassword" :placeholder="$t('retrievePassword.confirmNewPasswordPlaceholder')" type="password" show-password autocomplete="new-password" />
      </label>
      <el-button type="primary" native-type="submit" class="auth-submit">{{ $t('retrievePassword.resetButton') }}</el-button>
      <div class="auth-links">
        <a href="javascript:void(0)" @click.prevent="goToLogin">{{ $t('retrievePassword.goToLogin') }}</a>
      </div>
    </form>
  </auth-layout>
</template>

<script>
import Api from '@/apis/api';
import AuthLayout from '@/components/layout/AuthLayout.vue';
import { getUUID, goToPage, showDanger, showSuccess, validateMobile, sm2Encrypt } from '@/utils';
import { mapState } from 'vuex';

// 导入语言切换功能
import { changeLanguage } from '@/i18n';

export default {
  name: 'retrieve',
  components: {
    AuthLayout
  },
  computed: {
    ...mapState({
      allowUserRegister: state => state.pubConfig.allowUserRegister,
      mobileAreaList: state => state.pubConfig.mobileAreaList,
      sm2PublicKey: state => state.pubConfig.sm2PublicKey
    }),
    canSendMobileCaptcha() {
      return this.countdown === 0 && validateMobile(this.form.mobile, this.form.areaCode);
    }
  },
  data() {
    return {
      form: {
        areaCode: '+86',
        mobile: '',
        captcha: '',
        captchaId: '',
        mobileCaptcha: '',
        newPassword: '',
        confirmPassword: ''
      },
      captchaUrl: '',
      countdown: 0,
      timer: null
    }
  },
  mounted() {
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
        showDanger(this.$t('retrievePassword.inputCorrectMobile'));
        return;
      }

      // 验证图形验证码
      if (!this.validateInput(this.form.captcha, this.$t('retrievePassword.captchaRequired'))) {
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
        showSuccess(this.$t('retrievePassword.captchaSendSuccess'));
      }, (err) => {
        showDanger(err.data.msg || this.$t('register.captchaSendFailed'));
        this.countdown = 0;
        this.fetchCaptcha();
      });
    },

    // 修改逻辑
    retrievePassword() {
      // 验证逻辑
      if (!validateMobile(this.form.mobile, this.form.areaCode)) {
        showDanger(this.$t('retrievePassword.inputCorrectMobile'));
        return;
      }
      if (!this.form.captcha) {
        showDanger(this.$t('retrievePassword.captchaRequired'));
        return;
      }
      if (!this.form.mobileCaptcha) {
        showDanger(this.$t('retrievePassword.mobileCaptchaRequired'));
        return;
      }
      if (this.form.newPassword !== this.form.confirmPassword) {
        showDanger(this.$t('retrievePassword.passwordsNotMatch'));
        return;
      }

      // 加密密码
      let encryptedPassword;
      try {
        // 拼接图形验证码和新密码进行加密
        const captchaAndPassword = this.form.captcha + this.form.newPassword;
        encryptedPassword = sm2Encrypt(this.sm2PublicKey, captchaAndPassword);
      } catch (error) {
        console.error("密码加密失败:", error);
        showDanger(this.$t('sm2.encryptionFailed'));
        return;
      }

      Api.user.retrievePassword({
        phone: this.form.areaCode + this.form.mobile,
        password: encryptedPassword,
        code: this.form.mobileCaptcha,
        captchaId: this.form.captchaId
      }, (res) => {
        showSuccess(this.$t('retrievePassword.passwordUpdateSuccess'));
        goToPage('/login');
      }, (err) => {
        showDanger(err.data.msg || this.$t('message.error'));
        if (err.data != null && err.data.msg != null && (err.data.msg.indexOf('图形验证码') > -1 || err.data.msg.indexOf('Captcha') > -1)) {
          this.fetchCaptcha()
        }
      });
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
