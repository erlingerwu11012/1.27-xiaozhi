<template>
  <div class="wallpaper-pack-page">
    <HeaderBar />

    <div class="operation-bar">
      <div>
        <h2 class="page-title">{{ $t('wallpaperPack.pageTitle') }}</h2>
        <p class="page-desc">{{ $t('wallpaperPack.pageDesc') }}</p>
      </div>
      <el-button v-if="isSuperAdmin" type="primary" class="btn-add" @click="publishVisible = true">
        {{ $t('wallpaperPack.publish') }}
      </el-button>
    </div>

    <div class="main-wrapper">
      <div class="content-panel">
        <div class="content-area">
          <el-alert
            :title="$t('wallpaperPack.isolationHint')"
            type="info"
            :closable="false"
            show-icon
            style="margin-bottom: 16px"
          />

          <el-row :gutter="16" v-loading="loading">
            <el-col :xs="24" :sm="12" :md="8" v-for="item in catalog" :key="item.packId" style="margin-bottom: 16px">
              <div class="role-card">
                <div class="preview" :class="{ 'has-media': !!coverSrc(item) }">
                  <img v-if="coverSrc(item)" :src="coverSrc(item)" alt="" />
                  <div v-else class="preview-placeholder">{{ item.displayName }}</div>
                  <button
                    v-if="videoSrc(item)"
                    type="button"
                    class="play-overlay"
                    @click="openDemo(item)"
                  >
                    {{ $t('wallpaperPack.watchDemo') }}
                  </button>
                </div>
                <div class="meta">
                  <h3>{{ item.displayName }}</h3>
                  <el-button type="warning" size="small" @click="openDeploy(item)">
                    {{ $t('wallpaperPack.downloadToDevice') }}
                  </el-button>
                </div>
              </div>
            </el-col>
          </el-row>

          <el-empty v-if="!loading && catalog.length === 0" :description="$t('wallpaperPack.empty')" />
        </div>
      </div>
    </div>

    <el-dialog :title="$t('wallpaperPack.deployTitle')" :visible.sync="deployVisible" width="480px" custom-class="wallpaper-pack-dialog">
      <p>{{ $t('wallpaperPack.deployConfirm', { name: selectedPack && selectedPack.displayName }) }}</p>
      <el-form label-width="90px">
        <el-form-item :label="$t('wallpaperPack.selectDevice')">
          <el-select v-model="selectedDeviceId" filterable style="width: 100%" :placeholder="$t('wallpaperPack.selectDevicePlaceholder')">
            <el-option
              v-for="d in myDevices"
              :key="d.id"
              :label="deviceLabel(d)"
              :value="d.id"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <span slot="footer">
        <el-button @click="deployVisible = false">{{ $t('button.cancel') }}</el-button>
        <el-button type="primary" :loading="deploying" @click="confirmDeploy">{{ $t('wallpaperPack.confirmDeploy') }}</el-button>
      </span>
    </el-dialog>

    <el-dialog
      :title="$t('wallpaperPack.readyTitle')"
      :visible.sync="readyVisible"
      width="480px"
      custom-class="wallpaper-pack-dialog"
      :close-on-click-modal="false"
    >
      <p class="ready-body">{{ $t('wallpaperPack.readyBody') }}</p>
      <p class="ready-note">{{ $t('wallpaperPack.readyNote') }}</p>
      <span slot="footer">
        <el-button type="primary" @click="readyVisible = false">{{ $t('wallpaperPack.readyOk') }}</el-button>
      </span>
    </el-dialog>

    <el-dialog
      :title="$t('wallpaperPack.demoTitle')"
      :visible.sync="demoVisible"
      width="640px"
      custom-class="wallpaper-pack-dialog demo-dialog"
      @closed="onDemoClosed"
    >
      <video
        v-if="demoSrc"
        class="demo-video"
        :src="demoSrc"
        controls
        playsinline
        preload="metadata"
        controlslist="nodownload"
      />
    </el-dialog>

    <el-dialog
      :title="$t('wallpaperPack.publishTitle')"
      :visible.sync="publishVisible"
      width="560px"
      custom-class="wallpaper-pack-dialog"
      @close="resetPublish"
    >
      <p class="publish-help">{{ $t('wallpaperPack.publishHelp') }}</p>
      <el-form label-width="120px" size="small">
        <el-form-item :label="$t('wallpaperPack.displayName')" required>
          <el-input v-model="publishForm.displayName" />
        </el-form-item>
        <el-form-item :label="$t('wallpaperPack.file')" required>
          <input type="file" accept=".bin,application/octet-stream" @change="onFileChange" />
          <div v-if="publishFile" class="field-hint">
            {{ publishFile.name }} · {{ formatSize(publishFile.size) }}
            <span v-if="publishFile.size > 2097152" style="color:#f56c6c">{{ $t('wallpaperPack.exceedsMaxSize') }}</span>
          </div>
        </el-form-item>
        <el-form-item :label="$t('wallpaperPack.coverImage')">
          <input type="file" accept="image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp" @change="onImageChange" />
          <div class="field-hint">{{ $t('wallpaperPack.imageHint') }}</div>
        </el-form-item>
        <el-form-item :label="$t('wallpaperPack.demoVideo')">
          <input type="file" accept="video/mp4,video/webm,.mp4,.webm" @change="onVideoChange" />
          <div class="field-hint">{{ $t('wallpaperPack.videoHint') }}</div>
        </el-form-item>
        <el-form-item v-if="parsedMeta" :label="$t('wallpaperPack.parsedTitle')">
          <div class="parsed-box">
            <p>{{ formatParsedLine('wallpaperPack.parsedPackId', parsedMeta.packId) }}</p>
            <p>{{ formatParsedLine('wallpaperPack.parsedVersion', parsedMeta.version) }}</p>
            <p>{{ formatParsedLine('wallpaperPack.parsedDefaultId', parsedMeta.defaultId) }}</p>
            <p>{{ formatParsedLine('wallpaperPack.parsedItemCount', parsedMeta.itemCount) }}</p>
            <p>{{ formatParsedLine('wallpaperPack.parsedSize', formatSize(parsedMeta.size)) }}</p>
            <p class="field-hint">{{ $t('wallpaperPack.sizeHint') }}</p>
          </div>
        </el-form-item>
      </el-form>
      <span slot="footer">
        <el-button @click="publishVisible = false">{{ $t('button.cancel') }}</el-button>
        <el-button type="primary" :loading="publishing" :disabled="!parsedMeta" @click="confirmPublish">
          {{ $t('wallpaperPack.confirmPublish') }}
        </el-button>
      </span>
    </el-dialog>
  </div>
</template>

<script>
import HeaderBar from '@/components/HeaderBar.vue'
import Api from '@/apis/api'
import userApi from '@/apis/module/user'
import wallpaperPackApi from '@/apis/module/wallpaperPack'
import { resolveOtaApiMessage, formatOtaFileSize, formatOtaFieldLine } from '@/utils/visualOtaI18n'

export default {
  name: 'WallpaperPackCatalog',
  components: { HeaderBar },
  data() {
    return {
      loading: false,
      catalog: [],
      myDevices: [],
      isSuperAdmin: false,
      deployVisible: false,
      selectedPack: null,
      selectedDeviceId: '',
      deploying: false,
      readyVisible: false,
      publishVisible: false,
      publishing: false,
      publishFile: null,
      previewImage: null,
      previewVideo: null,
      parsedMeta: null,
      inspecting: false,
      demoVisible: false,
      demoSrc: '',
      publishForm: {
        displayName: ''
      }
    }
  },
  created() {
    this.fetchUser()
    this.loadCatalog()
    this.loadMyDevices()
  },
  methods: {
    coverSrc(item) {
      const url = item.previewImageUrl || item.previewUrl
      return url ? wallpaperPackApi.mediaUrl(url) : ''
    },
    videoSrc(item) {
      return item.previewVideoUrl ? wallpaperPackApi.mediaUrl(item.previewVideoUrl) : ''
    },
    openDemo(item) {
      this.demoSrc = this.videoSrc(item)
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
      Api.wallpaperPack.catalog((res) => {
        this.loading = false
        if (res && res.code === 0) {
          this.catalog = res.data || []
        } else {
          this.$message.error(resolveOtaApiMessage(this, res, 'wallpaperPack.loadFailed'))
        }
      })
    },
    loadMyDevices() {
      Api.agent.getAgentList(({ data }) => {
        const agents = (data && data.data) ? data.data : (data || [])
        const list = Array.isArray(agents) ? agents : []
        const devices = []
        let pending = list.length
        if (pending === 0) {
          this.myDevices = []
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
            }
          })
        })
      })
    },
    openDeploy(item) {
      this.selectedPack = item
      this.selectedDeviceId = this.myDevices.length === 1 ? this.myDevices[0].id : ''
      this.deployVisible = true
    },
    confirmDeploy() {
      if (!this.selectedDeviceId) {
        this.$message.warning(this.$t('wallpaperPack.selectDevicePlaceholder'))
        return
      }
      this.deploying = true
      Api.wallpaperPack.deploy(this.selectedPack.packId, this.selectedDeviceId, (res) => {
        this.deploying = false
        if (res && res.code === 0) {
          this.deployVisible = false
          this.readyVisible = true
        } else {
          this.$message.error(resolveOtaApiMessage(this, res, 'wallpaperPack.deployFailed'))
        }
      })
    },
    onFileChange(e) {
      this.publishFile = e.target.files && e.target.files[0] ? e.target.files[0] : null
      this.parsedMeta = null
      if (!this.publishFile) return
      if (this.publishFile.size > 2097152) {
        this.$message.error(this.$t('wallpaperPack.fileTooLarge'))
        return
      }
      this.inspecting = true
      Api.wallpaperPack.inspect(this.publishFile, (res) => {
        this.inspecting = false
        if (res && res.code === 0) {
          this.parsedMeta = res.data
        } else {
          this.parsedMeta = null
          this.$message.error(resolveOtaApiMessage(this, res, 'wallpaperPack.inspectFailed'))
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
      this.publishForm.displayName = ''
    },
    confirmPublish() {
      if (!this.publishForm.displayName || !this.publishForm.displayName.trim()) {
        this.$message.warning(this.$t('wallpaperPack.displayNameRequired'))
        return
      }
      if (!this.publishFile) {
        this.$message.warning(this.$t('wallpaperPack.fileRequired'))
        return
      }
      if (this.publishFile.size > 2097152) {
        this.$message.error(this.$t('wallpaperPack.fileTooLarge'))
        return
      }
      if (!this.parsedMeta) {
        this.$message.warning(this.$t('wallpaperPack.inspectFailed'))
        return
      }
      this.publishing = true
      Api.wallpaperPack.publish({
        displayName: this.publishForm.displayName.trim(),
        spineBin: this.publishFile,
        previewImage: this.previewImage,
        previewVideo: this.previewVideo
      }, (res) => {
        this.publishing = false
        if (res && res.code === 0) {
          this.$message.success(this.$t('wallpaperPack.publishSuccess'))
          this.publishVisible = false
          this.loadCatalog()
        } else {
          this.$message.error(resolveOtaApiMessage(this, res, 'wallpaperPack.publishFailed'))
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
.wallpaper-pack-page { min-height: 100vh; background: #f5f7fb; }
.operation-bar {
  max-width: 1200px; margin: 24px auto 0; padding: 0 20px;
  display: flex; justify-content: space-between; align-items: flex-start;
}
.page-title { margin: 0; font-size: 22px; color: #1f2a44; }
.page-desc { margin: 6px 0 0; color: #909399; font-size: 13px; }
.main-wrapper { max-width: 1200px; margin: 16px auto 40px; padding: 0 20px; }
.content-panel {
  background: #fff; border-radius: 12px; padding: 20px;
  box-shadow: 0 2px 12px rgba(31, 42, 68, 0.06);
}
.role-card {
  border: 1px solid #ebeef5; border-radius: 10px; overflow: hidden; height: 100%;
  display: flex; flex-direction: column; background: #fff;
}
.preview {
  position: relative;
  height: 160px;
  background: linear-gradient(135deg, #eef2ff 0%, #dbe4ff 100%);
  display: flex; align-items: center; justify-content: center;
}
.preview img { width: 100%; height: 100%; object-fit: cover; }
.preview-placeholder { color: #4f6ef6; font-weight: 600; padding: 12px; text-align: center; }
.play-overlay {
  position: absolute; left: 50%; bottom: 10px; transform: translateX(-50%);
  border: 0; border-radius: 16px; padding: 6px 12px;
  background: rgba(0, 0, 0, 0.62); color: #fff; cursor: pointer; font-size: 12px;
}
.meta { padding: 12px 14px 16px; flex: 1; display: flex; flex-direction: column; gap: 10px; }
.meta h3 { margin: 0; font-size: 16px; color: #303133; }
.field-hint { margin-top: 6px; font-size: 12px; color: #909399; line-height: 1.4; }
.ready-body { margin: 0 0 12px; font-size: 14px; color: #303133; line-height: 1.6; }
.ready-note { margin: 0; font-size: 13px; color: #909399; line-height: 1.6; }
.publish-help { margin: 0 0 12px; font-size: 13px; color: #606266; line-height: 1.5; }
.parsed-box {
  background: #f5f7fa; border-radius: 8px; padding: 8px 10px;
  font-size: 12px; color: #606266; line-height: 1.6;
}
.parsed-box p { margin: 0; word-break: break-all; }
.demo-video { width: 100%; max-width: 100%; max-height: 70vh; background: #111; display: block; }
.btn-add { background: #4f6ef6; border-color: #4f6ef6; }
@media (max-width: 640px) {
  .operation-bar { flex-direction: column; gap: 12px; }
  .preview { height: 180px; }
}
</style>

<style>
.wallpaper-pack-dialog {
  max-width: calc(100vw - 24px);
}
.wallpaper-pack-dialog .el-dialog__body {
  padding: 12px 16px 8px;
}
.demo-dialog .el-dialog__body {
  overflow: hidden;
}
</style>
