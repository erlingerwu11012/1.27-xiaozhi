<template>
  <div class="pp">
    <div class="pp__head">
      <span class="pp__title">{{ $t('xn.agents.persona.title') }}</span>
      <el-button type="text" class="pp__edit" @click="$emit('edit')"><xn-icon name="edit" /> {{ $t('xn.agents.persona.custom') }}</el-button>
    </div>
    <p class="pp__hint">{{ $t('xn.agents.persona.hint') }}</p>
    <div class="pp__grid" role="group" :aria-label="$t('xn.agents.persona.title')">
      <button v-for="preset in presets" :key="preset.id" type="button"
        class="pp__card" :class="{ 'is-on': selectedId === preset.id }"
        :aria-pressed="String(selectedId === preset.id)" @click="selectPreset(preset)">
        <span class="pp__name">
          {{ preset.name }}
          <xn-icon v-if="selectedId === preset.id" name="check" class="pp__check" />
        </span>
        <span class="pp__desc">{{ preset.description }}</span>
      </button>
    </div>
  </div>
</template>

<script>
import { PERSONA_PRESETS, matchingPersonaPreset } from '@/constants/personaPresets';

export default {
  name: 'PersonaPresetPicker',
  props: { value: { type: String, default: '' } },
  data() { return { presets: PERSONA_PRESETS, selectionPending: false }; },
  computed: {
    selectedId() { const preset = matchingPersonaPreset(this.value); return preset ? preset.id : null; },
  },
  methods: {
    async selectPreset(preset) {
      if (this.selectionPending || this.selectedId === preset.id) return;
      this.selectionPending = true;
      try {
        if (String(this.value || '').trim() && !matchingPersonaPreset(this.value)) {
          await this.$confirm(this.$t('xn.agents.persona.replaceMsg'), this.$t('xn.agents.persona.replaceTitle'), {
            confirmButtonText: this.$t('xn.agents.persona.replace'), cancelButtonText: this.$t('xn.agents.persona.keep'), type: 'warning',
          });
        }
        this.$emit('input', preset.prompt);
      } catch (_) {
        // 关闭或取消时保留当前文字
      } finally {
        this.selectionPending = false;
      }
    },
  },
};
</script>

<style scoped>
.pp__head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.pp__title { font-size: 14px; font-weight: 600; color: var(--xn-ink); }
.pp__edit { padding: 0; }
.pp__hint { margin: 2px 0 12px; font-size: 13px; line-height: 1.6; color: var(--xn-ink-3); }
.pp__grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 8px; }
.pp__card {
  display: block; padding: 10px 12px; text-align: left; cursor: pointer;
  border: 1px solid var(--xn-line); border-radius: var(--xn-r); background: #fff; font: inherit; color: var(--xn-ink);
}
.pp__card:hover { border-color: #AEBBC8; }
.pp__card:focus-visible { outline: none; box-shadow: var(--xn-focus); }
.pp__card.is-on { border-color: var(--xn-lake); background: var(--xn-lake-soft); }
.pp__name { display: flex; align-items: center; justify-content: space-between; gap: 6px; font-size: 14px; font-weight: 600; line-height: 1.4; }
.pp__check { color: var(--xn-lake); font-size: 16px; }
.pp__desc { display: block; margin-top: 2px; font-size: 13px; line-height: 1.5; color: var(--xn-ink-3); }
</style>
