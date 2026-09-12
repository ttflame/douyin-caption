<script setup lang="ts">
import UiField from '../../shared/components/UiField.vue'
import type { CreativeSettings } from '../../shared/types'

const settings = defineModel<CreativeSettings>({ required: true })
const lengths = [300, 500, 800, 1200, 2000]

function selectLength(value: number) {
  settings.value.targetLengthMode = 'fixed'
  settings.value.targetCharacters = value
}
</script>

<template>
  <section class="form-section">
    <div class="section-heading"><h2>目标字数</h2><span>{{ settings.targetLengthMode === 'follow_source' ? '跟随原文' : '按中文字符控制' }}</span></div>
    <UiField v-model="settings.targetCharacters" label="目标字数" type="number" :min="1" :max="20000" :disabled="settings.targetLengthMode === 'follow_source'" :hint="settings.targetLengthMode === 'follow_source' ? '生成稿将保持与原文大致相当的篇幅' : ''" @update:model-value="settings.targetLengthMode = 'fixed'" />
    <div class="choice-row" aria-label="长度方式">
      <button class="choice-button" :class="{ active: settings.targetLengthMode === 'follow_source' }" type="button" @click="settings.targetLengthMode = 'follow_source'">跟随原文</button>
      <button v-for="value in lengths" :key="value" class="choice-button" :class="{ active: settings.targetLengthMode === 'fixed' && settings.targetCharacters === value }" type="button" @click="selectLength(value)">{{ value }} 字</button>
    </div>
  </section>
  <section class="form-section"><div class="section-heading"><h2>人物与受众</h2><span>决定说话位置</span></div><div class="two-columns"><UiField v-model="settings.persona" label="人设背景" multiline :rows="4" /><UiField v-model="settings.audience" label="目标受众" multiline :rows="4" /></div></section>
  <section class="form-section"><div class="section-heading"><h2>表达方式</h2><span>决定成品听感</span></div><div class="two-columns"><UiField v-model="settings.languageStyle" label="语言风格" multiline :rows="4" /><UiField v-model="settings.contentStructure" label="内容结构" multiline :rows="4" /></div></section>
  <section class="form-section"><div class="section-heading"><h2>输出与约束</h2><span>明确不能偏离的边界</span></div><div class="two-columns"><UiField v-model="settings.outputSpecification" label="输出要求" multiline :rows="4" /><UiField v-model="settings.hardConstraints" label="强制约束" multiline :rows="4" /></div></section>
</template>
