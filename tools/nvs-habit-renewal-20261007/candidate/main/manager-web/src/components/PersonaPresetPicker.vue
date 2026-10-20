<template>
  <div class="persona-presets">
    <div class="persona-presets__heading">选择一个人格模板</div>
    <p class="persona-presets__hint">模板只是起点，选好后可以继续编辑，也可以直接写自己的设定。</p>
    <div class="persona-presets__grid">
      <button v-for="preset in presets" :key="preset.id" type="button"
        class="persona-presets__card" :class="{ 'is-selected': selectedId === preset.id }"
        :aria-pressed="selectedId === preset.id" @click="selectPreset(preset)">
        <span class="persona-presets__name">{{ preset.name }}</span>
        <span class="persona-presets__description">{{ preset.description }}</span>
      </button>
    </div>
    <el-button type="text" @click="$emit('edit')">直接自定义 / 修改当前设定</el-button>
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
          await this.$confirm('选择模板会替换当前自定义的人格文字。是否替换？', '替换人格设定', {
            confirmButtonText: '替换', cancelButtonText: '保留当前文字', type: 'warning',
          });
        }
        this.$emit('input', preset.prompt);
      } catch (_) {
        // Closing or cancelling leaves the draft untouched.
      } finally {
        this.selectionPending = false;
      }
    },
  },
};
</script>

<style scoped>
.persona-presets__heading { font-weight: 600; color: #18243b; }
.persona-presets__hint { margin: 6px 0 12px; color: #66758d; font-size: 13px; line-height: 1.6; }
.persona-presets__grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.persona-presets__card { text-align: left; padding: 12px; background: #fff; border: 1px solid #dce3ef; border-radius: 10px; cursor: pointer; font: inherit; }
.persona-presets__card:hover, .persona-presets__card:focus-visible { border-color: #326bff; outline: 2px solid #dbe6ff; }
.persona-presets__card.is-selected { border-color: #326bff; background: #f0f5ff; }
.persona-presets__name, .persona-presets__description { display: block; }
.persona-presets__name { color: #18243b; font-weight: 600; font-size: 14px; }
.persona-presets__description { margin-top: 5px; color: #66758d; font-size: 12px; line-height: 1.5; }
@media (max-width: 420px) { .persona-presets__grid { grid-template-columns: 1fr; } }
</style>
