"""Prepare a narrow login-page patch from the SSH-fetched production source."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "build/login_account_guard_20261002"
before = (WORK / "login.before.vue").read_text(encoding="utf-8")
source = before

def replace(old, new, count=1):
    global source
    if source.count(old) != count:
        raise RuntimeError("Unexpected source guard: " + old[:80])
    source = source.replace(old, new)

replace('<form class="form-body" @submit.prevent="handleSubmit" @keyup.enter="handleSubmit">',
        '<form v-if="showLogin" key="login-form" class="form-body" autocomplete="off" @submit.prevent="handleSubmit" @keyup.enter="handleSubmit">')
replace('<el-input v-model="form.username" :placeholder="$t(\'login.usernamePlaceholder\')" name="username" autocomplete="username" id="username" />',
        '''<el-input ref="loginUsername" :value="form.username" :placeholder="$t('login.usernamePlaceholder')" name="username" autocomplete="off" id="username"
                  :readonly="!credentialEditing.username" @focus="beginCredentialEdit('username')" @blur="endCredentialEdit('username')"
                  @input="updateLoginCredential('username', $event)" @change="updateLoginCredential('username', $event)" />''')
replace('<el-input v-model="form.password" :placeholder="$t(\'login.passwordPlaceholder\')" type="password" name="password" autocomplete="current-password" id="password" show-password />',
        '''<el-input ref="loginPassword" :value="form.password" :placeholder="$t('login.passwordPlaceholder')" type="password" name="password" autocomplete="off" id="password" show-password
                :readonly="!credentialEditing.password" @focus="beginCredentialEdit('password')" @blur="endCredentialEdit('password')"
                @input="updateLoginCredential('password', $event)" @change="updateLoginCredential('password', $event)" />''')
# Login/register branches must not reuse the same input component instances.
replace('<form class="form-body" @submit.prevent="handleSubmit">',
        '<form v-if="showLogin" key="register-form" class="form-body" @submit.prevent="handleSubmit">')
replace('      fetchCaptchaTimer: null,', '''      fetchCaptchaTimer: null,
      credentialEditing: { username: false, password: false },
      credentialGuardTimer: null,
      // Values live only in this component. Never persist credentials in storage.
      credentialGuardReady: false,''')
replace('      this.isMobileLogin = this.enableMobileRegister;',
        '''      // A delayed response must not replace fields the user is already using.
      if (!this.showLogin) this.isMobileLogin = this.enableMobileRegister;''')
replace('  beforeDestroy() {', '''  updated() {
    this.restoreInactiveCredentials();
  },
  beforeDestroy() {
    this.stopCredentialGuard();''')
replace('''      this.isRegisterMode = false;
    },
    openRegister()''', '''      this.isRegisterMode = false;
      this.startCredentialGuard();
    },
    openRegister()''')
replace('''    openRegister() {
      this.showLogin''', '''    openRegister() {
      this.stopCredentialGuard();
      this.showLogin''')
replace('''    closeLogin() {
      this.showLogin = false;''', '''    closeLogin() {
      this.stopCredentialGuard();
      this.showLogin = false;''')
replace('''    switchToRegister() {
      this.isRegisterMode''', '''    switchToRegister() {
      this.stopCredentialGuard();
      this.isRegisterMode''')
replace('''    switchToLogin() {
      this.isRegisterMode = false;
      this.form.confirmPassword = "";
    },''', '''    switchToLogin() {
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
    },''')
replace('''    async login() {
      if''', '''    async login() {
      this.restoreInactiveCredentials();
      if''')
(WORK / "login.after.vue").write_text(source, encoding="utf-8", newline="\n")
manifest = dict(before_sha256=hashlib.sha256((WORK/"login.before.vue").read_bytes()).hexdigest(),
                after_sha256=hashlib.sha256((WORK/"login.after.vue").read_bytes()).hexdigest(),
                path="main/manager-web/src/views/login.vue")
(WORK/"source-manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
print(json.dumps(manifest,indent=2))
