<script setup lang="ts">
import { computed } from 'vue'
import { artifactDisplay, type AgentRun } from './agentRun'
const props = defineProps<{ run: AgentRun; readOnly?: boolean }>()
const display = computed(() => artifactDisplay(props.run))
</script>
<template>
  <article class="agent-run-card">
    <small>{{ display.title }} · {{ run.status }}</small>
    <p>{{ run.payload?.advice_text || run.payload?.summary || run.payload?.outcome_summary || '' }}</p>
    <p v-if="display.title === '没有依据'">没有依据</p>
    <ul v-if="run.citations?.length">
      <li v-for="(citation, index) in run.citations" :key="index">{{ citation }}</li>
    </ul>
    <p v-if="run.degradations?.length">存在降级：{{ run.degradations.length }} 项</p>
    <slot />
  </article>
</template>