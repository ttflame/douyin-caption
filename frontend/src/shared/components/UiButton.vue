<script setup lang="ts">
import type { Component } from 'vue'
withDefaults(defineProps<{ variant?: 'primary' | 'secondary' | 'ghost' | 'danger'; size?: 'small' | 'medium'; loading?: boolean; disabled?: boolean; icon?: Component; type?: 'button' | 'submit' }>(), { variant: 'secondary', size: 'medium', type: 'button' })
</script>

<template>
  <button class="ui-button" :class="[`is-${variant}`, `is-${size}`]" :type="type" :disabled="disabled || loading">
    <span v-if="loading" class="button-loader" aria-hidden="true" />
    <component :is="icon" v-else-if="icon" :size="16" :stroke-width="1.8" aria-hidden="true" />
    <span><slot /></span>
  </button>
</template>

