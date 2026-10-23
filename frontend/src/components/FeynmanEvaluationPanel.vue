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
        <progress :value="item.score" :max="item.maximum" />
        <p v-if="!compact">{{ publicLearningText(item.evidence) }}</p>
      </div>
    </div>
    <div v-if="!compact" class="evaluation-notes">
      <div><strong>已经做到</strong><p>{{ publicLearningText(evaluation.strengths?.join('、')) }}</p></div>
      <div><strong>需要补充</strong><p>{{ publicLearningText(evaluation.gaps?.join('、')) }}</p></div>
    </div>
  </section>
</template>

<style scoped>
.evaluation-panel { margin-top: 22px; border-top: 1px solid #dce0df; padding-top: 22px; }
.evaluation-head { display: flex; justify-content: space-between; align-items: end; }
.evaluation-head h3 { margin: 0; font-size: 19px; }
.evaluation-head > strong { font-size: 28px; }
.evaluation-head small { color: #60727c; font-size: 14px; }
.dimension-list { display: grid; gap: 13px; margin-top: 18px; }
.dimension-row > div { display: flex; justify-content: space-between; gap: 12px; font-size: 14px; }
.dimension-row progress { width: 100%; height: 7px; margin-top: 7px; accent-color: #11212d; }
.dimension-row p { margin: 5px 0 0; color: #60727c; font-size: 14px; line-height: 1.55; }
.evaluation-notes { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 18px; }
.evaluation-notes > div { padding: 14px 16px; border: 1px solid #dce0df; border-radius: 7px; }
.evaluation-notes p { margin: 7px 0 0; color: #4a5c6a; line-height: 1.65; }
.evaluation-panel.compact { margin-top: 15px; padding-top: 15px; }
.evaluation-panel.compact .dimension-list { grid-template-columns: repeat(5, minmax(0, 1fr)); }

@media (max-width: 760px) {
  .evaluation-notes,
  .evaluation-panel.compact .dimension-list { grid-template-columns: 1fr; }
}
</style>
