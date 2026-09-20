<script setup lang="ts">
import { computed } from 'vue'
import { presentAgentRun, type AgentRun } from './agentRun'
import StatusBadge from './StatusBadge.vue'

const props = defineProps<{ run: AgentRun; readOnly?: boolean }>()
const presentation = computed(() => presentAgentRun(props.run))
</script>

<template>
  <article class="agent-run-card" :data-readonly="readOnly || presentation.readOnly">
    <header>
      <div>
        <small>{{ presentation.title }}</small>
        <h3>{{ presentation.summary || presentation.title }}</h3>
      </div>
      <StatusBadge :label="presentation.statusLabel" :tone="presentation.tone" />
    </header>

    <dl v-if="presentation.facts.length" class="agent-run-facts">
      <div v-for="fact in presentation.facts" :key="fact.label">
        <dt>{{ fact.label }}</dt>
        <dd>{{ fact.value }}</dd>
      </div>
    </dl>

    <section v-for="list in presentation.lists" :key="list.label" class="agent-run-section">
      <h4>{{ list.label }}</h4>
      <ul>
        <li v-for="item in list.items" :key="item">{{ item }}</li>
      </ul>
    </section>

    <section v-if="presentation.citations.length" class="agent-run-section">
      <h4>引用依据</h4>
      <ul class="citation-list">
        <li v-for="citation in presentation.citations" :key="`${citation.sourceId}:${citation.title}`">
          <strong>{{ citation.title || citation.sourceId }}</strong>
          <span>{{ citation.sourceId }}<template v-if="citation.version"> · v{{ citation.version }}</template><template v-if="citation.score"> · {{ citation.score }}</template></span>
          <p v-if="citation.excerpt">{{ citation.excerpt }}</p>
        </li>
      </ul>
    </section>

    <section v-if="presentation.evidence.length" class="agent-run-section">
      <h4>模型调用证据</h4>
      <ul class="evidence-list">
        <li v-for="item in presentation.evidence" :key="`${item.agent}:${item.traceId}:${item.model}`">
          <strong>{{ item.agent || item.model }}</strong>
          <span>{{ item.model }}<template v-if="item.tokens"> · {{ item.tokens }} tokens</template><template v-if="item.traceId"> · {{ item.traceId }}</template><template v-if="item.status"> · {{ item.status }}</template></span>
        </li>
      </ul>
    </section>

    <section v-if="presentation.degradations.length" class="agent-run-section degradation-section">
      <h4>降级与失败</h4>
      <ul>
        <li v-for="item in presentation.degradations" :key="`${item.agent}:${item.code}`">
          <strong>{{ item.code }}</strong>
          <span v-if="item.agent"> · {{ item.agent }}</span>
          <p v-if="item.message">{{ item.message }}</p>
        </li>
      </ul>
    </section>

    <section v-if="presentation.allowedActions.length" class="agent-run-section">
      <h4>允许动作</h4>
      <p>{{ presentation.allowedActions.join(' · ') }}</p>
    </section>

    <footer v-if="$slots.actions" class="agent-run-actions">
      <slot name="actions" />
    </footer>
  </article>
</template>

<style scoped>
.agent-run-card {
  display: grid;
  gap: 14px;
  padding: 16px;
  border: 1px solid var(--mp-color-hairline);
  border-radius: var(--mp-radius-card);
  background: var(--mp-color-surface);
}

.agent-run-card[data-readonly='true'] {
  opacity: 0.82;
}

.agent-run-card > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.agent-run-card h3,
.agent-run-card h4,
.agent-run-card p,
.agent-run-card dl,
.agent-run-card ul {
  margin: 0;
}

.agent-run-card small,
.agent-run-card h4,
.agent-run-card dt,
.agent-run-card span {
  color: var(--mp-color-mute);
  font-size: 12px;
}

.agent-run-card h3 {
  margin-top: 4px;
  color: var(--mp-color-ink);
  font-size: 16px;
}

.agent-run-card h4 {
  margin-bottom: 6px;
  color: var(--mp-color-body);
  font-weight: 600;
}

.agent-run-facts {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 8px 16px;
}

.agent-run-facts div {
  display: grid;
  gap: 2px;
}

.agent-run-facts dd {
  margin: 0;
  color: var(--mp-color-ink);
  font-size: 13px;
}

.agent-run-section ul {
  display: grid;
  gap: 8px;
  padding-left: 18px;
}

.agent-run-section li,
.agent-run-section p {
  color: var(--mp-color-body);
  font-size: 13px;
  line-height: 1.5;
}

.citation-list li,
.evidence-list li {
  display: grid;
  gap: 2px;
}

.citation-list strong,
.evidence-list strong,
.degradation-section strong {
  color: var(--mp-color-ink);
  font-size: 13px;
}

.citation-list p,
.degradation-section p {
  margin-top: 2px !important;
}

.degradation-section {
  border-left: 2px solid var(--mp-color-warning);
  padding-left: 10px;
}

.agent-run-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding-top: 4px;
}
</style>
