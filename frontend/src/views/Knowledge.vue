<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import KnowledgeCourseShelf from '../components/KnowledgeCourseShelf.vue'
import { getCanonicalCourseSource } from '../api/knowledge'

const router = useRouter()
const sourceError = ref('')

async function resolveCanonicalSourceDeepLink({
  courseId,
  sourceDocumentId,
  chapterId,
  sourceRefId,
  evidenceId,
}) {
  if (!courseId || !sourceDocumentId) return
  sourceError.value = ''
  try {
    const source = await getCanonicalCourseSource(sourceDocumentId)
    const canonicalDocumentId = source?.source_document_id || source?.id || sourceDocumentId
    const canonicalCourseId = source?.course_id || courseId
    const canonicalChapterId = source?.source_chapter_id || chapterId
    const canonicalSourceRefId = sourceRefId || source?.source_ref_id
    await router.push({
      path: `/knowledge/documents/${encodeURIComponent(canonicalDocumentId)}`,
      query: {
        course_id: canonicalCourseId,
        chapter_id: canonicalChapterId || undefined,
        canonical_source_id: canonicalDocumentId,
        source_ref_id: canonicalSourceRefId || undefined,
        evidence_id: evidenceId || undefined,
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
  })
}
</script>

<template>
  <div class="knowledge-page mx-auto max-w-6xl text-slate-800">
    <KnowledgeCourseShelf
      @open-source="openCourseSource"
      @open-search-result="openCourseSearchResult"
    />
    <p v-if="sourceError" class="source-error" role="alert">{{ sourceError }}</p>
  </div>
</template>

<style scoped>
.knowledge-page {
  padding-bottom: 48px;
}

.source-error {
  margin: 16px 0 0;
  padding: 10px 12px;
  color: #8f2f2f;
  border: 1px solid #efcaca;
  background: #fff7f7;
  font-size: 14px;
  line-height: 1.5;
}
</style>
