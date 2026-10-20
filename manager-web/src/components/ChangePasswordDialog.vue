<template>
  <el-dialog :visible.sync="dialogVisible" :title="$t('changePassword.title')" width="440px" append-to-body
    custom-class="xn-dialog-narrow" @closed="resetForm">
    <el-form label-position="top" @submit.native.prevent="confirm">
      <el-form-item :label="$t('changePassword.oldPasswordLabel')" required>
        <el-input v-model="oldPassword" type="password" show-password autocomplete="current-password"
          :placeholder="$t('changePassword.oldPasswordPlaceholder')" />
      </el-form-item>
      <el-form-item :label="$t('changePassword.newPasswordLabel')" required>
        <el-input v-model="newPassword" type="password" show-password autocomplete="new-password"
          :placeholder="$t('changePassword.newPasswordPlaceholder')" />
      </el-form-item>
      <el-form-item :label="$t('changePassword.confirmPasswordLabel')" required>
        <el-input v-model="confirmNewPassword" type="password" show-password autocomplete="new-password"
          :placeholder="$t('changePassword.confirmPasswordPlaceholder')" @keyup.enter.native="confirm" />
      </el-form-item>
    </el-form>
    <span slot="footer">
      <el-button @click="cancel">{{ $t('changePassword.cancelButton') }}</el-button>
      <el-button type="primary" @click="confirm">{{ $t('changePassword.confirmButton') }}</el-button>
    </span>
  </el-dialog>
</template>

<script>
import userApi from '@/apis/module/user';
import { mapActions } from 'vuex';

export default {
  name: 'ChangePasswordDialog',
  props: {
    value: {
      type: Boolean,
      required: true
    }
  },
  data() {
    return {
      dialogVisible: this.value,
      oldPassword: "",
      newPassword: "",
      confirmNewPassword: ""
    }
  },
  watch: {
    value(val) {
      this.dialogVisible = val;
    },
    dialogVisible(val) {
      this.$emit('input', val);
    }
  },
  methods: {
    ...mapActions(['logout']), // 引入Vuex的logout action
    confirm() {
      if (!this.oldPassword.trim() || !this.newPassword.trim() || !this.confirmNewPassword.trim()) {
        this.$message.error(this.$t('changePassword.allFieldsRequired'));
        return;
      }
      if (this.newPassword !== this.confirmNewPassword) {
        this.$message.error(this.$t('changePassword.passwordsNotMatch'));
        return;
      }
      if (this.newPassword === this.oldPassword) {
        this.$message.error(this.$t('changePassword.newPasswordSameAsOld'));
        return;
      }

      // 修改后的接口调用
      userApi.changePassword(this.oldPassword, this.newPassword, (res) => {
        if (res.data.code === 0) {
          this.$message.success({
            message: this.$t('changePassword.passwordChangedSuccessfully'),
            showClose: true
          });
          this.logout().then(() => {
            this.$router.push('/login');
            this.$emit('update:visible', false);
          });
        } else {
          this.$message.error(res.data.msg || this.$t('changePassword.changeFailed'));
        }
      }, (err) => {
        this.$message.error(err.msg || this.$t('changePassword.changeFailed'));
      });
      this.$emit('input', false);
    },
    cancel() {
      this.dialogVisible = false;
      this.resetForm();
    },
    resetForm() {
      this.oldPassword = "";
      this.newPassword = "";
      this.confirmNewPassword = "";
    }
  }
}
</script>
