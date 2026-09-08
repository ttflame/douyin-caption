<script setup lang="ts">
const props = withDefaults(defineProps<{ modelValue: string | number; label: string; type?: 'text' | 'password' | 'number' | 'url'; placeholder?: string; hint?: string; error?: string; multiline?: boolean; rows?: number; min?: number; max?: number; disabled?: boolean }>(), { type: 'text', rows: 3 })
const emit = defineEmits<{ 'update:modelValue': [value: string | number] }>()
function update(event: Event) {
  const target = event.target as HTMLInputElement | HTMLTextAreaElement
  emit('update:modelValue', props.type === 'number' ? Number(target.value) : target.value)
}
</script>

<template>
  <label class="ui-field">
    <span class="field-label">{{ label }}</span>
    <textarea v-if="multiline" class="field-control field-textarea" :value="modelValue" :placeholder="placeholder" :rows="rows" :disabled="disabled" @input="update" />
    <input v-else class="field-control" :value="modelValue" :type="type" :placeholder="placeholder" :min="min" :max="max" :disabled="disabled" @input="update" />
    <span v-if="error" class="field-error">{{ error }}</span>
    <span v-else-if="hint" class="field-hint">{{ hint }}</span>
  </label>
</template>

