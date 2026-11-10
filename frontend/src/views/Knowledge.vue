<script setup>
import { userMessage } from '../services/errorTranslator.js'
import { defineAsyncComponent, ref } from 'vue'
import { useRouter } from 'vue-router'
import KnowledgeCourseShelf from '../components/KnowledgeCourseShelf.vue'
import { getCanonicalCourseSource } from '../api/knowledge'

const router = useRouter()
const sourceError = ref('')
const sharingOpen = ref(false)
const CourseSharingWorkspace = defineAsyncComponent(() => import('./CourseSharingWorkspace.vue'))

async function resolveCanonicalSourceDeepLink({
  courseId,
  sourceDocumentId,
  chapterId,
  sourceRefId,
  evidenceId,
  matchCharStart,
  matchText,
}) {
  if (!courseId || !sourceDocumentId) return
  sourceError.value = ''
  try {
    const source = await getCanonicalCourseSource(sourceDocumentId)
    const canonicalDocumentId = source?.source_document_id || source?.id || sourceDocumentId
    const canonicalCourseId = source?.course_id || courseId
    // Opening a whole file resumes reading; chapter/search links keep their target.
    const canonicalChapterId = chapterId
    const canonicalSourceRefId = sourceRefId
    await router.push({
      path: `/knowledge/documents/${encodeURIComponent(canonicalDocumentId)}`,
      query: {
        course_id: canonicalCourseId,
        chapter_id: canonicalChapterId || undefined,
        canonical_source_id: canonicalDocumentId,
        source_ref_id: canonicalSourceRefId || undefined,
        evidence_id: evidenceId || undefined,
        char_start: Number.isInteger(matchCharStart) && matchCharStart >= 0 ? matchCharStart : undefined,
        search: matchText || undefined,
      },
    })
  } catch (error) {
    sourceError.value = error?.response?.data?.detail || '该课程来源暂不可访问。'
  }
}

async function openCourseSource({ courseId, sourceDocumentId, chapterId }) {
  await resolveCanonicalSourceDeepLink({ courseId, sourceDocumentId, chapterId })
}

async function openCourseSearchResult({ courseId, item }) {
  const sourceDocumentId = item?.source_document_id
  if (!sourceDocumentId || !item?.source_ref_id) {
    sourceError.value = '该结果缺少可定位的课程来源。'
    return
  }
  await resolveCanonicalSourceDeepLink({
    courseId,
    sourceDocumentId,
    sourceRefId: item.source_ref_id,
    evidenceId: item.evidence_id,
    chapterId: item.chapter_id,
    matchCharStart: item.match_char_start,
    matchText: item.match_text,
  })
}
</script>

<template>
  <div class="knowledge-page mx-auto">
    <details v-if="!$route.params.courseId" class="course-sharing" @toggle="sharingOpen = $event.currentTarget.open">
      <summary>接收共享课程与查看更新</summary>
      <CourseSharingWorkspace v-if="sharingOpen" />
    </details>
    <KnowledgeCourseShelf
      @open-source="openCourseSource"
      @open-search-result="openCourseSearchResult"
    />
    <p v-if="sourceError" class="source-error" role="alert">{{ userMessage(sourceError) }}</p>
  </div>
</template>

<style scoped>
.course-sharing { margin-bottom: 16px; padding: 16px; background: var(--color-surface, #fff); border: 1px solid var(--color-border, var(--color-border)); border-radius: 10px; }
.course-sharing summary { cursor: pointer; font-weight: 600; }
.knowledge-page {
  max-width: 1480px;
  padding-top: 20px;
  padding-bottom: 36px;
}

.source-error {
  margin: 16px 0 0;
  padding: 10px 12px;
  color: var(--color-danger);
  border: 1px solid #efcaca;
  background: #fff7f7;
  font-size: 14px;
  line-height: 1.5;
}
</style>
