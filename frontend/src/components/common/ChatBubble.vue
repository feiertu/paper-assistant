<script setup lang="ts">
import { computed } from 'vue'
import { marked } from 'marked'

const props = defineProps<{
  content: string
  role?: 'user' | 'assistant'
  isMarkdown?: boolean
}>()

const renderedHtml = computed(() => {
  if (props.isMarkdown && props.content) {
    return marked(props.content, { breaks: true })
  }
  return props.content
})
</script>

<template>
  <div :class="['chat-bubble', role || 'assistant']">
    <div v-if="isMarkdown" class="prose" v-html="renderedHtml"></div>
    <template v-else>{{ content }}</template>
  </div>
</template>
