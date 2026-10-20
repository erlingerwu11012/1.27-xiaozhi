<template>
  <div class="xn-page ot-studio">
    <page-header :title="title">
      <template v-if="$slots.hero" #description><slot name="hero" /></template>
      <slot name="actions" />
    </page-header>

    <nav class="ot-tabs" role="tablist" :aria-label="$t('xn.tts.tabsLabel')">
      <button v-for="tab in tabs" :key="tab.key" type="button" role="tab" class="ot-tabs__tab"
        :class="{ 'is-active': activeTab === tab.key }" :aria-selected="String(activeTab === tab.key)"
        :disabled="tab.disabled" @click="goTab(tab)">
        <xn-icon :name="tab.icon" /> {{ $t(tab.label) }}
      </button>
    </nav>

    <el-alert v-if="warning" class="ot-warning" type="warning" :title="warning" :closable="false" show-icon />

    <section class="xn-panel ot-composer" :class="{ 'is-compact': compact }">
      <slot name="composer" />
    </section>

    <div class="ot-bottom">
      <slot name="bottom" />
    </div>
  </div>
</template>

<script>
import "@/styles/official-tts-studio.scss";

export default {
  name: "OfficialTtsStudioShell",
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
        { key: "synth", label: "xn.tts.tabSynth", icon: "mic", path: "/official-tts/dubbing" },
        { key: "design", label: "xn.tts.tabDesign", icon: "tune", path: "/official-tts/voices", query: { mode: "design" } },
        { key: "clone", label: "xn.tts.tabClone", icon: "voice", path: "/official-tts/voices", query: { mode: "clone" } },
      ],
    };
  },
  computed: {
    title() {
      return this.activeTab === "synth" ? this.$t("xn.nav.ttsDubbing") : this.$t("xn.nav.ttsVoices");
    },
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
