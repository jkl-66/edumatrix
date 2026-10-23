<script setup>
import { computed } from 'vue'
import ReviewScheduleBoard from '../components/ReviewScheduleBoard.vue'
import ReviewToolsPanel from '../components/ReviewToolsPanel.vue'

const props = defineProps({ studentId: String })
const activeStudentId = computed(() => props.studentId || localStorage.getItem('edumatrix_student_id') || localStorage.getItem('edumatrix_username') || '')
</script>

<template>
  <div class="revision-page">
    <ReviewScheduleBoard>
      <template #tools>
        <ReviewToolsPanel :student-id="activeStudentId" />
      </template>
    </ReviewScheduleBoard>
  </div>
</template>

<style scoped>
.revision-page { width: 100%; }
</style>
