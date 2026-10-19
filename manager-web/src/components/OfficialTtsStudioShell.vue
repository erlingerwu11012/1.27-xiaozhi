<template>
  <div class="ot-studio">
    <HeaderBar />
    <div class="ot-studio__stage">
      <div class="ot-studio__body">
        <nav class="ot-studio__tabs" aria-label="官方语音功能">
          <button
            v-for="tab in tabs"
            :key="tab.key"
            type="button"
            class="ot-studio__tab"
            :class="{ 'is-active': activeTab === tab.key }"
            :disabled="tab.disabled"
            :title="tab.disabled ? '暂未开放' : ''"
            @click="goTab(tab)"
          >
            {{ tab.label }}
          </button>
        </nav>

        <div class="ot-studio__hero">
          <slot name="hero" />
        </div>

        <p v-if="warning" class="ot-studio__banner">{{ warning }}</p>

        <div class="ot-composer" :class="{ 'is-compact': compact }">
          <span class="ot-composer__ring" aria-hidden="true" />
          <div class="ot-composer__inner">
            <slot name="composer" />
          </div>
        </div>

        <div class="ot-bottom">
          <slot name="bottom" />
        </div>
      </div>
    </div>
  </div>
</template>

<script>
import HeaderBar from "@/components/HeaderBar.vue";
import "@/styles/official-tts-studio.scss";

export default {
  name: "OfficialTtsStudioShell",
  components: { HeaderBar },
  props: {
    activeTab: {
      type: String,
      required: true,
      validator: (v) => ["synth", "design", "clone"].includes(v),
    },
    warning: { type: String, default: "" },
    compact: { type: Boolean, default: false },
  },
  data() {
    return {
      tabs: [
        { key: "synth", label: "语音合成", path: "/official-tts/dubbing" },
        { key: "design", label: "音色设计", path: "/official-tts/voices", query: { mode: "design" } },
        { key: "clone", label: "音色复刻", path: "/official-tts/voices", query: { mode: "clone" } },
      ],
    };
  },
  methods: {
    goTab(tab) {
      if (tab.disabled || this.activeTab === tab.key || !tab.path) return;
      const query = { ...(tab.query || {}) };
      const agentId = this.$route.query.agentId;
      if (agentId) query.agentId = agentId;
      this.$router.push({ path: tab.path, query });
    },
  },
};
</script>
