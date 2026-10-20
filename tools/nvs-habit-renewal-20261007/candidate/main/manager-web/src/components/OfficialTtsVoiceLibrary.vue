<template>
  <el-dialog
    :visible.sync="visibleProxy"
    title="音色库"
    width="860px"
    custom-class="ot-voice-lib-dialog"
    append-to-body
    :close-on-click-modal="false"
  >
    <div class="ot-voice-lib">
      <div class="ot-voice-lib__tabs">
        <button
          v-for="t in tabs"
          :key="t.key"
          type="button"
          class="ot-voice-lib__tab"
          :class="{ 'is-active': tab === t.key }"
          @click="tab = t.key"
        >
          {{ t.label }}
        </button>
      </div>

      <div class="ot-voice-lib__toolbar">
        <el-select v-model="filterScene" size="small" class="ot-voice-lib__filter">
          <el-option label="全场景" value="" />
        </el-select>
        <el-select v-model="filterGender" size="small" class="ot-voice-lib__filter">
          <el-option label="全性别" value="" />
        </el-select>
        <el-select v-model="filterLang" size="small" class="ot-voice-lib__filter">
          <el-option label="全语言" value="" />
        </el-select>
        <el-input
          v-model="keyword"
          size="small"
          clearable
          prefix-icon="el-icon-search"
          placeholder="搜索音色名"
          class="ot-voice-lib__search"
        />
        <button type="button" class="ot-voice-lib__create" @click="goCreate">
          + 创建音色
        </button>
      </div>

      <div class="ot-voice-lib__grid" v-loading="loading">
        <div v-if="!loading && !filteredItems.length" class="ot-voice-lib__empty">
          {{ emptyText }}
        </div>
        <div
          v-for="(item, idx) in filteredItems"
          :key="item.code"
          class="ot-voice-lib__card"
          :class="{
            'is-selected': selected === item.code,
            'is-playing': playingCode === item.code,
          }"
          role="button"
          tabindex="0"
          @click="selected = item.code"
          @keydown.enter.prevent="selected = item.code"
          @keydown.space.prevent="selected = item.code"
        >
          <button
            v-if="item.id"
            type="button"
            class="ot-voice-lib__avatar ot-voice-lib__avatar--action"
            :class="avatarClass(idx)"
            :title="playingCode === item.code && !playPaused ? '暂停试听' : '试听'"
            :aria-label="playingCode === item.code && !playPaused ? '暂停试听' : '试听'"
            @click.stop="togglePlay(item)"
          >
            <i v-if="loadingCode === item.code" class="el-icon-loading" />
            <i
              v-else
              :class="playingCode === item.code && !playPaused ? 'el-icon-video-pause' : 'el-icon-video-play'"
            />
          </button>
          <span v-else class="ot-voice-lib__avatar" :class="avatarClass(idx)">
            <i class="el-icon-video-play" />
          </span>
          <div class="ot-voice-lib__body">
            <p class="ot-voice-lib__name">
              {{ item.name }}
              <span class="ot-voice-lib__id-tag">ID</span>
            </p>
            <p class="ot-voice-lib__meta">{{ item.meta }}</p>
          </div>
          <i v-if="selected === item.code" class="el-icon-check ot-voice-lib__check" />
          <span
            v-if="playingCode === item.code"
            class="ot-voice-lib__progress"
            :style="{ width: playPercent + '%' }"
          />
        </div>
      </div>
    </div>

    <audio
      ref="libAudio"
      class="ot-voice-lib__audio"
      @timeupdate="onAudioTime"
      @loadedmetadata="onAudioMeta"
      @ended="stopPlay"
      @pause="playPaused = true"
      @play="playPaused = false"
    />

    <span slot="footer" class="ot-voice-lib__footer">
      <button type="button" class="ot-voice-lib__confirm" :disabled="!selected" @click="confirm">
        确认
      </button>
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
        { key: "official", label: "官方" },
        { key: "design", label: "我的设计" },
        { key: "clone", label: "我的复刻" },
      ],
      filterScene: "",
      filterGender: "",
      filterLang: "",
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
          meta: "官方音色",
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
          meta: v.kind === "design" ? "我的设计" : "我的复刻",
          kind: v.kind,
          id: v.id,
          playable: v.hasPreview === true || v.hasPreview === "true",
        }));
    },
    emptyText() {
      if (this.tab === "official") return "暂无官方音色";
      if (this.tab === "design") return "暂无可用的设计音色，请先在「音色设计」中创建";
      return "暂无可用的复刻音色，请先在「音色复刻」中创建";
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
    avatarClass(idx) {
      const list = ["is-blue", "is-pink", "is-amber", "is-green"];
      return list[idx % list.length];
    },
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
      this.$message.warning(this.blobError(err) || "试听音频生成失败，请稍后重试");
      this.loadMine();
    },
    /** blob 请求失败时服务端返回的是 JSON，需要读出来才能拿到 msg */
    blobError(err) {
      const fallback = "试听音频生成失败，请稍后重试";
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
            this.$message.error("播放失败");
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
