<script setup>
import { computed } from 'vue'
import { LoaderCircle } from '@lucide/vue'

const props = defineProps({ task: Object, connectionError: String })
defineEmits(['refresh'])
const active = computed(() => props.task?.automation?.enabled
  ? !['completed', 'cancelled'].includes(props.task.automation.state)
  : ['queued', 'running'].includes(props.task?.status))
const stage = computed(() => props.task?.progress || {})
const title = computed(() => ['retry_wait', 'waiting_configuration', 'needs_attention'].includes(props.task?.automation?.state)
  ? props.task.automation.message : props.task?.status === 'queued' ? '即将开始安排学习'
  : stage.value.stage === 'review' ? '正在核对学习安排'
    : stage.value.stage === 'summary' ? '正在整理全程目标与阶段成果'
      : stage.value.stage === 'saved' ? '正在衔接后续内容' : '正在安排学习内容')
</script>

<template>
  <div v-if="active || connectionError" class="path-preparation" role="status" data-testid="path-generation-progress">
    <template v-if="active">
      <strong><LoaderCircle :size="17" class="path-preparation__spinner" />{{ title }}</strong>
      <progress v-if="stage.total" :value="stage.completed" :max="stage.total" aria-label="学习任务安排进度" />
      <p>{{ stage.total ? `已核对 ${stage.completed} / ${stage.total} 项学习安排。` : '' }}可以离开此页，回来后继续查看。</p>
    </template>
    <p v-if="connectionError">{{ connectionError }} <button type="button" @click="$emit('refresh')">重新读取</button></p>
  </div>
</template>

<style scoped>
.path-preparation { margin: 16px 0; color: var(--text-secondary, #526476); font-size: 14px; line-height: 1.6; }
.path-preparation strong { display: flex; align-items: center; gap: 8px; color: var(--text-primary, #293949); font-weight: 600; }
.path-preparation progress { appearance: none; border: 0; display: block; width: 100%; height: 5px; margin: 12px 0; border-radius: 4px; overflow: hidden; background: #e2e7e9; color: #687e94; }
.path-preparation progress::-webkit-progress-bar { background: #e2e7e9; border-radius: 4px; }
.path-preparation progress::-webkit-progress-value { background: #687e94; border-radius: 4px; }
.path-preparation progress::-moz-progress-bar { background: #687e94; border-radius: 4px; }
.path-preparation p { margin: 8px 0 0; }
.path-preparation button { color: #3d647e; text-decoration: underline; text-underline-offset: 3px; }
.path-preparation__spinner { animation: path-preparation-spin 1.2s linear infinite; }
@keyframes path-preparation-spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) { .path-preparation__spinner { animation: none; } }
</style>
