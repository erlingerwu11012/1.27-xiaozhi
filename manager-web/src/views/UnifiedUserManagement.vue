<template>
  <div class="xn-page">
    <page-header :title="$t('xn.visuals.people.title')" :description="$t('xn.visuals.people.desc')">
      <el-button type="primary" @click="openCreate"><xn-icon name="plus" /> {{ $t('xn.visuals.people.add') }}</el-button>
    </page-header>

    <div class="xn-toolbar">
      <el-input v-model.trim="keyword" clearable :placeholder="$t('xn.visuals.people.search')" @input="page = 1">
        <xn-icon slot="prefix" name="search" class="uu-search-icon" />
      </el-input>
      <el-select v-model="filter" class="uu-filter" @change="page = 1">
        <el-option value="all" :label="$t('xn.visuals.people.filterAll')" />
        <el-option value="noFace" :label="$t('xn.visuals.people.filterNoFace')" />
        <el-option value="noVoice" :label="$t('xn.visuals.people.filterNoVoice')" />
      </el-select>
      <span class="xn-toolbar__grow"></span>
      <label v-if="agents.length" class="uu-agent">
        <span class="xn-muted">{{ $t('xn.visuals.people.voiceAgent') }}</span>
        <el-tooltip :content="$t('xn.visuals.people.voiceAgentHint')" placement="top" popper-class="xn-tip-wide">
          <xn-icon name="info" class="uu-agent__hint" />
        </el-tooltip>
        <el-select :value="agentId" filterable @change="selectAgent">
          <el-option v-for="a in agents" :key="a.id" :label="a.agentName" :value="a.id" />
        </el-select>
      </label>
    </div>

    <div class="xn-panel xn-panel--flush uu-panel">
      <xn-empty v-if="loadFailed && !loading" error @retry="reload" />
      <template v-else>
        <el-table :data="pagedRows" v-loading="loading" row-key="userId">
          <el-table-column :label="$t('xn.visuals.people.colMember')" min-width="200">
            <template slot-scope="{ row }">
              <div class="uu-member">
                <span class="uu-avatar" aria-hidden="true">{{ initial(row.displayName) }}</span>
                <span class="uu-member__name xn-clip" :title="row.displayName">{{ row.displayName }}</span>
                <el-tooltip :content="$t('xn.visuals.people.rename')" placement="top">
                  <button type="button" class="uu-icon-btn" :aria-label="$t('xn.visuals.people.rename')" @click="editName(row)">
                    <xn-icon name="edit" />
                  </button>
                </el-tooltip>
              </div>
            </template>
          </el-table-column>

          <el-table-column :label="$t('xn.visuals.people.colFace')" min-width="250">
            <template slot-scope="{ row }">
              <div class="uu-bind">
                <span v-if="row.faceProfileIds.length" class="xn-tag xn-tag--success"><i class="dot"></i>{{ $t('xn.visuals.people.faceBound') }}</span>
                <span v-else class="xn-tag xn-tag--muted">{{ $t('xn.visuals.people.faceNone') }}</span>
                <span v-if="faceCount(row)" class="xn-muted uu-bind__meta xn-num">{{ $t('xn.visuals.people.faceCount', { n: faceCount(row) }) }}</span>
              </div>
              <div class="uu-actions">
                <el-button type="text" @click="openFace(row)">{{ row.faceProfileIds.length ? $t('xn.visuals.people.addFace') : $t('xn.visuals.people.bindFace') }}</el-button>
                <el-button v-if="row.faceProfileIds.length" type="text" class="uu-quiet" @click="unbindFaces(row)">{{ $t('xn.visuals.people.unbind') }}</el-button>
              </div>
            </template>
          </el-table-column>

          <el-table-column :label="$t('xn.visuals.people.colVoice')" min-width="260">
            <template slot-scope="{ row }">
              <div class="uu-bind">
                <span v-if="row.voiceprintIds.length" class="xn-tag xn-tag--success"><i class="dot"></i>{{ $t('xn.visuals.people.voiceBound') }}</span>
                <span v-else class="xn-tag xn-tag--muted">{{ $t('xn.visuals.people.voiceNone') }}</span>
                <span v-if="voiceNote(row)" class="xn-muted uu-bind__meta xn-clip" :title="voiceNote(row)">{{ voiceNote(row) }}</span>
              </div>
              <div class="uu-actions">
                <el-button type="text" @click="openVoice(row, false)">{{ row.voiceprintIds.length ? $t('xn.visuals.people.rerecordVoice') : $t('xn.visuals.people.recordVoice') }}</el-button>
                <el-button v-if="voicesFor(row).length && !row.voiceprintIds.length" type="text" @click="openVoice(row, true)">{{ $t('xn.visuals.people.bindExistingVoice') }}</el-button>
                <el-button v-if="row.voiceprintIds.length" type="text" class="uu-quiet" @click="unbindVoices(row)">{{ $t('xn.visuals.people.unbind') }}</el-button>
              </div>
            </template>
          </el-table-column>

          <el-table-column :label="$t('xn.visuals.people.colActions')" width="96" align="right">
            <template slot-scope="{ row }">
              <el-button type="text" class="uu-danger" @click="deleteMember(row)">{{ $t('xn.visuals.people.delete') }}</el-button>
            </template>
          </el-table-column>

          <template slot="empty">
            <xn-empty v-if="!users.length" icon="people" :title="$t('xn.visuals.people.emptyTitle')" :description="$t('xn.visuals.people.emptyDesc')">
              <el-button type="primary" @click="openCreate"><xn-icon name="plus" /> {{ $t('xn.visuals.people.add') }}</el-button>
            </xn-empty>
            <xn-empty v-else icon="search" :title="$t('xn.visuals.people.noMatch')">
              <el-button @click="clearFilters">{{ $t('xn.visuals.people.clearFilter') }}</el-button>
            </xn-empty>
          </template>
        </el-table>
        <div v-if="filteredRows.length > pageSizes[0]" class="uu-foot">
          <el-pagination background layout="total, sizes, prev, pager, next" :total="filteredRows.length"
            :page-size="pageSize" :page-sizes="pageSizes" :current-page="page"
            @size-change="(s) => { pageSize = s; page = 1 }" @current-change="(p) => { page = p }" />
        </div>
      </template>
    </div>

    <!-- 添加成员 -->
    <el-dialog :title="$t('xn.visuals.people.add')" :visible.sync="createVisible" width="440px" append-to-body
      :close-on-click-modal="false" @closed="resetCreate">
      <el-form ref="createForm" :model="createForm" :rules="createRules" label-position="top" @submit.native.prevent="createMember">
        <el-form-item :label="$t('xn.visuals.people.nickname')" prop="nickname">
          <el-input v-model.trim="createForm.nickname" maxlength="64" show-word-limit
            :placeholder="$t('xn.visuals.people.nicknamePlaceholder')" @keyup.enter.native="createMember" />
        </el-form-item>
      </el-form>
      <span slot="footer">
        <el-button @click="createVisible = false">{{ $t('xn.common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" @click="createMember">{{ $t('xn.visuals.people.createSubmit') }}</el-button>
      </span>
    </el-dialog>

    <VoicePrintDialog :visible.sync="voiceVisible" :agentId="agentId" :form="voiceForm" :memberBound="true"
      :title="voiceForm.id ? $t('xn.visuals.people.rerecordVoice') : $t('xn.visuals.people.recordVoice')"
      @submit="saveVoice" @cancel="voiceVisible = false" />

    <!-- 绑定已有声纹 -->
    <el-dialog :title="$t('xn.visuals.people.existingVoiceTitle')" :visible.sync="existingVoiceVisible" width="440px" append-to-body>
      <p class="uu-help">{{ $t('xn.visuals.people.existingVoiceHelp', { name: activeName }) }}</p>
      <el-select v-model="selectedVoice" :placeholder="$t('xn.visuals.people.selectVoice')" class="uu-full">
        <el-option v-for="voice in voicesFor(activeMember)" :key="voice.id" :label="voice.sourceName || $t('xn.visuals.people.unnamedVoice')" :value="voice.id">
          <span>{{ voice.sourceName || $t('xn.visuals.people.unnamedVoice') }}</span>
          <span class="uu-opt-meta xn-num">{{ (voice.createDate || '').slice(0, 10) }}</span>
        </el-option>
      </el-select>
      <span slot="footer">
        <el-button @click="existingVoiceVisible = false">{{ $t('xn.common.cancel') }}</el-button>
        <el-button type="primary" :loading="saving" :disabled="!selectedVoice" @click="bindExistingVoice">{{ $t('xn.visuals.people.bind') }}</el-button>
      </span>
    </el-dialog>

    <!-- 人脸：上传照片 / 设备采集 / 已有资料 -->
    <el-dialog :title="$t('xn.visuals.people.faceTitle', { name: activeName })" :visible.sync="faceVisible" width="580px"
      append-to-body :close-on-click-modal="false" @closed="onFaceClosed">
      <div class="uu-tabs" role="tablist">
        <button v-for="t in faceTabs" :key="t.key" type="button" role="tab" class="uu-tab" :class="{ 'is-on': faceTab === t.key }"
          :aria-selected="String(faceTab === t.key)" @click="faceTab = t.key">
          <xn-icon :name="t.icon" /> {{ t.label }}<span v-if="t.count" class="uu-tab__count xn-num">{{ t.count }}</span>
        </button>
      </div>

      <section v-if="faceTab === 'upload'" class="uu-pane">
        <p class="uu-help">{{ $t('xn.visuals.people.uploadHelp') }}</p>
        <el-upload action="#" :auto-upload="false" accept="image/jpeg,image/png" multiple :limit="5" :file-list="faceFiles"
          :on-change="faceFileChanged" :on-remove="faceFileChanged" :on-exceed="onFaceExceed" list-type="picture-card" class="uu-upload">
          <div class="uu-upload__trigger"><xn-icon name="upload" /><span>{{ $t('xn.visuals.people.choosePhotos') }}</span></div>
        </el-upload>
      </section>

      <section v-else-if="faceTab === 'draft'" class="uu-pane" v-loading="draftLoading">
        <div class="uu-pane__head">
          <p class="uu-help">{{ $t('xn.visuals.people.draftHelp') }}</p>
          <el-button size="small" @click="loadDrafts"><xn-icon name="refresh" /> {{ $t('xn.visuals.people.refresh') }}</el-button>
        </div>
        <xn-empty v-if="!drafts.length && !draftLoading" icon="people" :title="$t('xn.visuals.people.draftEmpty')" :description="$t('xn.visuals.people.draftEmptyDesc')" />
        <ul v-else class="uu-drafts">
          <li v-for="draft in drafts" :key="draft.session_id" class="uu-draft">
            <span class="uu-draft__thumb">
              <img v-if="draft.previewUrl" :src="draft.previewUrl" alt="" />
              <xn-icon v-else name="people" />
            </span>
            <span class="uu-draft__text">
              <span :class="['xn-tag', draftTagClass(draft.status)]">{{ draftStatusLabel(draft.status) }}</span>
              <span class="xn-muted xn-num">{{ $t('xn.visuals.people.draftCount', { n: draft.accepted_count || 0 }) }}<template v-if="draft.created_at">，{{ formatTime(draft.created_at) }}</template></span>
            </span>
            <span class="uu-draft__ops">
              <el-button size="small" type="primary" plain :disabled="draft.status !== 'draft_ready' || saving" @click="bindDraft(draft)">{{ $t('xn.visuals.people.bindTo', { name: activeName }) }}</el-button>
              <el-button size="small" type="text" class="uu-quiet" :disabled="saving" @click="discardDraft(draft)">{{ $t('xn.visuals.people.discard') }}</el-button>
            </span>
          </li>
        </ul>
      </section>

      <section v-else class="uu-pane">
        <p class="uu-help">{{ $t('xn.visuals.people.existingHelp', { name: activeName }) }}</p>
        <el-select v-if="facesFor(activeMember).length" v-model="selectedFace" :placeholder="$t('xn.visuals.people.selectFace')" class="uu-full">
          <el-option v-for="face in facesFor(activeMember)" :key="face.user_id" :label="face.display_name || $t('xn.visuals.people.unnamedFace')" :value="face.user_id">
            <span>{{ face.display_name || $t('xn.visuals.people.unnamedFace') }}</span>
            <span class="uu-opt-meta">{{ face.status === 'active' ? $t('xn.visuals.people.statusActive') : $t('xn.visuals.people.statusDraft') }}<template v-if="face.face_count">，{{ $t('xn.visuals.people.faceCount', { n: face.face_count }) }}</template></span>
          </el-option>
        </el-select>
        <p v-else class="uu-none">{{ $t('xn.visuals.people.existingEmpty') }}</p>
      </section>

      <span slot="footer">
        <el-button @click="faceVisible = false">{{ faceTab === 'draft' ? $t('xn.common.close') : $t('xn.common.cancel') }}</el-button>
        <el-button v-if="faceTab === 'upload'" type="primary" :loading="saving" :disabled="!faceFiles.length" @click="saveFace">{{ $t('xn.visuals.people.uploadAndBind') }}</el-button>
        <el-button v-else-if="faceTab === 'existing'" type="primary" :loading="saving" :disabled="!selectedFace" @click="bindExistingFace">{{ $t('xn.visuals.people.bind') }}</el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
/**
 * 人员身份：一位成员（user identity）同时拥有人脸资料与声纹，二者都绑定在成员上。
 * 接口与调用顺序与原页面一致：/user-identities/*、/face/*、/agent/voice-print。
 */
import Api from '@/apis/api'
import VoicePrintDialog from '@/components/VoicePrintDialog.vue'

const LOAD_GUARD_MS = 10000

export default {
  name: 'UnifiedUserManagement',
  components: { VoicePrintDialog },
  data() {
    return {
      users: [], faces: [], voices: [], drafts: [], agents: [],
      loading: false, loadFailed: false, saving: false, draftLoading: false,
      keyword: '', filter: 'all', page: 1, pageSize: 10, pageSizes: [10, 20, 50],
      createVisible: false, createForm: { nickname: '' },
      activeMember: null, agentId: '',
      voiceVisible: false, existingVoiceVisible: false, selectedVoice: '', voiceForm: {},
      faceVisible: false, faceTab: 'upload', selectedFace: '', faceFiles: [],
    }
  },
  computed: {
    createRules() {
      return {
        nickname: [
          { required: true, message: this.$t('xn.visuals.people.nicknameRequired'), trigger: 'blur' },
          { max: 64, message: this.$t('xn.visuals.people.nicknameTooLong'), trigger: 'blur' },
        ],
      }
    },
    filteredRows() {
      const kw = this.keyword.toLowerCase()
      return this.users.filter((u) => {
        if (kw && !String(u.displayName || '').toLowerCase().includes(kw)) return false
        if (this.filter === 'noFace') return !u.faceProfileIds.length
        if (this.filter === 'noVoice') return !u.voiceprintIds.length
        return true
      })
    },
    pagedRows() {
      const start = (this.page - 1) * this.pageSize
      return this.filteredRows.slice(start, start + this.pageSize)
    },
    activeName() { return (this.activeMember && this.activeMember.displayName) || '' },
    faceTabs() {
      return [
        { key: 'upload', icon: 'upload', label: this.$t('xn.visuals.people.tabUpload') },
        { key: 'draft', icon: 'device', label: this.$t('xn.visuals.people.tabDraft'), count: this.drafts.filter((d) => d.status === 'draft_ready').length },
        { key: 'existing', icon: 'people', label: this.$t('xn.visuals.people.tabExisting') },
      ]
    },
  },
  mounted() { this.agentId = this.$route.query.agentId || ''; this.reload() },
  beforeDestroy() { this.clearPreviews() },
  methods: {
    call(fn, ...args) { return new Promise((resolve, reject) => fn(...args, (response) => { const res = response && response.data && response.code === undefined ? response.data : response; if (res && res.code === 0) resolve(res.data); else reject(new Error((res && res.msg) || this.$t('xn.visuals.people.failed'))) })) },
    /** 列表读取：业务错误时原 API 模块不会回调，这里加一个超时，超时后显示失败状态而不是一直转圈 */
    load(fn, ...args) {
      return Promise.race([
        this.call(fn, ...args),
        new Promise((resolve, reject) => setTimeout(() => reject(new Error('')), LOAD_GUARD_MS)),
      ])
    },
    async reload() {
      this.loading = true
      this.loadFailed = false
      try {
        const [users, voices, agents] = await Promise.all([this.load(Api.userIdentity.list), this.load(Api.userIdentity.voices), this.load(Api.agent.getAgentList)])
        this.users = (users || []).map(user => ({ ...user, faceProfileIds: user.faceProfileIds || [], voiceprintIds: user.voiceprintIds || [] }))
        this.voices = voices || []
        const availableAgents = Array.isArray(agents) ? agents : ((agents && agents.list) || [])
        this.agents = availableAgents
        // The voice asset belongs to the account; the legacy upload endpoint
        // still needs an owned agent as its storage reference.
        if (!availableAgents.some(agent => agent.id === this.agentId)) this.agentId = availableAgents.length ? availableAgents[0].id : ''
        const faceData = await this.load(Api.face.listProfiles, true)
        this.faces = (faceData && faceData.profiles) || []
        if (this.page > 1 && (this.page - 1) * this.pageSize >= this.filteredRows.length) this.page = 1
      } catch (e) {
        this.loadFailed = true
        if (e.message) this.$message.error(e.message)
      } finally { this.loading = false }
    },
    selectAgent(id) {
      this.agentId = id
      if (this.$route.query.agentId !== id) this.$router.replace({ query: { ...this.$route.query, agentId: id } }).catch(() => {})
    },
    clearFilters() { this.keyword = ''; this.filter = 'all'; this.page = 1 },
    initial(name) { return String(name || '?').trim().slice(0, 1).toUpperCase() },
    faceCount(row) {
      return row.faceProfileIds.reduce((n, id) => { const f = this.faces.find((x) => x.user_id === id); return n + ((f && f.face_count) || 0) }, 0)
    },
    voiceNote(row) {
      const v = this.voices.find((x) => row.voiceprintIds.includes(x.id))
      return (v && v.introduce) || ''
    },
    formatTime(value) {
      const d = new Date(String(value).replace(' ', 'T'))
      return Number.isNaN(d.getTime()) ? value : d.toLocaleString()
    },
    draftStatusLabel(s) {
      if (s === 'draft_ready') return this.$t('xn.visuals.people.draftReady')
      if (s === 'expired') return this.$t('xn.visuals.people.draftExpired')
      return this.$t('xn.visuals.people.draftCollecting')
    },
    draftTagClass(s) {
      if (s === 'draft_ready') return 'xn-tag--success'
      if (s === 'expired') return 'xn-tag--muted'
      return 'xn-tag--warning'
    },

    /* ── 成员 ── */
    openCreate() { this.createVisible = true },
    resetCreate() { this.createForm.nickname = ''; if (this.$refs.createForm) this.$refs.createForm.clearValidate() },
    createMember() {
      if (this.saving) return
      this.$refs.createForm.validate(async (valid) => {
        if (!valid) return
        this.saving = true
        try {
          await this.call(Api.userIdentity.create, { displayName: this.createForm.nickname })
          this.createVisible = false
          this.$message.success(this.$t('xn.visuals.people.created'))
          await this.reload()
        } catch (e) { this.$message.error(e.message) } finally { this.saving = false }
      })
    },
    editName(row) {
      this.$prompt(this.$t('xn.visuals.people.renamePrompt'), this.$t('xn.visuals.people.rename'), {
        inputValue: row.displayName,
        confirmButtonText: this.$t('xn.common.confirm'),
        cancelButtonText: this.$t('xn.common.cancel'),
        inputValidator: (value) => {
          const v = String(value || '').trim()
          if (!v) return this.$t('xn.visuals.people.nicknameRequired')
          if (v.length > 64) return this.$t('xn.visuals.people.nicknameTooLong')
          return true
        },
      }).then(async ({ value }) => {
        try {
          await this.call(Api.userIdentity.updateDisplayName, row.userId, { displayName: value.trim() })
          this.$message.success(this.$t('xn.visuals.people.renamed'))
          await this.reload()
        } catch (e) { this.$message.error(e.message) }
      }).catch(() => {})
    },
    async deleteMember(row) {
      try {
        await this.$confirm(this.$t('xn.visuals.people.deleteConfirm', { name: row.displayName }), this.$t('xn.visuals.people.deleteTitle'), {
          type: 'warning', confirmButtonText: this.$t('xn.visuals.people.delete'), cancelButtonText: this.$t('xn.common.cancel'),
        })
        await this.call(Api.userIdentity.remove, row.userId)
        this.$message.success(this.$t('xn.visuals.people.deleted'))
        await this.reload()
      } catch (e) { if (e instanceof Error) this.$message.error(e.message) }
    },

    /* ── 声纹 ── */
    voicesFor() { const bound = new Set(this.users.flatMap(user => user.voiceprintIds)); return this.voices.filter(voice => !bound.has(voice.id)) },
    facesFor() { const bound = new Set(this.users.flatMap(user => user.faceProfileIds)); return this.faces.filter(face => !bound.has(face.user_id)) },
    openVoice(row, existing) {
      this.activeMember = row
      if (existing) { this.selectedVoice = ''; this.existingVoiceVisible = true; return }
      if (!this.agentId) return this.$message.warning(this.$t('xn.visuals.people.needAgent'))
      const original = this.voices.find(voice => row.voiceprintIds.includes(voice.id))
      this.voiceForm = { ...(original || {}), id: original ? original.id : null, audioId: '', sourceName: row.displayName, introduce: original ? original.introduce : '', userId: row.userId }
      this.voiceVisible = true
    },
    async saveVoice({ form, done }) {
      try {
        const payload = { ...form, agentId: this.agentId, userId: this.activeMember.userId, sourceName: this.activeMember.displayName }
        await this.call(form.id ? Api.agent.updateAgentVoicePrint : Api.agent.addAgentVoicePrint, payload)
        this.voiceVisible = false; await this.reload(); this.$message.success(this.$t('xn.visuals.people.voiceSaved'))
      } catch (e) { this.$message.error(e.message) } finally { if (done) done() }
    },
    async bindExistingVoice() {
      if (!this.selectedVoice || this.saving) return
      this.saving = true
      try {
        await this.call(Api.userIdentity.bindVoiceprint, this.activeMember.userId, this.selectedVoice)
        this.existingVoiceVisible = false
        this.$message.success(this.$t('xn.visuals.people.voiceBoundOk'))
        await this.reload()
      } catch (e) { this.$message.error(e.message) } finally { this.saving = false }
    },
    async unbindVoices(row) {
      try {
        await this.$confirm(this.$t('xn.visuals.people.unbindVoiceConfirm', { name: row.displayName }), this.$t('xn.visuals.people.unbindVoiceTitle'), {
          type: 'warning', confirmButtonText: this.$t('xn.visuals.people.unbind'), cancelButtonText: this.$t('xn.common.cancel'),
        })
        for (const id of row.voiceprintIds) await this.call(Api.userIdentity.unbindVoiceprint, row.userId, id)
        this.$message.success(this.$t('xn.visuals.people.unbound'))
        await this.reload()
      } catch (e) { if (e instanceof Error) this.$message.error(e.message) }
    },

    /* ── 人脸 ── */
    async unbindFaces(row) {
      try {
        await this.$confirm(this.$t('xn.visuals.people.unbindFaceConfirm', { name: row.displayName }), this.$t('xn.visuals.people.unbindFaceTitle'), {
          type: 'warning', confirmButtonText: this.$t('xn.visuals.people.unbind'), cancelButtonText: this.$t('xn.common.cancel'),
        })
        for (const id of row.faceProfileIds) await this.call(Api.userIdentity.unbindFace, row.userId, id)
        this.$message.success(this.$t('xn.visuals.people.unbound'))
        await this.reload()
      } catch (e) { if (e instanceof Error) this.$message.error(e.message) }
    },
    clearPreviews() { this.drafts.forEach(draft => { if (draft.previewUrl) URL.revokeObjectURL(draft.previewUrl) }); this.drafts = [] },
    openFace(row) {
      this.activeMember = row; this.selectedFace = ''; this.faceFiles = []; this.faceTab = 'upload'; this.faceVisible = true
      this.loadDrafts()
    },
    onFaceClosed() { this.faceFiles = []; this.selectedFace = ''; this.clearPreviews() },
    async loadDrafts() {
      this.clearPreviews()
      this.draftLoading = true
      try {
        const data = await this.call(Api.face.listEnrollmentSessions); this.drafts = ((data && data.sessions) || []).map(draft => ({ ...draft, previewUrl: '' }))
        this.drafts.forEach(draft => { if (draft.has_preview) Api.face.fetchEnrollmentPreview(draft.session_id, res => { if (res.code === 0) { if (this.drafts.includes(draft)) this.$set(draft, 'previewUrl', res.url); else URL.revokeObjectURL(res.url) } }) })
      } catch (e) { this.$message.error(e.message) } finally { this.draftLoading = false }
    },
    faceFileChanged(file, list) {
      const valid = list.filter(item => item.raw && ['image/jpeg', 'image/png'].includes(item.raw.type) && item.raw.size <= 10 * 1024 * 1024)
      if (valid.length < list.length) this.$message.warning(this.$t('xn.visuals.people.photoRejected', { n: list.length - valid.length }))
      this.faceFiles = valid
    },
    onFaceExceed() { this.$message.warning(this.$t('xn.visuals.people.uploadHelp')) },
    async saveFace() {
      if (this.saving || !this.faceFiles.length) return; this.saving = true
      try {
        const existing = this.facesFor().find(face => face.display_name === this.activeMember.displayName && face.status === 'draft')
        const profile = existing || await this.call(Api.face.createProfile, this.activeMember.displayName)
        for (const file of this.faceFiles) await this.call(Api.face.uploadFace, profile.user_id, file.raw)
        await this.call(Api.face.activateProfile, profile.user_id)
        await this.call(Api.userIdentity.bindFace, this.activeMember.userId, profile.user_id)
        this.faceVisible = false; await this.reload(); this.$message.success(this.$t('xn.visuals.people.faceBoundOk'))
      } catch (e) { this.$message.error(e.message); await this.reload() } finally { this.saving = false }
    },
    async bindDraft(draft) {
      if (this.saving) return; this.saving = true
      try {
        const profile = await this.call(Api.face.confirmEnrollment, draft.session_id, this.activeMember.displayName)
        await this.call(Api.userIdentity.bindFace, this.activeMember.userId, profile.user_id)
        this.faceVisible = false; this.$message.success(this.$t('xn.visuals.people.faceBoundOk')); await this.reload()
      } catch (e) { this.$message.error(e.message) } finally { this.saving = false }
    },
    discardDraft(draft) {
      this.$confirm(this.$t('faceManagement.discardConfirm'), this.$t('faceManagement.discardDraft'), {
        type: 'warning', confirmButtonText: this.$t('xn.visuals.people.discard'), cancelButtonText: this.$t('xn.common.cancel'),
      }).then(async () => {
        try {
          await this.call(Api.face.discardEnrollment, draft.session_id)
          this.$message.success(this.$t('faceManagement.discardSuccess'))
          this.loadDrafts()
        } catch (e) { this.$message.error(e.message) }
      }).catch(() => {})
    },
    async bindExistingFace() {
      if (this.saving || !this.selectedFace) return; this.saving = true
      try {
        await this.call(Api.userIdentity.bindFace, this.activeMember.userId, this.selectedFace)
        this.faceVisible = false; this.$message.success(this.$t('xn.visuals.people.faceBoundOk')); await this.reload()
      } catch (e) { this.$message.error(e.message) } finally { this.saving = false }
    },
  },
}
</script>

<style scoped>
.uu-search-icon { height: 100%; margin: 0 2px 0 4px; font-size: 16px; color: var(--xn-ink-3); }
.uu-filter { width: 160px; }
.uu-agent { display: inline-flex; align-items: center; gap: 6px; }
.uu-agent .el-select { width: 200px; margin-left: 2px; }
.uu-agent__hint { color: var(--xn-ink-4); cursor: help; }
.uu-panel { overflow: hidden; }
.uu-panel ::v-deep .el-table__empty-text { width: 100%; line-height: 1.6; }

.uu-member { display: flex; align-items: center; gap: 10px; min-width: 0; }
.uu-avatar {
  flex: none; display: inline-flex; align-items: center; justify-content: center; width: 32px; height: 32px;
  border-radius: 50%; background: var(--xn-lake-soft); color: var(--xn-lake-ink); font-size: 14px; font-weight: 600;
}
.uu-member__name { min-width: 0; font-weight: 600; color: var(--xn-ink); }
.uu-icon-btn {
  flex: none; display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; padding: 0;
  border: 0; border-radius: var(--xn-r-sm); background: none; color: var(--xn-ink-4); cursor: pointer;
}
.uu-icon-btn:hover { background: var(--xn-mist-2); color: var(--xn-lake); }

.uu-bind { display: flex; align-items: center; gap: 8px; min-width: 0; }
.uu-bind__meta { min-width: 0; font-size: 13px; }
.uu-actions { margin-top: 2px; margin-left: -4px; }
.uu-actions .el-button { padding-top: 6px; padding-bottom: 4px; }
.uu-quiet { color: var(--xn-ink-3); }
.uu-quiet:hover, .uu-quiet:focus { color: var(--xn-ink); }
.uu-danger { color: var(--xn-danger); }
.uu-danger:hover, .uu-danger:focus { color: #8D3523; }
.uu-foot { display: flex; justify-content: flex-end; padding: 4px 16px 14px; border-top: 1px solid var(--xn-line-2); }

.uu-help { margin: 0 0 14px; font-size: 13px; line-height: 1.7; color: var(--xn-ink-3); }
.uu-full { width: 100%; }
.uu-opt-meta { float: right; margin-left: 16px; font-size: 12px; color: var(--xn-ink-3); }
.uu-none { margin: 0; padding: 16px; border-radius: var(--xn-r); background: var(--xn-mist-2); color: var(--xn-ink-3); font-size: 14px; }

.uu-tabs { display: flex; gap: 4px; padding: 4px; margin-bottom: 18px; border-radius: 10px; background: var(--xn-mist); }
.uu-tab {
  flex: 1; display: inline-flex; align-items: center; justify-content: center; gap: 6px; height: 36px; padding: 0 8px;
  border: 0; border-radius: 8px; background: none; color: var(--xn-ink-2); font: inherit; font-size: 14px; cursor: pointer; white-space: nowrap;
}
.uu-tab:hover { color: var(--xn-ink); }
.uu-tab.is-on { background: #fff; color: var(--xn-ink); font-weight: 600; box-shadow: 0 1px 2px rgba(30, 43, 64, 0.08); }
.uu-tab__count { min-width: 18px; height: 18px; padding: 0 5px; border-radius: 9px; background: var(--xn-lake); color: #fff; font-size: 12px; line-height: 18px; }
.uu-pane { min-height: 200px; }
.uu-pane__head { display: flex; align-items: flex-start; gap: 12px; }
.uu-pane__head .uu-help { flex: 1; }

.uu-upload ::v-deep .el-upload--picture-card,
.uu-upload ::v-deep .el-upload-list--picture-card .el-upload-list__item { width: 96px; height: 96px; line-height: 1.4; border-radius: var(--xn-r); }
.uu-upload ::v-deep .el-upload--picture-card { border-color: var(--xn-line); background: var(--xn-mist-2); }
.uu-upload ::v-deep .el-upload--picture-card:hover { border-color: var(--xn-lake); }
.uu-upload__trigger { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; height: 100%; color: var(--xn-ink-2); font-size: 13px; }
.uu-upload__trigger .xn-icon { font-size: 20px; }

.uu-drafts { margin: 0; padding: 0; list-style: none; border: 1px solid var(--xn-line); border-radius: var(--xn-r-lg); }
.uu-draft { display: flex; align-items: center; gap: 12px; padding: 10px 12px; }
.uu-draft + .uu-draft { border-top: 1px solid var(--xn-line-2); }
.uu-draft__thumb {
  flex: none; display: inline-flex; align-items: center; justify-content: center; width: 56px; height: 56px; overflow: hidden;
  border-radius: var(--xn-r); background: var(--xn-mist-2); color: var(--xn-ink-4); font-size: 22px;
}
.uu-draft__thumb img { width: 100%; height: 100%; object-fit: cover; }
.uu-draft__text { flex: 1; min-width: 0; display: flex; flex-direction: column; align-items: flex-start; gap: 4px; font-size: 13px; }
.uu-draft__ops { flex: none; display: flex; align-items: center; }

@media (max-width: 760px) {
  .uu-agent, .uu-agent .el-select, .uu-filter { width: 100%; }
  .uu-draft { flex-wrap: wrap; }
  .uu-tab { font-size: 13px; }
}
</style>
