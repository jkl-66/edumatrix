<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import AggregationStatus from '../components/AggregationStatus.vue'
import ReviewScheduleBoard from '../components/ReviewScheduleBoard.vue'
import ReviewToolsPanel from '../components/ReviewToolsPanel.vue'
import { createNote } from '../api/notes'

const props = defineProps({ studentId: String })
const router = useRouter()
const activeStudentId = computed(() => props.studentId || localStorage.getItem('edumatrix_student_id') || localStorage.getItem('edumatrix_username') || '')
const noteBusyId = ref('')

async function openReviewNote(task) {
  const sourceId = String(task?.source_id || '')
  if (!activeStudentId.value || !/^\d+$/.test(sourceId) || noteBusyId.value) return
  noteBusyId.value = String(task.id)
  try {
    const concept = task.knowledge_point?.title || task.knowledge_point_title || task.title || '复习记录'
    const note = await createNote(activeStudentId.value, {
      source_type: 'review_task',
      source_metadata: { source_id: sourceId },
      content: `# ${concept}\n\n本次复习记录：`,
      tags: ['复习记录'],
      concepts: concept ? [concept] : [],
      idempotency_key: `review-note-${sourceId}`,
    })
    await router.push({ name: 'Notes', query: { note_id: note.id } })
  } catch (exception) {
    console.error('复习笔记创建失败', exception)
  } finally {
    noteBusyId.value = ''
  }
}
</script>

<template>
  <div class="review-page">
    <AggregationStatus class="review-feedback" />
    <ReviewScheduleBoard :note-busy-id="noteBusyId" @note="openReviewNote">
      <template #tools>
        <ReviewToolsPanel :student-id="activeStudentId" />
      </template>
    </ReviewScheduleBoard>
  </div>
</template>

<style scoped>
.review-page { width: 100%; }
.review-feedback { width: min(100%, 1240px); margin: 0 auto 16px; }
</style>
