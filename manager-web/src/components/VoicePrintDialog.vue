<template>
  <el-dialog :title="title" :visible="visible" width="520px" append-to-body :close-on-click-modal="false" :key="dialogKey"
    @close="cancel">
    <el-form :model="form" :rules="rules" ref="form" label-position="top" class="vp-form">
      <el-form-item :label="$t('voicePrintDialog.voicePrintVector')" prop="audioId">
        <p class="vp-help">{{ $t('xn.visuals.voice.sampleHelp') }}</p>
        <el-select v-model="form.audioId" :placeholder="$t('voicePrintDialog.selectVoiceMessage')" :loading="samplesLoading"
          :no-data-text="$t('xn.visuals.voice.noSamples')" popper-class="vp-popper" class="vp-full">
          <el-option v-for="item in valueTypeOptions" :key="item.audioId" :label="item.content || $t('xn.visuals.voice.untitled')" :value="item.audioId">
            <span class="vp-opt">
              <span class="vp-opt__text xn-clip">{{ item.content || $t('xn.visuals.voice.untitled') }}</span>
              <button type="button" class="vp-play" :class="{ 'is-on': playingAudioId === item.audioId }"
                :aria-label="playingAudioId === item.audioId ? $t('xn.visuals.voice.stop') : $t('xn.visuals.voice.play')"
                :title="playingAudioId === item.audioId ? $t('xn.visuals.voice.stop') : $t('xn.visuals.voice.play')"
                @click.stop="playAudio(item.audioId)">
                <i :class="getAudioIconClass(item.audioId)"></i>
              </button>
            </span>
          </el-option>
        </el-select>
        <p v-if="!samplesLoading && !valueTypeOptions.length" class="vp-empty">{{ $t('xn.visuals.voice.noSamples') }}</p>
      </el-form-item>

      <el-form-item :label="$t('voicePrintDialog.name')" prop="sourceName">
        <el-input v-model="form.sourceName" :readonly="memberBound" :class="{ 'vp-readonly': memberBound }"
          :placeholder="$t('voicePrintDialog.enterName')" maxlength="64" />
      </el-form-item>

      <el-form-item :label="$t('voicePrintDialog.description')" prop="introduce">
        <el-input type="textarea" v-model="form.introduce" :placeholder="$t('voicePrintDialog.enterDescription')" :rows="3"
          maxlength="100" show-word-limit />
      </el-form-item>
    </el-form>

    <span slot="footer">
      <el-button @click="cancel">{{ $t('voicePrintDialog.cancel') }}</el-button>
      <el-button type="primary" @click="submit" :loading="saving" :disabled="saving">{{ $t('voicePrintDialog.save') }}</el-button>
    </span>
  </el-dialog>
</template>

<script>
/**
 * 声纹录入 / 编辑。被 UnifiedUserManagement（memberBound：名称固定为成员昵称）与旧版 VoicePrint 页使用。
 * props / 事件不变：submit({ form, done })、cancel；关闭时通过 cancel 通知父组件（父组件用 .sync 或 @cancel 关闭）。
 * 声音样本来自该智能体最近 50 条用户语音（/agent/{id}/chat-history/user），试听走 src/utils/media.js 的 playableUrl。
 */
import api from '@/apis/api';
import { playableUrl } from '@/utils/media';

export default {
  props: {
    memberBound: { type: Boolean, default: false },
    title: {
      type: String,
      default: '添加说话人'
    },
    visible: {
      type: Boolean,
      default: false
    },
    agentId: {
      type: String
    },
    form: {
      type: Object,
      default: () => ({
        id: null,
        audioId: '',
        sourceName: '',
        introduce: ''
      })
    }
  },
  data() {
    return {
      dialogKey: Date.now(),
      saving: false,
      samplesLoading: false,
      playingAudioId: null,
      audioElement: null,
      valueTypeOptions: [],
    };
  },
  computed: {
    rules() {
      return {
        introduce: [
          { max: 100, message: this.$t('xn.visuals.voice.descTooLong'), trigger: 'blur' }
        ],
        sourceName: [
          { required: true, message: this.$t('xn.visuals.voice.nameRequired'), trigger: 'blur' }
        ],
        audioId: [
          { required: true, message: this.$t('voicePrintDialog.requiredAudioVector'), trigger: 'change' }
        ]
      };
    },
  },
  beforeDestroy() {
    this.stopAudio();
  },
  methods: {
    getAudioIconClass(audioId) {
      return this.playingAudioId === audioId ? 'el-icon-video-pause' : 'el-icon-video-play';
    },
    stopAudio() {
      if (this.audioElement) {
        this.audioElement.pause();
        this.audioElement = null;
      }
      this.playingAudioId = null;
    },
    playAudio(audioId) {
      if (this.playingAudioId === audioId) {
        // 如果正在播放当前音频，则停止播放
        this.stopAudio();
        return;
      }

      // 停止当前正在播放的音频
      this.stopAudio();

      // 先获取音频下载ID
      this.playingAudioId = audioId;
      api.agent.getAudioId(audioId, (res) => {
        if (this.playingAudioId !== audioId) return;
        if (res.data && res.data.data) {
          // 使用获取到的下载ID播放音频（mock 模式下 playableUrl 返回本机生成的演示音频）
          this.audioElement = new Audio(playableUrl(api.getServiceUrl() + `/agent/play/${res.data.data}`));

          this.audioElement.onended = () => {
            this.playingAudioId = null;
            this.audioElement = null;
          };

          const p = this.audioElement.play();
          if (p && p.catch) p.catch(() => { this.playingAudioId = null; this.audioElement = null; });
        } else {
          this.playingAudioId = null;
        }
      });
    },
    submit() {
      this.$refs.form.validate((valid) => {
        if (valid) {
          this.saving = true; // 开始加载
          this.$emit('submit', {
            form: this.form,
            done: () => {
              this.saving = false; // 加载完成
            }
          });

        }
      });
    },
    cancel() {
      this.saving = false; // 取消时重置状态
      this.stopAudio();
      this.$emit('update:visible', false);
      this.$emit('cancel');
    }
  },
  watch: {
    visible(newVal) {
      if (newVal) {
        this.dialogKey = Date.now();
        this.valueTypeOptions = [];
        this.samplesLoading = true;
        api.agent.getRecentlyFiftyByAgentId(this.agentId, ((data) => {
          this.samplesLoading = false;
          const list = ((data && data.data && data.data.code === 0 && data.data.data) || []).map(item => ({
            ...item
          }));
          // 保留编辑时已经补进来的当前样本
          const current = this.valueTypeOptions.filter((o) => !list.some((x) => x.audioId === o.audioId));
          this.valueTypeOptions = current.concat(list);
        }))
      } else {
        this.stopAudio();
      }
    },
    'form.audioId'(newVal) {
      if (newVal == null || newVal == "") {
        return
      }
      if (this.valueTypeOptions.some(item => item.audioId === newVal)) {
        return;
      }
      api.agent.getContentByAudioId(newVal, ((data) => {
        if (this.valueTypeOptions.some(item => item.audioId === newVal)) return;
        this.valueTypeOptions.push({
          audioId: newVal, content: data.data.data
        })
      }))
    }
  }
};
</script>

<style scoped>
.vp-form ::v-deep .el-form-item__label { padding-bottom: 4px; line-height: 1.5; }
.vp-help { margin: 0 0 8px; font-size: 13px; line-height: 1.6; color: var(--xn-ink-3); }
.vp-full { width: 100%; }
.vp-empty { margin: 8px 0 0; font-size: 13px; line-height: 1.6; color: var(--xn-warning); }
.vp-readonly ::v-deep .el-input__inner { background: var(--xn-mist-2); color: var(--xn-ink-2); cursor: default; }
</style>

<style>
/* 下拉层挂在 body 上，不能用 scoped */
.vp-popper .el-select-dropdown__item { display: flex; align-items: center; }
.vp-opt { display: flex; align-items: center; gap: 8px; width: 100%; min-width: 0; }
.vp-opt__text { flex: 1; min-width: 0; }
.vp-play {
  flex: none; display: inline-flex; align-items: center; justify-content: center; width: 28px; height: 28px; padding: 0;
  border: 0; border-radius: 6px; background: none; color: var(--xn-lake); cursor: pointer;
}
.vp-play:hover, .vp-play.is-on { background: var(--xn-lake-soft); }
</style>
