<script setup>
defineProps({
  evaluation: { type: Object, default: null },
  title: { type: String, default: '评价' },
  compact: { type: Boolean, default: false },
})

function publicLearningText(value) {
  return String(value || '')
    .replace(/\b(?:f\d+-)?(?:kp|event|trace|run)-[a-z0-9-]{6,}\b/gi, '当前知识点')
    .replace(/\b[a-f0-9]{24,}\b/gi, '')
    .replace(/\b(?:feynman_submitted|code_tests_passed|interactive_model_completed)\b/gi, '已完成学习活动')
}
</script>

<template>
  <section v-if="evaluation" :class="['evaluation-panel', { compact }]">
    <div class="evaluation-head">
      <h3>{{ title }}</h3>
      <strong>{{ evaluation.score }}<small>/100</small></strong>
    </div>
    <div class="dimension-list">
      <div v-for="item in evaluation.dimensions" :key="item.key" class="dimension-row">
        <div><span>{{ item.label }}</span><strong>{{ item.score }}/{{ item.maximum }}</strong></div>
        <progress :value="item.score" :max="item.maximum" :aria-label="item.label" />
        <p v-if="!compact">{{ publicLearningText(item.evidence) }}</p>
      </div>
    </div>
    <div v-if="!compact" class="evaluation-notes">
      <div v-if="evaluation.strengths?.length"><strong>已经做到</strong><ul><li v-for="(item, index) in evaluation.strengths" :key="index">{{ publicLearningText(item) }}</li></ul></div>
      <div v-if="evaluation.gaps?.length"><strong>需要补充</strong><ul><li v-for="(item, index) in evaluation.gaps" :key="index">{{ publicLearningText(item) }}</li></ul></div>
    </div>
  </section>
</template>

<style scoped>
.evaluation-panel { margin-top: 22px; border-top: 1px solid var(--color-border); padding-top: 22px; }
.evaluation-head { display: flex; justify-content: space-between; align-items: end; }
.evaluation-head h3 { margin: 0; font-size: 19px; }
.evaluation-head > strong { font-size: 28px; }
.evaluation-head small { color: var(--color-text-muted); font-size: 14px; }
.dimension-list { display: grid; gap: 13px; margin-top: 18px; }
.dimension-row > div { display: flex; justify-content: space-between; gap: 12px; font-size: 14px; }
.dimension-row progress { appearance: none; display: block; width: 100%; height: 5px; margin-top: 7px; border: 0; border-radius: 3px; overflow: hidden; background: var(--color-surface-muted); color: var(--color-success); }
.dimension-row progress::-webkit-progress-bar { background: var(--color-surface-muted); border-radius: 3px; }
.dimension-row progress::-webkit-progress-value { background: var(--color-success); border-radius: 3px; }
.dimension-row progress::-moz-progress-bar { background: var(--color-success); border-radius: 3px; }
.dimension-row p { margin: 5px 0 0; color: var(--color-text-muted); font-size: 14px; line-height: 1.55; }
.evaluation-notes { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }
.evaluation-notes > div { padding: 14px 0; }
.evaluation-notes ul { margin: 10px 0 0; padding-left: 20px; color: var(--color-text-secondary); line-height: 1.75; }
.evaluation-notes li + li { margin-top: 8px; }
.evaluation-panel.compact { margin-top: 15px; padding-top: 15px; }
.evaluation-panel.compact .dimension-list { grid-template-columns: repeat(5, minmax(0, 1fr)); }

@media (max-width: 760px) {
  .evaluation-notes,
  .evaluation-panel.compact .dimension-list { grid-template-columns: 1fr; }
}
</style>
