<template>
  <div class="xn-page">
    <page-header :title="$t('rolePack.pageTitle')" :description="$t('rolePack.pageDesc')">
      <el-button v-if="isSuperAdmin" type="primary" @click="publishVisible = true">
        <xn-icon name="upload" /> {{ $t('rolePack.publish') }}
      </el-button>
    </page-header>

    <p class="vp-note"><xn-icon name="info" /> {{ $t('rolePack.isolationHint') }}
      <router-link to="/home">{{ $t('xn.nav.agents') }}</router-link></p>

    <div class="xn-toolbar">
      <el-input v-model.trim="keyword" clearable :placeholder="$t('xn.visuals.pack.search')">
        <xn-icon slot="prefix" name="search" class="vp-search-icon" />
      </el-input>
      <span class="xn-toolbar__grow"></span>
      <span v-if="catalog.length" class="xn-muted xn-num">{{ $t('xn.visuals.pack.count', { n: filtered.length }) }}</span>
    </div>

    <div v-if="loading && !catalog.length" class="xn-grid vp-grid" aria-hidden="true">
      <div v-for="i in 3" :key="'sk' + i" class="vp-card vp-card--skel"><div class="vp-cover"></div><div class="vp-body"><span class="vp-skel-line"></span><span class="vp-skel-line w60"></span></div></div>
    </div>
    <div v-else-if="loadFailed" class="xn-panel"><xn-empty error @retry="loadCatalog" /></div>
    <div v-else-if="!catalog.length" class="xn-panel">
      <xn-empty icon="role" :title="$t('rolePack.empty')">
        <el-button v-if="isSuperAdmin" type="primary" @click="publishVisible = true"><xn-icon name="upload" /> {{ $t('rolePack.publish') }}</el-button>
      </xn-empty>
    </div>
    <div v-else-if="!filtered.length" class="xn-panel">
      <xn-empty icon="search" :title="$t('xn.visuals.pack.noMatch')">
        <el-button @click="keyword = ''">{{ $t('xn.visuals.people.clearFilter') }}</el-button>
      </xn-empty>
    </div>

    <div v-else class="xn-grid vp-grid" v-loading="loading">
      <article v-for="item in filtered" :key="item.packId" class="vp-card">
        <button type="button" class="vp-cover" :aria-label="$t('xn.visuals.pack.detail') + ' ' + item.displayName" @click="openDetail(item)">
          <img v-if="coverSrc(item)" :src="coverSrc(item)" alt="" />
          <span v-else class="vp-cover__name">{{ item.displayName }}</span>
        </button>
        <div class="vp-body">
          <div class="vp-title-row">
            <h3 class="vp-title xn-clip" :title="item.displayName">{{ item.displayName }}</h3>
            <span v-if="item.version" class="xn-tag xn-tag--muted xn-num">v{{ item.version }}</span>
          </div>
          <p class="vp-desc">{{ item.description || $t('rolePack.noDesc') }}</p>
          <div class="vp-actions">
            <el-button size="small" @click="openDeploy(item)"><xn-icon name="download" /> {{ $t('rolePack.downloadToDevice') }}</el-button>
            <el-button v-if="videoSrc(item)" size="small" type="text" @click="openDemo(item)">{{ $t('rolePack.watchDemo') }}</el-button>
            <span class="xn-toolbar__grow"></span>
            <el-button size="small" type="text" @click="openDetail(item)">{{ $t('xn.visuals.pack.detail') }}</el-button>
          </div>
        </div>
      </article>
    </div>

    <!-- 详情 -->
    <el-dialog :title="detail ? detail.displayName : ''" :visible.sync="detailVisible" width="600px" append-to-body>
      <div v-if="detail" v-loading="detailLoading" class="vp-detail">
        <div class="vp-detail__cover">
          <img v-if="coverSrc(detail)" :src="coverSrc(detail)" alt="" />
          <span v-else class="vp-cover__name">{{ detail.displayName }}</span>
        </div>
        <p v-if="detailFailed" class="vp-warn">{{ $t('xn.visuals.pack.detailFailed') }}</p>
        <p class="vp-detail__desc">{{ detail.description || $t('rolePack.noDesc') }}</p>
        <dl class="vp-dl">
          <template v-for="f in detailFields">
            <dt :key="f.k + '-t'">{{ f.label }}</dt>
            <dd :key="f.k + '-d'" :class="{ 'xn-num': f.num }">{{ f.value }}</dd>
          </template>
        </dl>
      </div>
      <span slot="footer" class="vp-foot">
        <el-button v-if="isSuperAdmin && detail" type="danger" plain :loading="disabling" @click="confirmDisable(detail)">{{ $t('xn.visuals.pack.disable') }}</el-button>
        <span class="xn-toolbar__grow"></span>
        <el-button v-if="detail && videoSrc(detail)" @click="openDemo(detail)">{{ $t('rolePack.watchDemo') }}</el-button>
        <el-button type="primary" @click="detailToDeploy"><xn-icon name="download" /> {{ $t('rolePack.downloadToDevice') }}</el-button>
      </span>
    </el-dialog>

    <!-- 下载到设备 -->
    <el-dialog :title="$t('rolePack.deployTitle')" :visible.sync="deployVisible" width="480px" append-to-body>
      <template v-if="devicesLoaded && !myDevices.length">
        <xn-empty icon="device" :title="$t('xn.visuals.pack.noDevicesTitle')" :description="$t('xn.visuals.pack.noDevicesDesc')">
          <el-button type="primary" @click="goDevices">{{ $t('xn.visuals.pack.goDevices') }}</el-button>
        </xn-empty>
      </template>
      <template v-else>
        <p class="vp-help">{{ $t('rolePack.deployConfirm', { name: selectedPack && selectedPack.displayName }) }}</p>
        <el-form label-position="top" @submit.native.prevent>
          <el-form-item :label="$t('rolePack.selectDevice')" required>
            <el-select v-model="selectedDeviceId" filterable class="vp-full" :loading="!devicesLoaded" :placeholder="$t('rolePack.selectDevicePlaceholder')">
              <el-option v-for="d in myDevices" :key="d.id" :label="deviceLabel(d)" :value="d.id">
                <span>{{ d.alias || d.macAddress }}</span>
                <span class="vp-opt-meta xn-num">{{ d.board || '-' }} / {{ d.appVersion || '-' }}</span>
              </el-option>
            </el-select>
          </el-form-item>
        </el-form>
      </template>
      <span v-if="!devicesLoaded || myDevices.length" slot="footer">
        <el-button @click="deployVisible = false">{{ $t('button.cancel') }}</el-button>
        <el-button type="primary" :loading="deploying" :disabled="!selectedDeviceId" @click="confirmDeploy">{{ $t('rolePack.confirmDeploy') }}</el-button>
      </span>
    </el-dialog>

    <!-- 任务已创建 / 任务状态 -->
    <el-dialog :title="$t('rolePack.readyTitle')" :visible.sync="readyVisible" width="480px" append-to-body
      :close-on-click-modal="false" @closed="stopTaskPolling">
      <template v-if="deployTask">
        <dl class="vp-dl vp-dl--task">
          <dt>{{ $t('xn.visuals.pack.taskPack') }}</dt><dd>{{ taskPackName }}</dd>
          <dt>{{ $t('xn.visuals.pack.taskDevice') }}</dt><dd>{{ taskDeviceName }}</dd>
          <dt>{{ $t('rolePack.state') }}</dt>
          <dd><span class="xn-tag" :class="taskTagClass" role="status">{{ taskStateLabel }}</span></dd>
        </dl>
        <el-progress :percentage="taskProgress" :status="taskProgressStatus" :stroke-width="8" />
        <p v-if="taskError" class="vp-err">{{ taskError }}</p>
      </template>
      <p v-if="taskPollError" class="vp-warn">{{ $t('visualOta.networkFail') }}</p>
      <p class="vp-help vp-ready">{{ $t('rolePack.readyBody') }}</p>
      <p class="vp-help">{{ $t('rolePack.readyNote') }}</p>
      <p v-if="isMock" class="vp-demo"><demo-tag /> {{ $t('xn.visuals.pack.demoTaskNote') }}</p>
      <span slot="footer">
        <el-button type="primary" @click="readyVisible = false">{{ $t('rolePack.readyOk') }}</el-button>
      </span>
    </el-dialog>

    <!-- 演示视频 -->
    <el-dialog :title="$t('rolePack.demoTitle')" :visible.sync="demoVisible" width="640px" append-to-body @closed="onDemoClosed">
      <template v-if="isMock">
        <img class="vp-demo-media" :src="demoPoster" alt="" />
        <p class="vp-demo"><demo-tag /> {{ $t('xn.visuals.pack.demoVideoNote') }}</p>
      </template>
      <video v-else-if="demoSrc" class="vp-demo-media" :src="demoSrc" controls playsinline preload="metadata" controlslist="nodownload" />
    </el-dialog>

    <!-- 发布（管理员） -->
    <el-dialog :title="$t('rolePack.publishTitle')" :visible.sync="publishVisible" width="560px" append-to-body
      :close-on-click-modal="false" @close="resetPublish">
      <p class="vp-help">{{ $t('rolePack.publishHelp') }}</p>
      <el-form label-position="top" @submit.native.prevent>
        <el-form-item :label="$t('rolePack.displayName')" required>
          <el-input v-model="publishForm.displayName" maxlength="64" show-word-limit />
        </el-form-item>
        <el-form-item :label="$t('xn.visuals.pack.descLabel')">
          <el-input v-model="publishForm.description" type="textarea" :rows="2" maxlength="200" show-word-limit :placeholder="$t('xn.visuals.pack.descPlaceholder')" />
        </el-form-item>
        <el-form-item :label="$t('rolePack.file')" required>
          <div class="vp-file">
            <label class="el-button el-button--default el-button--small vp-file__btn">
              <xn-icon name="upload" /> {{ $t('xn.visuals.pack.chooseFile') }}
              <input ref="binInput" type="file" accept=".bin,application/octet-stream" @change="onFileChange" />
            </label>
            <span v-if="publishFile" class="vp-file__name xn-clip">{{ publishFile.name }}</span>
            <span v-if="publishFile" class="xn-muted xn-num">{{ formatSize(publishFile.size) }}</span>
            <span v-if="publishFile && publishFile.size > 4194304" class="vp-err-inline">{{ $t('rolePack.exceedsMaxSize') }}</span>
          </div>
          <p v-if="inspecting" class="vp-hint"><i class="el-icon-loading"></i> {{ $t('xn.visuals.pack.inspecting') }}</p>
        </el-form-item>
        <div v-if="parsedMeta" class="vp-parsed">
          <div class="vp-parsed__title">{{ $t('rolePack.parsedTitle') }} <demo-tag /></div>
          <p>{{ formatParsedLine('rolePack.parsedPackId', parsedMeta.packId) }}</p>
          <p>{{ formatParsedLine('rolePack.parsedVersion', parsedMeta.version) }}</p>
          <p>{{ formatParsedLine('rolePack.parsedRuntime', parsedMeta.spineRuntimeVersion || parsedMeta.format) }}</p>
          <p>{{ formatParsedLine('rolePack.parsedSize', formatSize(parsedMeta.size)) }}</p>
          <p>{{ formatParsedLine('rolePack.parsedBoards', (parsedMeta.defaultSupportedBoards || []).join(', ')) }}</p>
          <p v-if="isMock" class="vp-hint">{{ $t('xn.visuals.pack.demoParseNote') }}</p>
        </div>
        <div class="vp-row">
          <el-form-item :label="$t('rolePack.coverImage')">
            <div class="vp-file">
              <label class="el-button el-button--default el-button--small vp-file__btn">
                {{ $t('xn.visuals.pack.chooseFile') }}
                <input type="file" accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp" @change="onImageChange" />
              </label>
              <span v-if="previewImage" class="vp-file__name xn-clip">{{ previewImage.name }}</span>
            </div>
            <p class="vp-hint">{{ $t('rolePack.imageHint') }}</p>
          </el-form-item>
          <el-form-item :label="$t('rolePack.demoVideo')">
            <div class="vp-file">
              <label class="el-button el-button--default el-button--small vp-file__btn">
                {{ $t('xn.visuals.pack.chooseFile') }}
                <input type="file" accept="video/mp4,video/webm,.mp4,.webm" @change="onVideoChange" />
              </label>
              <span v-if="previewVideo" class="vp-file__name xn-clip">{{ previewVideo.name }}</span>
            </div>
            <p class="vp-hint">{{ $t('rolePack.videoHint') }}</p>
          </el-form-item>
        </div>
      </el-form>
      <span slot="footer">
        <el-button @click="publishVisible = false">{{ $t('button.cancel') }}</el-button>
        <el-button type="primary" :loading="publishing" :disabled="!parsedMeta" @click="confirmPublish">
          {{ $t('rolePack.confirmPublish') }}
        </el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
/**
 * 视觉角色（设备屏幕上的 Spine 形象包），与智能体的人设配置（roleConfig）无关。
 * 接口：Api.rolePack.catalog / detail / deploy / getTask / inspect / publish / disable（后三个仅管理员入口）。
 */
import Api from '@/apis/api'
import userApi from '@/apis/module/user'
import rolePackApi from '@/apis/module/rolePack'
import { resolveOtaApiMessage, translateOtaState, formatOtaFileSize, formatOtaFieldLine } from '@/utils/visualOtaI18n'
import { imageUrl, IS_MOCK } from '@/utils/media'

const MAX_SIZE = 4194304
const FINAL_STATES = ['completed', 'success', 'succeeded', 'failed', 'cancelled', 'needs_manual_review', 'expired']
/** 原 API 模块遇到业务错误不回调页面（由请求层弹出提示），超时后恢复按钮 / 显示失败状态 */
const GUARD_MS = 10000

export default {
  name: 'RolePackCatalog',
  data() {
    return {
      loading: false,
      loadFailed: false,
      catalog: [],
      keyword: '',
      myDevices: [],
      devicesLoaded: false,
      isSuperAdmin: false,
      detailVisible: false,
      detail: null,
      detailLoading: false,
      detailFailed: false,
      disabling: false,
      deployVisible: false,
      selectedPack: null,
      selectedDeviceId: '',
      deploying: false,
      readyVisible: false,
      deployTask: null,
      taskPollTimer: null,
      taskPollError: false,
      publishVisible: false,
      publishing: false,
      publishFile: null,
      previewImage: null,
      previewVideo: null,
      parsedMeta: null,
      inspecting: false,
      demoVisible: false,
      demoSrc: '',
      demoPoster: '',
      publishForm: {
        displayName: '',
        description: ''
      },
      isMock: IS_MOCK,
      guards: {}
    }
  },
  computed: {
    filtered() {
      const kw = this.keyword.toLowerCase()
      if (!kw) return this.catalog
      return this.catalog.filter((p) => String(p.displayName || '').toLowerCase().includes(kw) || String(p.description || '').toLowerCase().includes(kw))
    },
    detailFields() {
      const d = this.detail || {}
      const rows = [
        { k: 'packId', label: this.$t('xn.visuals.pack.packId'), value: d.packId, num: true },
        { k: 'version', label: this.$t('xn.visuals.pack.version'), value: d.version, num: true },
        { k: 'size', label: this.$t('xn.visuals.pack.size'), value: d.size ? this.formatSize(d.size) : '', num: true },
        { k: 'runtime', label: this.$t('rolePack.parsedRuntime'), value: d.spineRuntimeVersion },
        { k: 'boards', label: this.$t('xn.visuals.pack.boards'), value: (d.defaultSupportedBoards || d.supportedBoards || []).join(', ') },
        { k: 'minFw', label: this.$t('xn.visuals.pack.minFw'), value: d.minFirmware || d.minFw, num: true },
        { k: 'publishedAt', label: this.$t('xn.visuals.pack.publishedAt'), value: (d.publishedAt || d.createdAt || '').slice(0, 16), num: true },
      ]
      return rows.filter((r) => r.value)
    },
    taskStateLabel() {
      return translateOtaState(this, this.deployTask && this.deployTask.state)
    },
    taskProgress() {
      return Math.max(0, Math.min(100, Number(this.deployTask && this.deployTask.progress) || 0))
    },
    taskProgressStatus() {
      const state = this.deployTask && this.deployTask.state
      if (['failed', 'needs_manual_review', 'cancelled', 'expired'].includes(state)) return 'exception'
      if (['completed', 'success', 'succeeded'].includes(state)) return 'success'
      return undefined
    },
    taskTagClass() {
      const s = this.taskProgressStatus
      return s === 'exception' ? 'xn-tag--danger' : s === 'success' ? 'xn-tag--success' : 'xn-tag--lake'
    },
    taskError() {
      const code = this.deployTask && this.deployTask.errorCode
      if (!code || code === 'none') return ''
      return `${resolveOtaApiMessage(this, { code: 1, errorCode: code }, 'visualOta.error.generic')} (${code})`
    },
    taskPackName() {
      const id = this.deployTask && this.deployTask.packId
      const p = this.catalog.find((x) => x.packId === id) || this.selectedPack
      return (p && p.displayName) || id || '-'
    },
    taskDeviceName() {
      const id = this.deployTask && this.deployTask.deviceId
      const d = this.myDevices.find((x) => x.id === id)
      return d ? (d.alias || d.macAddress) : (id || '-')
    }
  },
  created() {
    this.fetchUser()
    this.loadCatalog()
    this.loadMyDevices()
  },
  beforeDestroy() {
    this.stopTaskPolling()
    Object.values(this.guards).forEach(clearTimeout)
  },
  methods: {
    /** 为一次请求设置超时：到时仍未回调就执行 onTimeout */
    guard(key, onTimeout) {
      clearTimeout(this.guards[key])
      this.guards[key] = setTimeout(onTimeout, GUARD_MS)
    },
    release(key) {
      clearTimeout(this.guards[key])
    },
    coverSrc(item) {
      const url = item.previewImageUrl || item.previewUrl
      if (!url) return ''
      if (/^(data:|blob:)/.test(url)) return url
      return imageUrl(rolePackApi.mediaUrl(url), item.displayName)
    },
    videoSrc(item) {
      return item.previewVideoUrl ? rolePackApi.mediaUrl(item.previewVideoUrl) : ''
    },
    openDemo(item) {
      this.demoSrc = this.videoSrc(item)
      this.demoPoster = this.coverSrc(item)
      this.demoVisible = true
    },
    onDemoClosed() {
      this.demoSrc = ''
    },
    fetchUser() {
      userApi.getUserInfo(({ data }) => {
        const info = data && data.data ? data.data : data
        this.isSuperAdmin = !!(info && (info.superAdmin === 1 || info.superAdmin === true))
      })
    },
    loadCatalog() {
      this.loading = true
      this.loadFailed = false
      this.guard('catalog', () => { this.loading = false; this.loadFailed = true })
      Api.rolePack.catalog((res) => {
        this.release('catalog')
        this.loading = false
        if (res && res.code === 0) {
          this.catalog = res.data || []
        } else {
          this.loadFailed = !this.catalog.length
          this.$message.error(resolveOtaApiMessage(this, res, 'rolePack.loadFailed'))
        }
      })
    },
    loadMyDevices() {
      this.devicesLoaded = false
      Api.agent.getAgentList(({ data }) => {
        const agents = (data && data.data) ? data.data : (data || [])
        const list = Array.isArray(agents) ? agents : []
        const devices = []
        let pending = list.length
        if (pending === 0) {
          this.myDevices = []
          this.devicesLoaded = true
          return
        }
        list.forEach((agent) => {
          const agentId = agent.id || agent.agentId
          Api.device.getAgentBindDevices(agentId, (res) => {
            const body = res && res.data ? res.data : res
            const arr = (body && body.data) ? body.data : (body || [])
            if (Array.isArray(arr)) {
              arr.forEach((d) => devices.push(d))
            }
            pending -= 1
            if (pending <= 0) {
              const map = {}
              devices.forEach((d) => { if (d && d.id) map[d.id] = d })
              this.myDevices = Object.values(map)
              this.devicesLoaded = true
            }
          })
        })
      })
    },
    openDetail(item) {
      this.detail = { ...item }
      this.detailFailed = false
      this.detailVisible = true
      this.detailLoading = true
      this.guard('detail', () => { this.detailLoading = false; this.detailFailed = true })
      Api.rolePack.detail(item.packId, (res) => {
        this.release('detail')
        this.detailLoading = false
        if (!this.detail || this.detail.packId !== item.packId) return
        if (res && res.code === 0 && res.data) this.detail = { ...item, ...res.data }
        else this.detailFailed = true
      })
    },
    detailToDeploy() {
      const item = this.catalog.find((p) => p.packId === this.detail.packId) || this.detail
      this.detailVisible = false
      this.openDeploy(item)
    },
    confirmDisable(item) {
      this.$confirm(this.$t('xn.visuals.pack.disableConfirm', { name: item.displayName }), this.$t('xn.visuals.pack.disableTitle'), {
        type: 'warning', confirmButtonText: this.$t('xn.visuals.pack.disable'), cancelButtonText: this.$t('button.cancel'),
        customClass: 'ot-delete-confirm'
      }).then(() => {
        this.disabling = true
        this.guard('disable', () => { this.disabling = false })
        Api.rolePack.disable(item.packId, (res) => {
          this.release('disable')
          this.disabling = false
          if (res && res.code === 0) {
            this.$message.success(this.$t('xn.visuals.pack.disabled'))
            this.detailVisible = false
            this.loadCatalog()
          } else {
            this.$message.error(resolveOtaApiMessage(this, res, 'xn.visuals.pack.disableFailed'))
          }
        })
      }).catch(() => {})
    },
    openDeploy(item) {
      this.selectedPack = item
      this.selectedDeviceId = this.myDevices.length === 1 ? this.myDevices[0].id : ''
      this.deployVisible = true
    },
    goDevices() {
      this.deployVisible = false
      this.$router.push('/device-management').catch(() => {})
    },
    stopTaskPolling() {
      clearTimeout(this.taskPollTimer)
      this.taskPollTimer = null
    },
    pollDeployTask(taskId) {
      if (!this.readyVisible || !this.deployTask || this.deployTask.taskId !== taskId) return
      Api.rolePack.getTask(taskId, (res) => {
        if (!this.readyVisible || !this.deployTask || this.deployTask.taskId !== taskId) return
        this.taskPollError = !res || res.code !== 0 || !res.data
        if (!this.taskPollError) this.deployTask = res.data
        if (!FINAL_STATES.includes(this.deployTask.state)) {
          this.taskPollTimer = setTimeout(() => this.pollDeployTask(taskId), 2000)
        }
      })
    },
    confirmDeploy() {
      if (!this.selectedDeviceId) {
        this.$message.warning(this.$t('rolePack.selectDevicePlaceholder'))
        return
      }
      this.deploying = true
      this.guard('deploy', () => { this.deploying = false })
      Api.rolePack.deploy(this.selectedPack.packId, this.selectedDeviceId, (res) => {
        this.release('deploy')
        this.deploying = false
        if (res && res.code === 0) {
          this.stopTaskPolling()
          this.deployTask = res.data && res.data.taskId ? res.data : null
          this.taskPollError = false
          this.deployVisible = false
          this.readyVisible = true
          if (this.deployTask) this.pollDeployTask(this.deployTask.taskId)
        } else {
          this.$message.error(resolveOtaApiMessage(this, res, 'rolePack.deployFailed'))
        }
      })
    },
    onFileChange(e) {
      this.publishFile = e.target.files && e.target.files[0] ? e.target.files[0] : null
      this.parsedMeta = null
      if (!this.publishFile) return
      if (this.publishFile.size > MAX_SIZE) {
        this.$message.error(this.$t('rolePack.fileTooLarge'))
        return
      }
      this.inspecting = true
      this.guard('inspect', () => { this.inspecting = false })
      Api.rolePack.inspect(this.publishFile, (res) => {
        this.release('inspect')
        this.inspecting = false
        if (res && res.code === 0) {
          this.parsedMeta = res.data
        } else {
          this.parsedMeta = null
          this.$message.error(resolveOtaApiMessage(this, res, 'rolePack.inspectFailed'))
        }
      })
    },
    onImageChange(e) {
      this.previewImage = e.target.files && e.target.files[0] ? e.target.files[0] : null
    },
    onVideoChange(e) {
      this.previewVideo = e.target.files && e.target.files[0] ? e.target.files[0] : null
    },
    resetPublish() {
      this.publishFile = null
      this.previewImage = null
      this.previewVideo = null
      this.parsedMeta = null
      this.publishing = false
      this.inspecting = false
      this.publishForm.displayName = ''
      this.publishForm.description = ''
      // 清空文件选择框，便于再次选择同一个文件（弹窗挂在 body 上）
      document.querySelectorAll('.vp-file input[type=file]').forEach((i) => { i.value = '' })
    },
    confirmPublish() {
      if (!this.publishForm.displayName || !this.publishForm.displayName.trim()) {
        this.$message.warning(this.$t('rolePack.displayNameRequired'))
        return
      }
      if (!this.publishFile) {
        this.$message.warning(this.$t('rolePack.fileRequired'))
        return
      }
      if (this.publishFile.size > MAX_SIZE) {
        this.$message.error(this.$t('rolePack.fileTooLarge'))
        return
      }
      if (!this.parsedMeta) {
        this.$message.warning(this.$t('rolePack.inspectFailed'))
        return
      }
      this.publishing = true
      this.guard('publish', () => { this.publishing = false })
      Api.rolePack.publish({
        displayName: this.publishForm.displayName.trim(),
        description: this.publishForm.description.trim(),
        spineBin: this.publishFile,
        previewImage: this.previewImage,
        previewVideo: this.previewVideo
      }, (res) => {
        this.release('publish')
        this.publishing = false
        if (res && res.code === 0) {
          this.$message.success(this.$t('rolePack.publishSuccess'))
          this.publishVisible = false
          this.loadCatalog()
        } else {
          this.$message.error(resolveOtaApiMessage(this, res, 'rolePack.publishFailed'))
        }
      })
    },
    formatSize(n) {
      return formatOtaFileSize(this, n)
    },
    formatParsedLine(labelKey, value) {
      return formatOtaFieldLine(this, labelKey, value)
    },
    deviceLabel(d) {
      const name = d.alias || d.deviceName || d.macAddress || d.id
      return `${name} (${d.board || '-'} / ${d.appVersion || '-'})`
    }
  }
}
</script>

<style scoped>
.vp-note { display: flex; align-items: center; flex-wrap: wrap; gap: 6px; margin: -6px 0 16px; font-size: 13px; color: var(--xn-ink-3); }
.vp-search-icon { height: 100%; margin: 0 2px 0 4px; font-size: 16px; color: var(--xn-ink-3); }
.vp-grid { grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); }
.vp-card { display: flex; flex-direction: column; min-width: 0; overflow: hidden; background: #fff; border: 1px solid var(--xn-line); border-radius: var(--xn-r-lg); }
.vp-cover {
  display: flex; align-items: center; justify-content: center; width: 100%; aspect-ratio: 16 / 10; padding: 0; overflow: hidden;
  border: 0; border-bottom: 1px solid var(--xn-line-2); background: var(--xn-mist-2); cursor: pointer;
}
.vp-cover img { width: 100%; height: 100%; object-fit: cover; }
.vp-cover__name { padding: 12px; font-weight: 600; color: var(--xn-ink-2); text-align: center; }
.vp-body { display: flex; flex-direction: column; gap: 8px; flex: 1; padding: 14px 16px 12px; }
.vp-title-row { display: flex; align-items: center; gap: 8px; min-width: 0; }
.vp-title { flex: 1; min-width: 0; margin: 0; font-size: 16px; font-weight: 600; color: var(--xn-ink); }
.vp-desc {
  flex: 1; margin: 0; font-size: 13px; line-height: 1.6; color: var(--xn-ink-3);
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.vp-actions { display: flex; align-items: center; gap: 4px; margin-top: 4px; }
.vp-card--skel .vp-cover { cursor: default; }
.vp-skel-line { display: block; height: 12px; border-radius: 6px; background: var(--xn-mist-2); }
.vp-skel-line.w60 { width: 60%; }

.vp-detail__cover { display: flex; align-items: center; justify-content: center; aspect-ratio: 16 / 9; overflow: hidden; border-radius: var(--xn-r-lg); background: var(--xn-mist-2); }
.vp-detail__cover img { width: 100%; height: 100%; object-fit: cover; }
.vp-detail__desc { margin: 14px 0; font-size: 14px; line-height: 1.7; color: var(--xn-ink-2); }
.vp-dl { display: grid; grid-template-columns: max-content 1fr; gap: 8px 16px; margin: 0 0 8px; font-size: 14px; }
.vp-dl dt { color: var(--xn-ink-3); }
.vp-dl dd { margin: 0; min-width: 0; color: var(--xn-ink); word-break: break-all; }
.vp-dl--task { margin-bottom: 14px; }
.vp-foot { display: flex; align-items: center; }

.vp-help { margin: 0 0 14px; font-size: 14px; line-height: 1.7; color: var(--xn-ink-2); }
.vp-ready { margin-top: 16px; }
.vp-hint { margin: 6px 0 0; font-size: 12px; line-height: 1.5; color: var(--xn-ink-3); }
.vp-warn { margin: 10px 0; font-size: 13px; color: var(--xn-warning); }
.vp-err { margin: 10px 0 0; font-size: 13px; color: var(--xn-danger); }
.vp-err-inline { font-size: 13px; color: var(--xn-danger); }
.vp-demo { display: flex; align-items: center; gap: 8px; margin: 12px 0 0; font-size: 13px; color: var(--xn-ink-3); }
.vp-demo-media { display: block; width: 100%; max-height: 70vh; border-radius: var(--xn-r); background: var(--xn-mist-2); object-fit: contain; }
.vp-full { width: 100%; }
.vp-opt-meta { float: right; margin-left: 16px; font-size: 12px; color: var(--xn-ink-3); }

.vp-file { display: flex; align-items: center; gap: 10px; min-width: 0; line-height: 1.4; }
.vp-file__btn { position: relative; flex: none; margin: 0; overflow: hidden; }
.vp-file__btn input { position: absolute; inset: 0; opacity: 0; cursor: pointer; }
.vp-file__btn:focus-within { box-shadow: var(--xn-focus); }
.vp-file__name { min-width: 0; font-size: 13px; color: var(--xn-ink); }
.vp-parsed { margin: -4px 0 18px; padding: 12px 14px; border-radius: var(--xn-r); background: var(--xn-mist-2); font-size: 13px; line-height: 1.7; color: var(--xn-ink-2); }
.vp-parsed__title { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; font-weight: 600; color: var(--xn-ink); }
.vp-parsed p { margin: 0; word-break: break-all; }
.vp-row { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
@media (max-width: 640px) { .vp-row { grid-template-columns: 1fr; } }
</style>
