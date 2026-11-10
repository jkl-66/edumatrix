<script setup>
import { quizStartQuestion, quizStudySession } from '../utils/quizStudySession.js'
import { userMessage } from '../services/errorTranslator.js'
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertCircle, Check, CheckCircle2, ChevronLeft, ChevronRight, Circle, MessageSquareText,
  FileQuestion, History, LoaderCircle, RefreshCw, X,
} from '@lucide/vue'
import {
  compareM5ResourceVersions, createM5ResourceVersion, getM5Resource,
  restoreM5ResourceVersion, createQuizPractice,
} from '../api'
import InlineQuizCard from '../components/InlineQuizCard.vue'
import ResourceHistoryDrawer from '../components/ResourceHistoryDrawer.vue'
import ResourceToolbar from '../components/ResourceToolbar.vue'
import ResourceFloatingQa from '../components/ResourceFloatingQa.vue'

const route = useRoute()
const router = useRouter()
const loading = ref(true)
const error = ref('')
const detail = ref(null)
const selectedVersionId = ref('')
const activeQuestionId = ref('')
const historyOpen = ref(false)
const historyError = ref('')
const comparingId = ref('')
const restoringId = ref('')
const compareResult = ref(null)
const editing = ref(false)
const saving = ref(false)
const draft = ref(null)
const actionError = ref('')
const notice = ref('')
const qaOpen = ref(false)
const preparingPractice = ref(false)

const resourceId = computed(() => String(route.params.resourceId || ''))
const versions = computed(() => detail.value?.quiz?.versions || [])
const currentVersionId = computed(() => detail.value?.quiz?.current_version_id || '')
const selectedVersion = computed(() => (
  versions.value.find(item => item.id === selectedVersionId.value)
  || versions.value.find(item => item.id === currentVersionId.value)
  || null
))
const projection = computed(() => selectedVersion.value?.projection || null)
const structured = computed(() => projection.value?.structured || null)
const questions = computed(() => projection.value?.questions || [])
const sourceRefs = computed(() => projection.value?.source_refs || [])
const progress = computed(() => projection.value?.progress || {
  question_count: questions.value.length,
  attempted_count: 0,
  correct_count: 0,
  required_count: 0,
  required_correct_count: 0,
  completed: false,
})
const catalog = computed(() => detail.value?.catalog || {})
const isStructured = computed(() => projection.value?.mode === 'structured')
const isHistorical = computed(() => Boolean(selectedVersionId.value && selectedVersionId.value !== currentVersionId.value))
const title = computed(() => structured.value?.title || catalog.value?.title || '测验题资源')
const versionLabel = computed(() => selectedVersion.value ? `v${selectedVersion.value.number}` : '版本未记录')
const activeIndex = computed(() => {
  const index = questions.value.findIndex(item => item.id === activeQuestionId.value)
  return index >= 0 ? index : 0
})
const activeQuestion = computed(() => questions.value[activeIndex.value] || null)
const studySession = computed(() => quizStudySession(
  structured.value?.studySessions || [], questions.value, activeIndex.value,
))
const historyItems = computed(() => detail.value?.history?.items || [])
const qaSourceRefIds = computed(() => sourceRefs.value
  .map(item => item.id || item.source_ref_id)
  .filter(Boolean))

function message(exception, fallback) {
  return userMessage(exception, fallback)
}

function clone(value) {
  return JSON.parse(JSON.stringify(value))
}

function selectInitialQuestion(preferredId = '') {
  if (!questions.value.length) {
    activeQuestionId.value = ''
    return
  }
  const requested = preferredId || String(route.query.question_version_id || '')
  activeQuestionId.value = quizStartQuestion(questions.value, requested)?.id || ''
}

async function loadResource({ preserveVersion = false, preserveQuestion = false } = {}) {
  const previousQuestionId = preserveQuestion ? activeQuestionId.value : ''
  loading.value = true
  error.value = ''
  try {
    const payload = await getM5Resource(resourceId.value)
    if (payload?.catalog?.type !== 'quiz') throw new Error('当前资源不是测验题资源。')
    detail.value = payload
    const keepVersion = preserveVersion && versions.value.some(item => item.id === selectedVersionId.value)
    if (!keepVersion) {
      const requestedVersion = String(route.query.resource_version_id || '')
      selectedVersionId.value = versions.value.some(item => item.id === requestedVersion)
        ? requestedVersion : payload.quiz?.current_version_id || ''
    }
    await nextTick()
    selectInitialQuestion(previousQuestionId)
  } catch (exception) {
    error.value = message(exception, '测验题资源加载失败，请稍后重试。')
  } finally {
    loading.value = false
  }
}

function questionCorrect(question) {
  return (question?.attempts || []).some(item => item.correct === true)
}

function questionAttempted(question) {
  return Boolean(question?.attempts?.length)
}

function formatAttemptTime(value) {
  if (!value) return '时间未记录'
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  }).format(new Date(value))
}

function selectQuestion(question) {
  if (!question) return
  activeQuestionId.value = question.id
  router.replace({ query: { ...route.query, question_version_id: question.id } })
}

function moveQuestion(delta) {
  const target = questions.value[activeIndex.value + delta]
  if (target) selectQuestion(target)
}

async function handleSubmitted(attempt) {
  notice.value = '' // The question already shows the saved result and feedback.
  await loadResource({ preserveVersion: true, preserveQuestion: true })
}

async function startNewPractice() {
  if (preparingPractice.value || !selectedVersion.value) return
  preparingPractice.value = true
  actionError.value = ''
  try {
    const job = await createQuizPractice({ resource_id: resourceId.value, version_id: selectedVersion.value.id })
    // The saved job has its own progress/recovery page; leaving this quiz must
    // not abort generation or replace the learner's previous answers.
    await router.push({ path: `/workspace/resources/bundles/${job.job_id}`, query: { course_id: job.course_id } })
  } catch (exception) {
    actionError.value = message(exception, '新练习暂时无法准备，请稍后再试。')
  } finally {
    preparingPractice.value = false
  }
}

function openFollowUp(payload) {
  const answer = payload.attempt?.answer?.choice || '未记录'
  const result = payload.attempt?.correct ? '回答正确' : '回答错误'
  router.push({
    path: '/learn',
    query: {
      course_id: catalog.value.course?.id || catalog.value.course_id || undefined,
      quiz_resource_id: resourceId.value,
      question_version_id: payload.question?.id,
      attempt_id: payload.attempt?.id,
      quiz_follow_up: `请结合当前课程来源继续讲解这道题：${payload.question?.prompt}\n我的答案：${answer}（${result}）\n我的追问：${payload.text}`,
      tab: 'chat',
    },
  })
}

function openSource(sourceId) {
  const source = sourceRefs.value.find(item => (item.id || item.source_ref_id) === sourceId) || sourceRefs.value[0]
  if (!source) return
  const documentId = source.source_document_id || source.document_id
  const returnTo = router.resolve({
    path: route.path,
    query: { ...route.query, resource_version_id: selectedVersionId.value, question_version_id: activeQuestionId.value },
  }).fullPath
  const query = {
    course_id: catalog.value.course?.id || catalog.value.course_id,
    source_ref_id: source.id || source.source_ref_id,
    return_to: returnTo,
  }
  if (documentId) router.push({ path: `/knowledge/documents/${encodeURIComponent(documentId)}`, query })
  else router.push({ path: '/knowledge', query })
}

function startEditing() {
  if (!isStructured.value || !selectedVersion.value) return
  draft.value = clone(structured.value)
  editing.value = true
  actionError.value = ''
  notice.value = ''
}

function cancelEditing() {
  editing.value = false
  draft.value = null
  actionError.value = ''
}

async function saveVersion() {
  if (!editing.value || saving.value || !selectedVersion.value) return
  saving.value = true
  actionError.value = ''
  try {
    const payload = await createM5ResourceVersion(resourceId.value, {
      expected_lock_version: detail.value.lock_version,
      source_version_id: selectedVersion.value.id,
      content: JSON.stringify(draft.value),
      content_format: 'json',
    })
    detail.value = payload
    selectedVersionId.value = payload.quiz?.current_version_id || payload.current_version_id || ''
    editing.value = false
    draft.value = null
    notice.value = '资源说明已保存为新版本，题目身份和历史作答均未改变。'
    await nextTick()
    selectInitialQuestion(activeQuestionId.value)
  } catch (exception) {
    actionError.value = exception?.detail?.code === 'resource_version_conflict'
      ? '资源已在别处更新。当前草稿仍保留，请重新加载后再次保存。'
      : message(exception, '保存失败，草稿已保留。')
  } finally {
    saving.value = false
  }
}

function openHistory() {
  historyError.value = ''
  compareResult.value = null
  historyOpen.value = true
}

function closeHistory() {
  historyOpen.value = false
  historyError.value = ''
  compareResult.value = null
}

function selectHistoryVersion(versionId) {
  if (editing.value) return
  selectedVersionId.value = versionId
  closeHistory()
  nextTick(() => selectInitialQuestion())
}

async function compareHistory(versionId) {
  if (comparingId.value) return
  const left = versions.value.find(item => item.id === versionId)
  const right = versions.value.find(item => item.id === currentVersionId.value)
  if (!left || !right) return
  comparingId.value = versionId
  historyError.value = ''
  try {
    compareResult.value = await compareM5ResourceVersions(resourceId.value, left.number, right.number)
  } catch (exception) {
    historyError.value = message(exception, '版本比较失败，请稍后重试。')
  } finally {
    comparingId.value = ''
  }
}

async function restoreHistory(versionId) {
  if (editing.value || restoringId.value || versionId === currentVersionId.value) return
  restoringId.value = versionId
  historyError.value = ''
  try {
    detail.value = await restoreM5ResourceVersion(resourceId.value, {
      expected_lock_version: detail.value.lock_version,
      version_id: versionId,
    })
    selectedVersionId.value = detail.value.quiz?.current_version_id || detail.value.current_version_id || ''
    selectInitialQuestion(activeQuestionId.value)
    notice.value = '历史版本已恢复为新的当前版本，旧版本和作答记录仍然保留。'
    closeHistory()
  } catch (exception) {
    historyError.value = message(exception, '恢复失败，当前版本没有改变。')
  } finally {
    restoringId.value = ''
  }
}

watch(selectedVersionId, () => {
  if (!editing.value) selectInitialQuestion(activeQuestionId.value)
})

onMounted(() => loadResource())
</script>

<template>
  <main class="quiz-workspace" data-testid="quiz-resource-workspace">
    <ResourceToolbar
      :title="title"
      type-label=""
      version-label=""
      :history-count="historyItems.length"
      :can-edit="isStructured && Boolean(selectedVersion)"
      :editing="editing"
      :saving="saving"
      :loading="loading"
      :history-disabled="!historyItems.length || editing"
      edit-label="编辑资源说明"
      @back="router.push({ name: 'WorkspaceResources' })"
      @history="openHistory"
      @edit="startEditing"
      @save="saveVersion"
      @cancel="cancelEditing"
      @reload="loadResource({ preserveVersion: true, preserveQuestion: true })"
    />

    <div v-if="loading" class="workspace-state" aria-live="polite">
      <LoaderCircle :size="27" class="spin" />
      <strong>正在恢复测验题</strong>
    </div>

    <div v-else-if="error" class="workspace-state workspace-state--error" role="alert">
      <AlertCircle :size="27" />
      <strong>暂时无法打开测验题</strong>
      <span>{{ userMessage(error) }}</span>
      <button type="button" @click="loadResource()"><RefreshCw :size="17" />重新加载</button>
    </div>

    <template v-else-if="detail && projection">
      <div v-if="actionError || notice" class="status-line" :class="{ 'status-line--error': actionError }" role="status">
        <AlertCircle v-if="actionError" :size="17" />
        <Check v-else :size="17" />
        <span>{{ userMessage(actionError || notice) }}</span>
        <button type="button" title="关闭提示" @click="actionError = ''; notice = ''"><X :size="16" /></button>
      </div>

      <section v-if="editing" class="metadata-editor" aria-label="编辑测验资源说明">
        <label>资源标题<input v-model="draft.title" maxlength="256" /></label>
        <label>资源摘要<textarea v-model="draft.summary" rows="3" maxlength="4000" /></label>
        <label>学习目标<textarea v-model="draft.adaptation.learningGoal" rows="3" maxlength="2000" /></label>
        <label>画像适配说明<textarea v-model="draft.adaptation.profileSummary" rows="3" maxlength="4000" /></label>
        <p>题目版本、顺序、必做标记和课程来源保持不变；保存只会创建新的资源说明版本。</p>
      </section>

      <section v-if="projection.mode !== 'structured'" class="workspace-state workspace-state--error" role="alert">
        <AlertCircle :size="27" />
        <strong>{{ projection.mode === 'legacy_readonly' ? '这是旧版只读测验' : '当前测验结构不完整' }}</strong>
        <span>{{ projection.warnings?.[0] || projection.error?.message || '请在版本历史中选择可判分的结构化版本。' }}</span>
        <button type="button" @click="openHistory"><History :size="17" />查看版本历史</button>
      </section>

      <template v-else>
        <section class="quiz-summary" aria-label="测验说明与完成条件">
          <div class="progress-summary" :class="{ complete: progress.completed }">
            <strong>{{ progress.required_correct_count }}/{{ progress.required_count }}</strong>
            <span>{{ progress.completed ? '练习完成' : '必做题已答对' }}</span>
          </div>
          <button v-if="progress.attempted_count" type="button" class="quiz-qa-button" :disabled="preparingPractice || editing || Boolean(projection.learning_unavailable_reason)" :title="projection.learning_unavailable_reason || undefined" @click="startNewPractice">
            <LoaderCircle v-if="preparingPractice" :size="16" class="spin" /><RefreshCw v-else :size="16" />再练一组
          </button>
          <button type="button" class="quiz-qa-button" @click="qaOpen = true"><MessageSquareText :size="16" />资源内提问</button>
        </section>

        <div v-if="versions.length > 1" class="workspace-version-row">
          <label>
            <History :size="16" /><span>资源版本</span>
            <select v-model="selectedVersionId" :disabled="editing" aria-label="测验资源版本">
              <option v-for="version in [...versions].reverse()" :key="version.id" :value="version.id">
                v{{ version.number }}{{ version.id === currentVersionId ? ' · 当前' : ' · 历史' }}
              </option>
            </select>
          </label>
          <span v-if="isHistorical">正在只读查看历史版本；恢复或编辑都会另存新版本。</span>
        </div>

        <section class="quiz-layout">
          <aside class="question-rail" aria-label="题目列表">
            <header><FileQuestion :size="18" /><strong>题目</strong></header>
            <button
              v-for="(question, index) in questions"
              :key="question.id"
              type="button"
              :class="{ active: question.id === activeQuestion?.id }"
              :aria-label="`第 ${index + 1} 题，${questionCorrect(question) ? '已答对' : questionAttempted(question) ? '可再次作答' : '未作答'}`"
              :aria-current="question.id === activeQuestion?.id ? 'step' : undefined"
              @click="selectQuestion(question)"
            >
              <CheckCircle2 v-if="questionCorrect(question)" :size="18" />
              <Circle v-else :size="18" />
              <span><strong>第 {{ index + 1 }} 题</strong><small v-if="questionAttempted(question) && !questionCorrect(question)">可再次作答</small></span>
              <em v-if="!question.required">选做</em>
            </button>
          </aside>

          <div class="question-stage">
            <template v-if="activeQuestion">
              <p v-if="studySession" class="study-session">
                第 {{ studySession.startQuestion }}–{{ studySession.endQuestion }} 题 · 约 {{ studySession.estimatedMinutes }} 分钟
              </p>
              <InlineQuizCard
                :question="activeQuestion"
                :resource-id="resourceId"
                :resource-version-id="selectedVersionId"
                :initial-attempt="activeQuestion.latest_attempt"
                :position="activeIndex + 1"
                :total="questions.length"
                :source-refs="sourceRefs"
                @submitted="handleSubmitted"
                @follow-up="openFollowUp"
                @open-source="openSource"
              />
              <p v-if="studySession?.reachedEnd && studySession.attempted && studySession.nextQuestion" class="session-pause" role="status">
                这段已作答，可以休息了。下次从第 {{ studySession.nextQuestion }} 题继续。
              </p>
              <section v-if="activeQuestion.attempts?.length" class="attempt-history" aria-label="本题作答历史">
                <header><strong>本题作答历史</strong><span>{{ activeQuestion.attempts.length }} 次提交</span></header>
                <ol>
                  <li v-for="(attempt, index) in activeQuestion.attempts" :key="attempt.id">
                    <span>第 {{ activeQuestion.attempts.length - index }} 次</span>
                    <strong>{{ attempt.practice_kind === 'correction' && attempt.correct ? '已订正' : attempt.correct ? '回答正确' : '回答错误' }}</strong>
                    <span>选择 {{ attempt.answer?.choice || '未记录' }}</span>
                    <time>{{ formatAttemptTime(attempt.submitted_at) }}</time>
                  </li>
                </ol>
              </section>
            </template>
            <div v-else class="workspace-state"><FileQuestion :size="26" /><strong>当前版本没有可显示的题目</strong><span>请查看版本历史或重新生成资源。</span></div>
            <nav class="question-navigation" aria-label="切换题目">
              <button type="button" :disabled="activeIndex <= 0" @click="moveQuestion(-1)"><ChevronLeft :size="17" />上一题</button>
              <span>{{ activeIndex + 1 }} / {{ questions.length }}</span>
              <button type="button" :disabled="activeIndex >= questions.length - 1" @click="moveQuestion(1)">下一题<ChevronRight :size="17" /></button>
            </nav>
          </div>
        </section>
      </template>
    </template>

    <ResourceHistoryDrawer
      :open="historyOpen"
      title="测验题资源版本历史"
      :items="historyItems"
      :current-version-id="currentVersionId"
      :selected-version-id="selectedVersionId"
      :restoring-id="restoringId"
      :comparing-id="comparingId"
      :error="historyError"
      :compare-result="compareResult"
      :compare-disabled="Boolean(comparingId)"
      :restore-disabled="editing || saving"
      @close="closeHistory"
      @select="selectHistoryVersion"
      @compare="compareHistory"
      @restore="restoreHistory"
      @compare-close="compareResult = null"
    />

    <ResourceFloatingQa
      :open="qaOpen"
      :course-id="catalog.course?.id || catalog.course_id || ''"
      :knowledge-point-id="catalog.knowledge_point?.id || structured?.knowledgePoint?.id || ''"
      :resource-id="resourceId"
      :resource-version-id="selectedVersionId"
      :resource-title="title"
      :source-ref-ids="qaSourceRefIds"
      @close="qaOpen = false"
    />
  </main>
</template>

<style scoped>
.quiz-workspace { min-width: 0; padding: 8px 0; container-type: inline-size; background: transparent; color: var(--color-text); font-family: var(--font-sans); }
.workspace-state { display: grid; min-height: 430px; place-content: center; justify-items: center; gap: 9px; border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-surface); color: var(--color-text-muted); text-align: center; }
.workspace-state strong { color: var(--color-text); font-size: 17px; }
.workspace-state span { max-width: 46ch; font-size: 14px; line-height: 1.6; }
.workspace-state button { display: inline-flex; min-height: 38px; align-items: center; gap: 7px; border: 1px solid var(--color-text); border-radius: 8px; padding: 0 12px; background: var(--color-text); color: #fff; font-size: 14px; cursor: pointer; }
.workspace-state--error { color: var(--color-danger); }
.status-line { display: flex; min-height: 42px; align-items: center; gap: 8px; margin-top: 10px; border: 1px solid var(--color-border-strong); border-radius: 8px; padding: 0 11px; background: var(--color-surface); color: var(--color-text-secondary); font-size: 14px; }
.status-line--error { border-color: #d8aaa5; background: var(--color-danger-soft); color: var(--color-danger); }
.status-line span { flex: 1; }
.status-line button { display: grid; width: 30px; height: 30px; place-items: center; border: 0; background: transparent; color: currentColor; cursor: pointer; }
.metadata-editor { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 12px; border: 1px solid var(--color-border-strong); border-radius: 8px; padding: 16px; background: var(--color-surface); }
.metadata-editor label { display: grid; gap: 6px; color: var(--color-text-secondary); font-size: 14px; }
.metadata-editor input, .metadata-editor textarea { width: 100%; border: 1px solid var(--color-border-strong); border-radius: 8px; padding: 9px 10px; color: var(--color-text); font-family: inherit; font-size: 14px; line-height: 1.55; }
.metadata-editor p { grid-column: 1 / -1; margin: 0; color: var(--color-text-muted); font-size: 14px; line-height: 1.6; }
 .quiz-summary { display: flex; align-items: flex-start; gap: 22px; margin: 12px 0; padding: 12px 2px; }
.study-session { margin: 0 0 16px; color: var(--color-text-secondary); font-size: 15px; }
.session-pause { margin: 18px 0; color: var(--color-text); line-height: 1.7; }
.quiz-qa-button { display: inline-flex; min-height: 36px; flex-shrink: 0; align-items: center; gap: 7px; padding: 0 10px; border: 0; background: transparent; color: var(--color-accent); white-space: nowrap; cursor: pointer; }
.progress-summary { display: flex; min-height: 36px; align-items: center; gap: 8px; color: var(--color-text-secondary); font-size: 15px; }
.progress-summary strong { font-size: 18px; font-variant-numeric: tabular-nums; color: var(--color-text); }
.workspace-version-row { display: flex; min-height: 50px; align-items: center; justify-content: space-between; gap: 12px; margin-top: 10px; color: var(--color-text-muted); font-size: 14px; }
.workspace-version-row label { display: inline-flex; align-items: center; gap: 7px; }
.workspace-version-row select { min-height: 36px; border: 1px solid var(--color-border-strong); border-radius: 8px; padding: 0 28px 0 9px; background: var(--color-surface); color: var(--color-text); font-size: 14px; }
.quiz-layout { display: grid; min-height: 570px; grid-template-columns: 154px minmax(0, 1fr); border: 0; border-radius: 8px; background: var(--color-surface); }
.question-rail { border-right: 1px solid var(--color-border); background: transparent; }
.question-rail header { display: grid; min-height: 54px; grid-template-columns: 20px minmax(0, 1fr); align-items: center; gap: 7px; border-bottom: 1px solid var(--color-border); padding: 0 12px; }
.question-rail header strong { font-size: 15px; }
.question-rail header span { grid-column: 1 / -1; margin-top: -10px; padding-left: 27px; color: var(--color-text-muted); font-size: 14px; }
.question-rail > button { display: grid; width: 100%; min-height: 62px; grid-template-columns: 20px minmax(0, 1fr) auto; align-items: center; gap: 9px; border: 0; border-bottom: 0; padding: 8px 11px; background: transparent; color: var(--color-text-secondary); text-align: left; cursor: pointer; }
.question-rail > button.active { background: var(--color-accent-soft); box-shadow: inset 2px 0 var(--color-accent); color: var(--color-text); }
.question-rail > button span { min-width: 0; }
.question-rail > button strong, .question-rail > button small { display: block; }
.question-rail > button strong { font-size: 14px; }
.question-rail > button small { margin-top: 3px; color: var(--color-text-muted); font-size: 14px; }
.question-rail > button em { border: 1px solid var(--color-border-strong); border-radius: 5px; padding: 2px 5px; color: var(--color-text-secondary); font-size: 14px; font-style: normal; }
.question-stage { min-width: 0; padding: 24px clamp(18px, 3vw, 42px) 18px; }
.question-navigation { display: flex; min-height: 52px; align-items: center; justify-content: space-between; gap: 12px; }
.question-navigation button { display: inline-flex; min-height: 36px; align-items: center; gap: 5px; border: 1px solid var(--color-border-strong); border-radius: 8px; padding: 0 10px; background: var(--color-surface); color: var(--color-text); font-size: 14px; cursor: pointer; }
.question-navigation button:disabled { cursor: default; opacity: .45; }
.question-navigation span { color: var(--color-text-muted); font-size: 14px; font-variant-numeric: tabular-nums; }
.attempt-history { margin-top: 12px; border: 1px solid var(--color-border); border-radius: 8px; background: var(--color-surface); }
.attempt-history header { display: flex; min-height: 43px; align-items: center; justify-content: space-between; gap: 12px; border-bottom: 1px solid #e7ebec; padding: 0 13px; }
.attempt-history header strong { font-size: 15px; }
.attempt-history header span { color: var(--color-text-muted); font-size: 14px; }
.attempt-history ol { margin: 0; padding: 0; list-style: none; }
.attempt-history li { display: grid; min-height: 42px; grid-template-columns: 72px 92px minmax(100px, 1fr) auto; align-items: center; gap: 10px; border-bottom: 1px solid var(--color-surface-subtle); padding: 0 13px; color: var(--color-text-secondary); font-size: 14px; }
.attempt-history li:last-child { border-bottom: 0; }
.attempt-history li strong { color: var(--color-text); font-size: 14px; }
.attempt-history time { color: var(--color-text-muted); font-size: 14px; }
.spin { animation: spin .8s linear infinite; }
button:focus-visible, select:focus-visible, input:focus-visible, textarea:focus-visible { outline: 2px solid var(--color-text); outline-offset: 2px; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1120px) {
  .quiz-workspace { padding: 14px; }
  .quiz-layout { grid-template-columns: 132px minmax(0, 1fr); }
  .question-stage { padding-right: 20px; padding-left: 20px; }
  .metadata-editor { grid-template-columns: 1fr; }
  .metadata-editor p { grid-column: 1; }
}
@container (max-width: 760px) {
  .quiz-summary { flex-wrap: wrap; gap: 12px; }
  .quiz-objectives { flex-basis: 100%; }
  .quiz-layout { grid-template-columns: minmax(0, 1fr); }
  .question-rail { display: flex; flex-wrap: wrap; gap: 6px; padding: 12px; border-right: 0; }
  .question-rail header { display: none; }
  .question-rail > button { width: auto; min-height: 40px; grid-template-columns: 18px auto; border-radius: 6px; }
  .question-stage { padding: 12px; }
  .attempt-history li { grid-template-columns: auto auto; padding-block: 8px; }
  :deep(.resource-toolbar) { flex-wrap: wrap; }
  :deep(.toolbar-actions) { flex-basis: 100%; justify-content: flex-end; }
}
</style>
