<template>
  <el-dialog
    :title="$t('deviceAssets.title')"
    :visible.sync="dialogVisible"
    width="720px"
    append-to-body
    :close-on-click-modal="false"
    @close="handleClose"
    @open="handleOpen"
  >
    <p class="da-desc">{{ $t('xn.visuals.assets.desc') }}</p>

    <!-- 上传 -->
    <section class="da-upload">
      <span class="da-label">{{ $t('xn.visuals.assets.type') }}</span>
      <el-radio-group v-model="uploadFileType" size="small">
        <el-radio-button label="emoji">{{ $t('deviceAssets.typeEmoji') }}</el-radio-button>
        <el-radio-button label="wallpaper">{{ $t('deviceAssets.typeWallpaper') }}</el-radio-button>
      </el-radio-group>
      <el-upload
        ref="upload"
        class="da-upload__btn"
        action="#"
        :http-request="handleUpload"
        :before-upload="beforeUpload"
        :accept="'.jpg,.jpeg,.png,.JPG,.JPEG,.PNG'"
        :show-file-list="false"
        :disabled="!deviceId || uploading"
      >
        <el-button size="small" :loading="uploading" :disabled="!deviceId">
          <xn-icon v-if="!uploading" name="upload" /> {{ uploading ? $t('xn.visuals.assets.uploading') : $t('deviceAssets.clickUpload') }}
        </el-button>
      </el-upload>
      <span class="da-tip">{{ deviceId ? $t('deviceAssets.uploadTip') : $t('deviceAssets.selectDeviceFirst') }}</span>
    </section>

    <!-- 已上传 -->
    <section class="da-list">
      <div class="da-list__head">
        <span class="da-label">{{ $t('deviceAssets.previewList') }} <span class="xn-muted xn-num">{{ assetList.length }}</span></span>
        <el-radio-group v-if="assetList.length" v-model="filterType" size="mini">
          <el-radio-button label="all">{{ $t('xn.visuals.assets.filterAll') }}</el-radio-button>
          <el-radio-button label="emoji">{{ $t('deviceAssets.typeEmoji') }}</el-radio-button>
          <el-radio-button label="wallpaper">{{ $t('deviceAssets.typeWallpaper') }}</el-radio-button>
        </el-radio-group>
      </div>
      <div v-loading="listLoading" class="da-grid-wrap">
        <xn-empty v-if="!visibleAssets.length && !listLoading" icon="image" :title="$t('deviceAssets.noAssets')" :description="$t('xn.visuals.assets.emptyDesc')" />
        <div v-else class="da-grid">
          <figure v-for="item in visibleAssets" :key="item.id" class="da-item">
            <div class="da-item__img">
              <img :src="imageUrl(item.fileUrl)" :alt="item.fileName || item.fileType" @error="onImgError" />
            </div>
            <figcaption class="da-item__meta">
              <span class="xn-tag" :class="item.fileType === 'emoji' ? 'xn-tag--warning' : 'xn-tag--lake'">{{ item.fileType === 'emoji' ? $t('deviceAssets.typeEmoji') : $t('deviceAssets.typeWallpaper') }}</span>
              <span class="xn-muted xn-num">v{{ item.version }}</span>
            </figcaption>
          </figure>
        </div>
      </div>
    </section>

    <span slot="footer" class="da-foot">
      <span class="da-foot__hint xn-muted">{{ $t('xn.visuals.assets.syncHint') }}</span>
      <el-button @click="dialogVisible = false">{{ $t('xn.common.close') }}</el-button>
      <el-button type="primary" :loading="syncLoading" :disabled="!deviceId" @click="handleSync">
        <xn-icon v-if="!syncLoading" name="refresh" /> {{ $t('deviceAssets.syncToDevice') }}
      </el-button>
    </span>
  </el-dialog>
</template>

<script>
/**
 * 设备图片资源（表情 / 壁纸）：从设备管理页打开。props / 事件不变：visible(.sync)、deviceId。
 * 接口：Api.device.getAssetList / uploadAsset / syncAssets，字段 id / fileType / fileUrl / version。
 */
import Api from '@/apis/api';
import { imageUrl as mediaImageUrl } from '@/utils/media';

export default {
  name: 'DeviceAssetsDialog',
  props: {
    visible: {
      type: Boolean,
      default: false
    },
    deviceId: {
      type: String,
      default: ''
    }
  },
  data() {
    return {
      dialogVisible: this.visible,
      uploadFileType: 'emoji',
      filterType: 'all',
      assetList: [],
      listLoading: false,
      syncLoading: false,
      uploading: false
    };
  },
  computed: {
    visibleAssets() {
      return this.filterType === 'all' ? this.assetList : this.assetList.filter((a) => a.fileType === this.filterType);
    }
  },
  watch: {
    visible(val) {
      this.dialogVisible = val;
    },
    dialogVisible(val) {
      this.$emit('update:visible', val);
    },
    deviceId() {
      if (this.dialogVisible && this.deviceId) {
        this.fetchList();
      }
    }
  },
  methods: {
    handleOpen() {
      if (this.deviceId) {
        this.fetchList();
      }
    },
    handleClose() {
      this.assetList = [];
      this.uploadFileType = 'emoji';
      this.filterType = 'all';
    },
    imageUrl(fileUrl) {
      if (!fileUrl) return '';
      if (/^(data:|blob:)/.test(fileUrl)) return fileUrl;
      const base = Api.getServiceUrl ? Api.getServiceUrl() : '';
      if (!base) return mediaImageUrl(fileUrl);
      const path = fileUrl.startsWith('/') ? fileUrl : `/${fileUrl}`;
      return mediaImageUrl(base.replace(/\/$/, '') + path);
    },
    onImgError(e) {
      const label = encodeURIComponent(this.$t('deviceAssets.imageLoadFailed'))
      e.target.src = `data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80" viewBox="0 0 80 80"><rect fill="%23EEF2F5" width="80" height="80"/><text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" fill="%2366748A" font-size="12">${label}</text></svg>`
    },
    beforeUpload(file) {
      const isImage = ['image/jpeg', 'image/png', 'image/jpg'].includes(file.type);
      if (!isImage) {
        this.$message.warning(this.$t('deviceAssets.acceptJpgPng'));
        return false;
      }
      const isLt5M = file.size / 1024 / 1024 < 5;
      if (!isLt5M) {
        this.$message.warning(this.$t('deviceAssets.sizeLimit'));
        return false;
      }
      return true;
    },
    handleUpload({ file }) {
      if (!this.deviceId) {
        this.$message.warning(this.$t('deviceAssets.selectDeviceFirst'));
        return;
      }
      this.uploading = true;
      const guard = setTimeout(() => { this.uploading = false; }, 15000);
      Api.device.uploadAsset(this.deviceId, this.uploadFileType, file, (res) => {
        clearTimeout(guard);
        this.uploading = false;
        if (res.data && (res.data.code === 0 || res.data.code === 'success')) {
          this.$message.success(this.successText(res.data.msg, 'deviceAssets.uploadSuccess'));
          this.filterType = 'all';
          this.fetchList();
        } else {
          this.$message.error((res.data && res.data.msg) || this.$t('deviceAssets.uploadFailed'));
        }
      });
    },
    fetchList() {
      if (!this.deviceId) return;
      this.listLoading = true;
      const guard = setTimeout(() => { this.listLoading = false; }, 10000);
      Api.device.getAssetList(this.deviceId, (res) => {
        clearTimeout(guard);
        this.listLoading = false;
        if (res.data && (res.data.code === 0 || res.data.code === 'success')) {
          this.assetList = res.data.data || [];
        } else {
          this.assetList = [];
        }
      });
    },
    handleSync() {
      if (!this.deviceId) {
        this.$message.warning(this.$t('deviceAssets.selectDeviceFirst'));
        return;
      }
      this.syncLoading = true;
      const guard = setTimeout(() => { this.syncLoading = false; }, 15000);
      Api.device.syncAssets(this.deviceId, (res) => {
        clearTimeout(guard);
        this.syncLoading = false;
        if (res.data && (res.data.code === 0 || res.data.code === 'success')) {
          this.$message.success(this.successText(res.data.msg, 'deviceAssets.syncSuccess'));
        } else {
          this.$message.warning((res.data && res.data.msg) || this.$t('deviceAssets.syncNotImplemented'));
        }
      });
    },
    /** 服务端返回了具体说明（例如演示模式的“没有向设备下发”）就显示它，否则用默认文案 */
    successText(msg, key) {
      return msg && msg !== 'success' ? msg : this.$t(key);
    }
  }
};
</script>

<style scoped>
.da-desc { margin: 0 0 16px; font-size: 13px; line-height: 1.7; color: var(--xn-ink-3); }
.da-label { font-size: 14px; font-weight: 500; color: var(--xn-ink-2); }
.da-upload {
  display: flex; align-items: center; flex-wrap: wrap; gap: 10px 12px; padding: 14px 16px; margin-bottom: 16px;
  border: 1px solid var(--xn-line); border-radius: var(--xn-r-lg); background: var(--xn-mist-2);
}
.da-upload__btn ::v-deep .el-upload { display: inline-block; }
.da-tip { font-size: 13px; color: var(--xn-ink-3); }
.da-list__head { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
.da-grid-wrap { min-height: 160px; }
.da-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(112px, 1fr)); gap: 12px; max-height: 360px; overflow-y: auto; }
.da-item { margin: 0; border: 1px solid var(--xn-line); border-radius: var(--xn-r); overflow: hidden; background: #fff; }
.da-item__img { position: relative; padding-top: 100%; background: var(--xn-mist-2); }
.da-item__img img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; }
.da-item__meta { display: flex; align-items: center; justify-content: space-between; gap: 6px; padding: 6px 8px; font-size: 12px; }
.da-foot { display: flex; align-items: center; gap: 8px; }
.da-foot__hint { flex: 1; text-align: left; font-size: 12px; }
@media (max-width: 760px) {
  .da-foot { flex-wrap: wrap; }
  .da-foot__hint { flex-basis: 100%; }
}
</style>
