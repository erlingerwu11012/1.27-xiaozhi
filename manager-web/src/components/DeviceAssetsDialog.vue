<template>
  <el-dialog
    :title="$t('deviceAssets.title')"
    :visible.sync="dialogVisible"
    width="720px"
    :close-on-click-modal="false"
    @close="handleClose"
    @open="handleOpen"
  >
    <div class="device-assets-body">
      <!-- 上传区域 -->
      <div class="upload-section">
        <div class="section-label">{{ $t('deviceAssets.uploadArea') }}</div>
        <el-select
          v-model="uploadFileType"
          :placeholder="$t('deviceAssets.selectType')"
          class="upload-type-select"
          size="small"
        >
          <el-option :label="$t('deviceAssets.typeEmoji')" value="emoji" />
          <el-option :label="$t('deviceAssets.typeWallpaper')" value="wallpaper" />
        </el-select>
        <el-upload
          ref="upload"
          class="upload-inline"
          action="#"
          :http-request="handleUpload"
          :before-upload="beforeUpload"
          :accept="'.jpg,.jpeg,.png,.JPG,.JPEG,.PNG'"
          :show-file-list="false"
          :disabled="!deviceId"
        >
          <el-button size="small" type="primary" :disabled="!deviceId">
            {{ $t('deviceAssets.clickUpload') }}
          </el-button>
        </el-upload>
        <span v-if="!deviceId" class="hint">{{ $t('deviceAssets.selectDeviceFirst') }}</span>
        <div class="upload-tip">{{ $t('deviceAssets.uploadTip') }}</div>
      </div>

      <!-- 预览列表 -->
      <div class="preview-section">
        <div class="section-label">{{ $t('deviceAssets.previewList') }}</div>
        <div v-loading="listLoading" class="asset-grid">
          <div v-if="assetList.length === 0 && !listLoading" class="empty-tip">
            {{ $t('deviceAssets.noAssets') }}
          </div>
          <div
            v-for="item in assetList"
            :key="item.id"
            class="asset-item"
          >
            <div class="asset-img-wrap">
              <img :src="imageUrl(item.fileUrl)" :alt="item.fileType" class="asset-img" @error="onImgError" />
              <span class="asset-type-tag">{{ item.fileType === 'emoji' ? $t('deviceAssets.typeEmoji') : $t('deviceAssets.typeWallpaper') }}</span>
            </div>
            <div class="asset-meta">v{{ item.version }}</div>
            <!-- 删除按钮占位，接口未实现时可隐藏 -->
            <!-- <el-button size="mini" type="text" class="asset-delete" @click="handleDelete(item)">删除</el-button> -->
          </div>
        </div>
      </div>

      <!-- 同步到设备 -->
      <div class="sync-section">
        <el-button
          type="primary"
          size="medium"
          class="sync-btn"
          :loading="syncLoading"
          :disabled="!deviceId"
          @click="handleSync"
        >
          {{ $t('deviceAssets.syncToDevice') }}
        </el-button>
      </div>
    </div>
  </el-dialog>
</template>

<script>
import Api from '@/apis/api';

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
      assetList: [],
      listLoading: false,
      syncLoading: false
    };
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
    },
    imageUrl(fileUrl) {
      if (!fileUrl) return '';
      const base = Api.getServiceUrl ? Api.getServiceUrl() : '';
      if (!base) return fileUrl;
      const path = fileUrl.startsWith('/') ? fileUrl : `/${fileUrl}`;
      return base.replace(/\/$/, '') + path;
    },
    onImgError(e) {
      const label = encodeURIComponent(this.$t('deviceAssets.imageLoadFailed'))
      e.target.src = `data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80" viewBox="0 0 80 80"><rect fill="%23f5f5f5" width="80" height="80"/><text x="50%" y="50%" dominant-baseline="middle" text-anchor="middle" fill="%23999" font-size="12">${label}</text></svg>`
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
      Api.device.uploadAsset(this.deviceId, this.uploadFileType, file, (res) => {
        if (res.data && (res.data.code === 0 || res.data.code === 'success')) {
          this.$message.success(this.$t('deviceAssets.uploadSuccess'));
          this.fetchList();
        } else {
          this.$message.error((res.data && res.data.msg) || this.$t('deviceAssets.uploadFailed'));
        }
      });
    },
    fetchList() {
      if (!this.deviceId) return;
      this.listLoading = true;
      Api.device.getAssetList(this.deviceId, (res) => {
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
      Api.device.syncAssets(this.deviceId, (res) => {
        this.syncLoading = false;
        if (res.data && (res.data.code === 0 || res.data.code === 'success')) {
          this.$message.success(this.$t('deviceAssets.syncSuccess'));
        } else {
          this.$message.warning((res.data && res.data.msg) || this.$t('deviceAssets.syncNotImplemented'));
        }
      });
    }
  }
};
</script>

<style scoped>
.device-assets-body {
  padding: 0 4px;
}
.section-label {
  font-size: 14px;
  color: #303133;
  margin-bottom: 10px;
  font-weight: 500;
}
.upload-section {
  margin-bottom: 20px;
}
.upload-type-select {
  width: 140px;
  margin-right: 10px;
}
.upload-inline {
  display: inline-block;
  margin-right: 8px;
}
.upload-inline ::v-deep .el-upload {
  display: inline-block;
}
.hint {
  font-size: 12px;
  color: #909399;
  margin-left: 8px;
}
.upload-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 8px;
}
.preview-section {
  margin-bottom: 24px;
}
.asset-grid {
  min-height: 120px;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
  gap: 12px;
}
.empty-tip {
  grid-column: 1 / -1;
  text-align: center;
  color: #909399;
  font-size: 13px;
  padding: 24px 0;
}
.asset-item {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  overflow: hidden;
  background: #fafafa;
}
.asset-img-wrap {
  position: relative;
  width: 100%;
  padding-top: 100%;
  background: #f5f7fa;
}
.asset-img {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  object-fit: cover;
}
.asset-type-tag {
  position: absolute;
  bottom: 4px;
  left: 4px;
  font-size: 10px;
  color: #fff;
  background: rgba(0, 0, 0, 0.5);
  padding: 2px 6px;
  border-radius: 4px;
}
.asset-meta {
  padding: 4px 8px;
  font-size: 12px;
  color: #909399;
}
.sync-section {
  text-align: center;
  padding-top: 8px;
  border-top: 1px solid #ebeef5;
}
.sync-btn {
  min-width: 200px;
  height: 44px;
  font-size: 16px;
}
</style>
