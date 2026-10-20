<template>
  <el-dialog
    :visible.sync="visibleProxy"
    :title="$t('xn.tts.libTitle')"
    width="820px"
    custom-class="ot-lib-dialog"
    append-to-body
    :close-on-click-modal="false"
  >
    <div class="ot-lib">
      <div class="ot-lib__toolbar">
        <el-radio-group v-model="tab" size="small">
          <el-radio-button v-for="t in tabs" :key="t.key" :label="t.key">{{ $t(t.label) }}</el-radio-button>
        </el-radio-group>
        <el-input v-model="keyword" size="small" clearable :placeholder="$t('xn.tts.libSearch')" class="ot-lib__search">
          <xn-icon slot="prefix" name="search" class="ot-lib__search-icon" />
        </el-input>
        <span class="xn-toolbar__grow"></span>
        <el-button size="small" @click="goCreate"><xn-icon name="plus" /> {{ $t('xn.tts.libCreate') }}</el-button>
      </div>

      <div class="ot-lib__grid" v-loading="loading" role="radiogroup" :aria-label="$t('xn.tts.libTitle')">
        <xn-empty v-if="!loading && !filteredItems.length" class="ot-lib__empty" icon="voice"
          :title="keyword ? $t('xn.tts.libNoMatch') : emptyText" />
        <div
          v-for="item in filteredItems"
          :key="item.code"
          class="ot-lib__card"
          :class="{ 'is-selected': selected === item.code, 'is-playing': playingCode === item.code }"
          role="radio"
          :aria-checked="String(selected === item.code)"
          tabindex="0"
          @click="selected = item.code"
          @keydown.enter.prevent="selected = item.code"
          @keydown.space.prevent="selected = item.code"
        >
          <button v-if="item.id" type="button" class="ot-play"
            :class="{ 'is-on': playingCode === item.code && !playPaused }"
            :title="playingCode === item.code && !playPaused ? $t('xn.tts.pause') : $t('xn.tts.play')"
            :aria-label="(playingCode === item.code && !playPaused ? $t('xn.tts.pause') : $t('xn.tts.play')) + ' ' + item.name"
            @click.stop="togglePlay(item)">
            <i v-if="loadingCode === item.code" class="el-icon-loading" />
            <svg v-else-if="playingCode === item.code && !playPaused" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5v14M16 5v14" /></svg>
            <svg v-else viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13l10-6.5z" /></svg>
          </button>
          <span v-else class="ot-lib__avatar" aria-hidden="true"><xn-icon name="voice" /></span>
          <div class="ot-lib__body">
            <p class="ot-lib__name xn-clip">{{ item.name }}</p>
            <p class="ot-lib__meta xn-clip">{{ item.meta }}</p>
          </div>
          <xn-icon v-if="selected === item.code" name="check" class="ot-lib__check" />
          <span v-if="playingCode === item.code" class="ot-lib__progress" :style="{ width: playPercent + '%' }" />
        </div>
      </div>
    </div>

    <audio
      ref="libAudio"
      class="ot-audio-el"
      @timeupdate="onAudioTime"
      @loadedmetadata="onAudioMeta"
      @ended="stopPlay"
      @pause="playPaused = true"
      @play="playPaused = false"
    />

    <span slot="footer">
      <el-button @click="visibleProxy = false">{{ $t('xn.common.cancel') }}</el-button>
      <el-button type="primary" :disabled="!selected" @click="confirm">{{ $t('xn.tts.libConfirm') }}</el-button>
    </span>
  </el-dialog>
</template>

<script>
import officialTts from "@/apis/module/officialTts";

export default {
  name: "OfficialTtsVoiceLibrary",
  props: {
    visible: { type: Boolean, default: false },
    value: { type: String, default: "" },
    officialVoices: { type: Array, default: () => [] },
  },
  data() {
    return {
      tab: "official",
      tabs: [
        { key: "official", label: "xn.tts.libOfficial" },
        { key: "design", label: "xn.tts.libDesign" },
        { key: "clone", label: "xn.tts.libClone" },
      ],
      keyword: "",
      selected: "",
      myVoices: [],
      loading: false,
      playingCode: "",
      loadingCode: "",
      playUrl: "",
      playPaused: true,
      playCurrent: 0,
      playDuration: 0,
    };
  },
  computed: {
    visibleProxy: {
      get() {
        return this.visible;
      },
      set(v) {
        this.$emit("update:visible", v);
      },
    },
    playPercent() {
      if (!this.playDuration) return 0;
      return Math.min(100, (this.playCurrent / this.playDuration) * 100);
    },
    filteredItems() {
      const kw = (this.keyword || "").trim().toLowerCase();
      return this.currentItems.filter((it) => {
        if (!kw) return true;
        return (it.name || "").toLowerCase().includes(kw)
          || (it.code || "").toLowerCase().includes(kw)
          || (it.meta || "").toLowerCase().includes(kw);
      });
    },
    currentItems() {
      if (this.tab === "official") {
        return (this.officialVoices || []).map((v) => ({
          code: v.code,
          name: v.name || v.code,
          meta: this.$t("xn.tts.libOfficialMeta"),
          kind: "official",
          id: null,
          playable: false,
        }));
      }
      const kind = this.tab === "design" ? "design" : "clone";
      return (this.myVoices || [])
        .filter((v) => {
          if (kind === "design") return v.kind === "design";
          return v.kind === "clone";
        })
        .filter((v) => v.status === "available" && v.upstreamVoiceId)
        .map((v) => ({
          code: v.upstreamVoiceId,
          name: v.name || v.upstreamVoiceId,
          meta: v.kind === "design" ? this.$t("xn.tts.libDesign") : this.$t("xn.tts.libClone"),
          kind: v.kind,
          id: v.id,
          playable: v.hasPreview === true || v.hasPreview === "true",
        }));
    },
    emptyText() {
      if (this.tab === "official") return this.$t("xn.tts.libEmptyOfficial");
      if (this.tab === "design") return this.$t("xn.tts.libEmptyDesign");
      return this.$t("xn.tts.libEmptyClone");
    },
  },
  watch: {
    visible(val) {
      if (val) {
        this.selected = this.value || "";
        this.keyword = "";
        this.loadMine();
      } else {
        this.stopPlay();
      }
    },
    tab() {
      this.stopPlay();
    },
  },
  beforeDestroy() {
    this.stopPlay();
  },
  methods: {
    onAudioTime(e) {
      this.playCurrent = (e && e.target && e.target.currentTime) || 0;
    },
    onAudioMeta(e) {
      const d = e && e.target && e.target.duration;
      this.playDuration = Number.isFinite(d) ? d : 0;
    },
    stopPlay() {
      const el = this.$refs.libAudio;
      if (el) {
        el.pause();
        el.removeAttribute("src");
        if (typeof el.load === "function") el.load();
      }
      if (this.playUrl) {
        URL.revokeObjectURL(this.playUrl);
        this.playUrl = "";
      }
      this.playingCode = "";
      this.loadingCode = "";
      this.playPaused = true;
      this.playCurrent = 0;
      this.playDuration = 0;
    },
    /** 该音色暂无可播音频：给出服务端原因并刷新列表 */
    previewMissing(err) {
      this.$message.warning(this.blobError(err) || this.$t("xn.tts.previewGenFailed"));
      this.loadMine();
    },
    /** blob 请求失败时服务端返回的是 JSON，需要读出来才能拿到 msg */
    blobError(err) {
      const fallback = this.$t("xn.tts.previewGenFailed");
      if (!err) return fallback;
      if (err.__blobText) {
        try {
          const parsed = JSON.parse(err.__blobText);
          return (parsed && (parsed.msg || parsed.message)) || fallback;
        } catch (e) {
          return fallback;
        }
      }
      const data = err.data;
      if (data && !(data instanceof Blob) && typeof data === "object") {
        return data.msg || data.message || fallback;
      }
      return (typeof data === "string" && data) || fallback;
    },
    /** axios 把错误体当 blob 返回，先异步读成文本挂在 err 上供 blobError 使用 */
    async captureBlobText(err) {
      const data = err && err.data;
      if (!(data instanceof Blob) || err.__blobText) return;
      try {
        err.__blobText = await data.text();
      } catch (e) {
        // 读不出来就退回默认文案
      }
    },
    async togglePlay(item) {
      if (!item || !item.id) return;
      if (this.playingCode === item.code) {
        const el = this.$refs.libAudio;
        if (!el) return;
        if (el.paused) el.play().catch(() => {});
        else el.pause();
        return;
      }
      this.loadingCode = item.code;
      const onOk = (blob) => {
        this.loadingCode = "";
        this.stopPlay();
        this.playUrl = URL.createObjectURL(blob);
        this.playingCode = item.code;
        this.playPaused = false;
        this.playCurrent = 0;
        this.playDuration = 0;
        this.$nextTick(() => {
          const el = this.$refs.libAudio;
          if (!el) return;
          el.src = this.playUrl;
          el.play().catch(() => {
            this.stopPlay();
            this.$message.error(this.$t("xn.tts.playFailed"));
          });
        });
      };
      const onFail = async (err) => {
        await this.captureBlobText(err);
        this.loadingCode = "";
        this.previewMissing(err);
      };
      if (item.playable) {
        officialTts.fetchVoicePreview(item.id, onOk, onFail);
      } else {
        // 尚无试听音频：按需生成一条（用户主动点击才产生费用）
        officialTts.ensureVoicePreview(item.id, onOk, onFail);
      }
    },
    loadMine() {
      this.loading = true;
      officialTts.listVoices((res) => {
        this.myVoices = (res.data && res.data.data) || [];
        this.loading = false;
      }, () => {
        this.myVoices = [];
        this.loading = false;
      });
    },
    goCreate() {
      this.visibleProxy = false;
      const query = { mode: this.tab === "clone" ? "clone" : "design" };
      const agentId = this.$route.query.agentId;
      if (agentId) query.agentId = agentId;
      this.$router.push({ path: "/official-tts/voices", query });
    },
    confirm() {
      if (!this.selected) return;
      const hit = this.filteredItems.find((i) => i.code === this.selected)
        || this.currentItems.find((i) => i.code === this.selected);
      this.stopPlay();
      this.$emit("input", this.selected);
      this.$emit("confirm", hit || { code: this.selected, name: this.selected });
      this.visibleProxy = false;
    },
  },
};
</script>
