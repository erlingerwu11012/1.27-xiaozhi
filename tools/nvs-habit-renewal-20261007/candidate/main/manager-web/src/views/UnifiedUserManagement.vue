<template>
  <div class="page">
    <HeaderBar />
    <section class="toolbar">
      <h2>用户管理</h2>
      <el-button type="primary" @click="createVisible = true">添加成员</el-button>
    </section>
    <main class="panel glass-panel" v-loading="loading">
      <el-empty v-if="!users.length && !loading" description="暂无成员" />
      <div class="members">
        <article v-for="row in users" :key="row.userId" class="member-card">
          <div class="member-header">
            <span class="avatar"><i class="el-icon-user" /></span>
            <h3>{{ row.displayName }}</h3>
            <el-button type="text" @click="editName(row)">改名</el-button>
          </div>
          <div class="binding-row"><span>人脸</span><el-tag size="small" :type="row.faceProfileIds.length ? 'success' : 'info'">{{ row.faceProfileIds.length ? '已绑定' : '未绑定' }}</el-tag></div>
          <div class="binding-actions">
            <el-button size="small" @click="openFace(row)">采集 / 绑定</el-button>
            <el-button v-if="row.faceProfileIds.length" size="small" type="text" @click="unbindFaces(row)">解绑</el-button>
          </div>
          <div class="binding-row"><span>声纹</span><el-tag size="small" :type="row.voiceprintIds.length ? 'success' : 'info'">{{ row.voiceprintIds.length ? '已绑定' : '未绑定' }}</el-tag></div>
          <div class="binding-actions">
            <el-button size="small" @click="openVoice(row,false)">{{ row.voiceprintIds.length ? '重录声纹' : '录入声纹' }}</el-button>
            <el-button v-if="voicesFor(row).length && !row.voiceprintIds.length" size="small" type="text" @click="openVoice(row,true)">绑定已有声纹</el-button>
            <el-button v-if="row.voiceprintIds.length" size="small" type="text" @click="unbindVoices(row)">解绑</el-button>
          </div>
          <el-button class="remove-member" type="text" @click="deleteMember(row)">删除成员</el-button>
        </article>
      </div>
    </main>
    <el-dialog title="添加成员" :visible.sync="createVisible" width="400px" :close-on-click-modal="false">
      <el-form @submit.native.prevent="createMember"><el-form-item label="昵称" required><el-input v-model.trim="nickname" maxlength="64" placeholder="例如：爸爸" @keyup.enter.native="createMember" /></el-form-item></el-form>
      <span slot="footer"><el-button @click="createVisible=false">取消</el-button><el-button type="primary" :loading="saving" @click="createMember">添加</el-button></span>
    </el-dialog>
    <VoicePrintDialog :visible.sync="voiceVisible" :agentId="agentId" :form="voiceForm" :memberBound="true" :title="voiceForm.id ? '重录声纹' : '录入声纹'" @submit="saveVoice" @cancel="voiceVisible=false" />
    <el-dialog title="绑定已有声纹" :visible.sync="existingVoiceVisible" width="440px">
      <el-select v-model="selectedVoice" placeholder="选择声纹" style="width:100%"><el-option v-for="voice in voicesFor(activeMember)" :key="voice.id" :label="voice.sourceName || '未命名声纹'" :value="voice.id" /></el-select>
      <span slot="footer"><el-button @click="existingVoiceVisible=false">取消</el-button><el-button type="primary" :loading="saving" @click="bindExistingVoice">绑定</el-button></span>
    </el-dialog>
    <el-dialog :title="activeMember ? activeMember.displayName + '的人脸' : '绑定人脸'" :visible.sync="faceVisible" width="520px" :close-on-click-modal="false">
      <el-tabs v-model="faceTab">
        <el-tab-pane label="上传照片" name="upload">
          <el-upload action="#" :auto-upload="false" accept="image/jpeg,image/png" :limit="5" :file-list="faceFiles" :on-change="faceFileChanged" :on-remove="faceFileChanged" list-type="picture"><el-button size="small">选择照片</el-button></el-upload>
          <el-button type="primary" :loading="saving" :disabled="!faceFiles.length" @click="saveFace">上传并绑定</el-button>
        </el-tab-pane>
        <el-tab-pane label="设备已采集" name="draft">
          <el-empty v-if="!drafts.length" description="暂无已采集的人脸" />
          <div v-for="draft in drafts" :key="draft.session_id" class="draft-row">
            <el-image v-if="draft.previewUrl" :src="draft.previewUrl" fit="cover" class="face-preview" />
            <span>{{ draft.status === 'draft_ready' ? '采集完成' : '采集中' }}</span>
            <el-button type="text" :disabled="draft.status !== 'draft_ready' || saving" @click="bindDraft(draft)">绑定给{{ activeMember && activeMember.displayName }}</el-button>
          </div>
        </el-tab-pane>
        <el-tab-pane label="绑定已有资料" name="existing">
          <el-select v-model="selectedFace" placeholder="选择人脸资料" style="width:100%"><el-option v-for="face in facesFor(activeMember)" :key="face.user_id" :label="face.display_name || '未命名人脸'" :value="face.user_id" /></el-select>
          <el-button type="primary" :loading="saving" :disabled="!selectedFace" @click="bindExistingFace">绑定</el-button>
        </el-tab-pane>
      </el-tabs>
    </el-dialog>
    <VersionFooter />
  </div>
</template>

<script>
import Api from '@/apis/api'
import HeaderBar from '@/components/HeaderBar.vue'
import VersionFooter from '@/components/VersionFooter.vue'
import VoicePrintDialog from '@/components/VoicePrintDialog.vue'
export default {
  name: 'UnifiedUserManagement',
  components: { HeaderBar, VersionFooter, VoicePrintDialog },
  data() { return { users: [], faces: [], voices: [], drafts: [], loading: false, saving: false, createVisible: false, nickname: '', activeMember: null, agentId: '', voiceVisible: false, existingVoiceVisible: false, selectedVoice: '', voiceForm: {}, faceVisible: false, faceTab: 'upload', selectedFace: '', faceFiles: [] } },
  mounted() { this.agentId = this.$route.query.agentId || ''; this.reload() },
  beforeDestroy() { this.clearPreviews() },
  methods: {
    call(fn, ...args) { return new Promise((resolve, reject) => fn(...args, (response) => { const res = response && response.data && response.code === undefined ? response.data : response; if (res && res.code === 0) resolve(res.data); else reject(new Error((res && res.msg) || '操作失败，请稍后重试')) })) },
    async reload() {
      this.loading = true
      try {
        const [users, voices, agents] = await Promise.all([this.call(Api.userIdentity.list), this.call(Api.userIdentity.voices), this.call(Api.agent.getAgentList)])
        this.users = (users || []).map(user => ({ ...user, faceProfileIds: user.faceProfileIds || [], voiceprintIds: user.voiceprintIds || [] }))
        this.voices = voices || []
        const availableAgents = Array.isArray(agents) ? agents : ((agents && agents.list) || [])
        // The voice asset belongs to the account; the legacy upload endpoint
        // still needs an owned agent as its storage reference.
        if (!availableAgents.some(agent => agent.id === this.agentId)) this.agentId = availableAgents.length ? availableAgents[0].id : ''
        const faceData = await this.call(Api.face.listProfiles, true)
        this.faces = faceData.profiles || []
      } catch (e) { this.$message.error(e.message) } finally { this.loading = false }
    },
    async createMember() {
      if (this.saving) return
      if (!this.nickname) return this.$message.warning('请填写昵称')
      this.saving = true
      try { await this.call(Api.userIdentity.create, { displayName: this.nickname }); this.createVisible = false; this.nickname = ''; await this.reload() } catch (e) { this.$message.error(e.message) } finally { this.saving = false }
    },
    editName(row) {
      this.$prompt('填写成员昵称', '修改昵称', { inputValue: row.displayName, inputValidator: value => !!value.trim() || '请填写昵称' }).then(async ({ value }) => {
        try { await this.call(Api.userIdentity.updateDisplayName, row.userId, { displayName: value.trim() }); await this.reload() } catch (e) { this.$message.error(e.message) }
      }).catch(() => {})
    },
    async deleteMember(row) {
      try { await this.$confirm('删除该成员的人脸、声纹及相关记录？', '删除成员', { type: 'warning' }); await this.call(Api.userIdentity.remove, row.userId); await this.reload() } catch (e) { if (e instanceof Error) this.$message.error(e.message) }
    },
    voicesFor() { const bound = new Set(this.users.flatMap(user => user.voiceprintIds)); return this.voices.filter(voice => !bound.has(voice.id)) },
    facesFor() { const bound = new Set(this.users.flatMap(user => user.faceProfileIds)); return this.faces.filter(face => !bound.has(face.user_id)) },
    openVoice(row, existing) {
      this.activeMember = row
      if (existing) { this.selectedVoice = ''; this.existingVoiceVisible = true; return }
      if (!this.agentId) return this.$message.warning('请先添加智能体，再录入声纹')
      const original = this.voices.find(voice => row.voiceprintIds.includes(voice.id))
      this.voiceForm = { ...(original || {}), id: original ? original.id : null, audioId: '', sourceName: row.displayName, introduce: original ? original.introduce : '', userId: row.userId }
      this.voiceVisible = true
    },
    async saveVoice({ form, done }) {
      try {
        const payload = { ...form, agentId: this.agentId, userId: this.activeMember.userId, sourceName: this.activeMember.displayName }
        await this.call(form.id ? Api.agent.updateAgentVoicePrint : Api.agent.addAgentVoicePrint, payload)
        this.voiceVisible = false; await this.reload(); this.$message.success('声纹已保存')
      } catch (e) { this.$message.error(e.message) } finally { if (done) done() }
    },
    async bindExistingVoice() { if (!this.selectedVoice || this.saving) return; this.saving = true; try { await this.call(Api.userIdentity.bindVoiceprint, this.activeMember.userId, this.selectedVoice); this.existingVoiceVisible = false; await this.reload() } catch (e) { this.$message.error(e.message) } finally { this.saving = false } },
    async unbindVoices(row) { try { await this.$confirm('解绑该成员的声纹？', '解绑声纹'); for (const id of row.voiceprintIds) await this.call(Api.userIdentity.unbindVoiceprint, row.userId, id); await this.reload() } catch (e) { if (e instanceof Error) this.$message.error(e.message) } },
    async unbindFaces(row) { try { await this.$confirm('解绑该成员的人脸？', '解绑人脸'); for (const id of row.faceProfileIds) await this.call(Api.userIdentity.unbindFace, row.userId, id); await this.reload() } catch (e) { if (e instanceof Error) this.$message.error(e.message) } },
    clearPreviews() { this.drafts.forEach(draft => { if (draft.previewUrl) URL.revokeObjectURL(draft.previewUrl) }); this.drafts = [] },
    async openFace(row) {
      this.activeMember = row; this.selectedFace = ''; this.faceFiles = []; this.faceTab = 'upload'; this.faceVisible = true; this.clearPreviews()
      try {
        const data = await this.call(Api.face.listEnrollmentSessions); this.drafts = (data.sessions || []).map(draft => ({ ...draft, previewUrl: '' }))
        this.drafts.forEach(draft => { if (draft.has_preview) Api.face.fetchEnrollmentPreview(draft.session_id, res => { if (res.code === 0) { if (this.drafts.includes(draft)) this.$set(draft, 'previewUrl', res.url); else URL.revokeObjectURL(res.url) } }) })
      } catch (e) { this.$message.error(e.message) }
    },
    faceFileChanged(file, list) { this.faceFiles = list.filter(item => item.raw && ['image/jpeg', 'image/png'].includes(item.raw.type) && item.raw.size <= 10 * 1024 * 1024) },
    async saveFace() {
      if (this.saving || !this.faceFiles.length) return; this.saving = true
      try {
        const existing = this.facesFor().find(face => face.display_name === this.activeMember.displayName && face.status === 'draft')
        const profile = existing || await this.call(Api.face.createProfile, this.activeMember.displayName)
        for (const file of this.faceFiles) await this.call(Api.face.uploadFace, profile.user_id, file.raw)
        await this.call(Api.face.activateProfile, profile.user_id)
        await this.call(Api.userIdentity.bindFace, this.activeMember.userId, profile.user_id)
        this.faceVisible = false; await this.reload(); this.$message.success('人脸已绑定')
      } catch (e) { this.$message.error(e.message); await this.reload() } finally { this.saving = false }
    },
    async bindDraft(draft) { if (this.saving) return; this.saving = true; try { const profile = await this.call(Api.face.confirmEnrollment, draft.session_id, this.activeMember.displayName); await this.call(Api.userIdentity.bindFace, this.activeMember.userId, profile.user_id); this.faceVisible = false; await this.reload() } catch (e) { this.$message.error(e.message) } finally { this.saving = false } },
    async bindExistingFace() { if (this.saving || !this.selectedFace) return; this.saving = true; try { await this.call(Api.userIdentity.bindFace, this.activeMember.userId, this.selectedFace); this.faceVisible = false; await this.reload() } catch (e) { this.$message.error(e.message) } finally { this.saving = false } },
  },
}
</script>

<style lang="scss" scoped>
.page { min-height: 100vh; background: #f4f7fb; }
.toolbar { display: flex; justify-content: space-between; align-items: center; max-width: 1200px; margin: auto; padding: 24px 32px; h2 { margin: 0; font-size: 24px; color: #334155; } }
.panel { margin: 0 auto 32px; max-width: 1136px; padding: 24px; background: #fff; border-radius: 16px; }
.members { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 20px; }
.member-card { border: 1px solid #e8edf5; padding: 20px; border-radius: 16px; background: #fff; }
.member-header { display: flex; align-items: center; gap: 12px; h3 { flex: 1; margin: 0; color: #334155; overflow-wrap: anywhere; } }
.avatar { display: flex; justify-content: center; align-items: center; width: 40px; height: 40px; border-radius: 50%; color: #5b7cfa; background: #eef3ff; font-size: 22px; }
.binding-row { display: flex; justify-content: space-between; margin-top: 22px; color: #475569; }
.binding-actions { display: flex; gap: 12px; margin-top: 12px; }
.remove-member { margin-top: 18px; color: #909399; }
.draft-row { display: flex; gap: 12px; align-items: center; margin: 12px 0; }
.face-preview { width: 56px; height: 56px; border-radius: 8px; }
.el-tab-pane > .el-button { margin-top: 20px; }
.page ::v-deep .copyright { position: static; transform: none; width: 100%; }
@media (max-width: 600px) {
  .toolbar { padding: 20px 16px; }
  .panel { margin: 0 12px 24px; padding: 12px; }
  .members { grid-template-columns: 1fr; }
  .page ::v-deep .el-dialog { width: calc(100% - 24px) !important; }
  .page ::v-deep .header { min-width: 0; height: auto !important; padding: 0 8px; }
  .page ::v-deep .header-container { flex-wrap: wrap; height: auto; margin: 0; padding: 12px; }
  .page ::v-deep .header-left { min-width: 0; }
  .page ::v-deep .header-right { min-width: 0; flex: 1; }
  .page ::v-deep .header-center { position: static; transform: none; order: 3; width: 100%; overflow-x: auto; gap: 8px; padding-top: 10px; }
}
</style>
