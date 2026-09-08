<script setup lang="ts">
import type { Component } from 'vue'
defineProps<{ icon: Component; title: string; description: string }>()
</script>

<template>
  <div class="state-panel">
    <component :is="icon" :size="28" :stroke-width="1.5" aria-hidden="true" />
    <h2>{{ title }}</h2>
    <p>{{ description }}</p>
    <slot />
  </div>
</template>

