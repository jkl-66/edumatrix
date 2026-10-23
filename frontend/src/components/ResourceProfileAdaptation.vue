<script setup>
import { computed } from 'vue'

const props = defineProps({
  adaptation: { type: Object, default: () => ({}) },
  plan: { type: Object, default: () => ({}) },
  summary: { type: String, default: '' },
  title: { type: String, default: '画像适配' },
  resourceType: { type: String, default: 'resource' },
})

const resourceLabel = computed(() => ({
  handout: '讲义',
  mind_map: '思维导图',
  quiz: '测验题',
  training_task: '实训任务书',
  code_sandbox: '代码沙盒',
  video: '视频推荐',
  deck: 'PPT/网页课件',
  interactive_model: '可交互模型',
  feynman: '费曼复述任务',
})[props.resourceType] || '资源')

const hasContent = computed(() => {
  const source = props.plan && Object.keys(props.plan).length ? props.plan : props.adaptation
  return Boolean(props.summary || source?.profileSummary || source?.profile_adaptation || source?.difficulty_label)
})

const sentence = computed(() => `本${resourceLabel.value}已按你的学习情况调整内容与难度。`)
</script>

<template>
  <p v-if="hasContent" class="resource-profile-adaptation" data-testid="resource-profile-adaptation">
    {{ sentence }}
  </p>
</template>

<style scoped>
.resource-profile-adaptation {
  margin: 14px 0;
  color: #4e6470;
  font-size: 14px;
  line-height: 1.5;
}
</style>
