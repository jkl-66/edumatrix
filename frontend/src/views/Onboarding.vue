<script setup>
import { computed, nextTick, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  AlertCircle,
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  Edit3,
  FileText,
  LoaderCircle,
  MessageSquareText,
  Paperclip,
  RotateCcw,
  Send,
  Sparkles,
  Trash2,
} from '@lucide/vue'
import {
  confirmOnboardingEvidence,
  confirmOnboardingTurn,
  discardOnboardingEvidence,
  finalizeOnboardingProfile,
  getOnboardingSession,
  submitOnboardingTurn,
  updateStudentProfile,
  uploadOnboardingEvidence,
} from '../api'
import ProfileSummaryPanel from '../components/ProfileSummaryPanel.vue'

const router = useRouter()
const loading = ref(true)
const sending = ref(false)
const confirming = ref(false)
const uploading = ref(false)
const evidenceAction = ref('')
const error = ref('')
const answer = ref('')
const session = ref(null)
const conversation = ref(null)
const evidenceInput = ref(null)
const evidenceType = ref('transcript')
const candidateValues = reactive({})
const evidenceValues = reactive({})

const legacyForm = reactive({
  major: '',
  goal: '',
  foundation: '',
  difficulty: '',
  preference: '',
})

const pendingStatuses = new Set([
  'awaiting_confirmation', 'conflict', 'extraction_failed', 'projection_failed', 'projecting',
])
const candidateTurn = computed(() => [...(session.value?.turns || [])].reverse().find((turn) => pendingStatuses.has(turn.status)))
const candidateFields = computed(() => candidateTurn.value?.extractedCandidates?.fields || [])
const completed = computed(() => session.value?.progress?.completed || 0)
const isConfirmed = computed(() => session.value?.status === 'confirmed')
const isFinalized = computed(() => Boolean(session.value?.finalized))
const personalEvidence = computed(() => session.value?.personalEvidence || [])
const suggestedPrompts = computed(() => session.value?.suggestedPrompts || [])
const pendingEvidence = computed(() => personalEvidence.value.find((item) => item.status === 'parsed'))
const failedEvidence = computed(() => personalEvidence.value.filter((item) => item.status === 'parse_failed'))
const canSend = computed(() => answer.value.trim().length > 0 && !sending.value && !candidateTurn.value && !isConfirmed.value)
const statusLabel = computed(() => {
  if (loading.value) return '正在恢复上次进度'
  if (uploading.value) return '正在读取个人资料'
  if (sending.value) return '正在整理本轮回答'
  if (confirming.value) return '正在保存已确认画像'
  if (candidateTurn.value?.status === 'projection_failed') return '回答已保存，画像写入待重试'
  if (candidateTurn.value?.status === 'extraction_failed') return '自动整理失败，请手动确认'
  if (candidateTurn.value?.status === 'conflict') return '发现与已确认信息不同的内容'
  if (candidateTurn.value) return '请确认本轮画像字段'
  if (isFinalized.value) return '初始画像已完成'
  if (isConfirmed.value) return pendingEvidence.value ? '请确认资料抽取字段' : '等待最终确认'
  return '等待你的回答'
})

function messageOf(requestError) {
  const detail = requestError?.response?.data?.detail || requestError?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || requestError?.message || '请求失败，请稍后重试。'
}

function makeTurnId() {
  return globalThis.crypto?.randomUUID?.() || `onboard-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function resetCandidate() {
  Object.keys(candidateValues).forEach((key) => delete candidateValues[key])
  for (const field of candidateFields.value) {
    const value = field.value
    if (field.key === 'misconception_patterns' && value && typeof value === 'object' && !Array.isArray(value)) {
      candidateValues[field.key] = Object.entries(value).map(([topic, score]) => ({ topic, score }))
    } else {
      candidateValues[field.key] = Array.isArray(value) ? value.join('\n') : value ?? ''
    }
  }
}

function normalizedCandidateFields() {
  return Object.fromEntries(candidateFields.value.map((field) => {
    if (field.key === 'misconception_patterns' && Array.isArray(candidateValues[field.key])) {
      return [field.key, Object.fromEntries(candidateValues[field.key]
        .filter((item) => item.topic.trim())
        .map((item) => [item.topic.trim(), item.score]))]
    }
    const raw = String(candidateValues[field.key] ?? '').trim()
    const value = field.kind === 'list'
      ? raw.split(/\n|；|;/).map((item) => item.trim()).filter(Boolean)
      : raw
    return [field.key, value]
  }))
}

function resetEvidenceValues() {
  Object.keys(evidenceValues).forEach((key) => delete evidenceValues[key])
  for (const field of pendingEvidence.value?.candidates || []) {
    evidenceValues[field.key] = Array.isArray(field.value) ? field.value.join('\n') : field.value ?? ''
  }
}

function normalizedEvidenceFields() {
  return Object.fromEntries((pendingEvidence.value?.candidates || []).map((field) => {
    const raw = String(evidenceValues[field.key] ?? '').trim()
    const value = field.kind === 'list'
      ? raw.split(/\n|；|;/).map((item) => item.trim()).filter(Boolean)
      : raw
    return [field.key, value]
  }))
}

function scrollToLatest() {
  nextTick(() => {
    if (conversation.value) conversation.value.scrollTop = conversation.value.scrollHeight
  })
}

function scrollToEvidence() {
  nextTick(() => {
    const editor = conversation.value?.querySelector('[data-testid="onboarding-evidence-editor"]')
    if (editor && conversation.value) {
      const target = editor.getBoundingClientRect().top
        - conversation.value.getBoundingClientRect().top
        + conversation.value.scrollTop
      conversation.value.scrollTop = Math.max(0, target - 16)
    }
    else scrollToLatest()
  })
}

async function loadSession() {
  loading.value = true
  error.value = ''
  try {
    session.value = await getOnboardingSession()
    resetCandidate()
    resetEvidenceValues()
    if (isFinalized.value) {
      localStorage.setItem('edumatrix_onboarded', 'true')
      await router.replace('/')
      return
    }
    scrollToLatest()
  } catch (requestError) {
    error.value = messageOf(requestError)
  } finally {
    loading.value = false
  }
}

async function sendAnswer() {
  if (!canSend.value) return
  const currentAnswer = answer.value.trim()
  const turnId = makeTurnId()
  answer.value = ''
  sending.value = true
  error.value = ''
  const optimisticTurn = {
    turnId,
    questionDimension: session.value.questionDimension,
    userAnswer: currentAnswer,
    status: 'analyzing',
    extractedCandidates: null,
  }
  session.value = {
    ...session.value,
    turns: [...(session.value?.turns || []), optimisticTurn],
  }
  try {
    session.value = await submitOnboardingTurn({
      turn_id: turnId,
      question_dimension: session.value.questionDimension,
      user_answer: currentAnswer,
    })
    resetCandidate()
    scrollToLatest()
  } catch (requestError) {
    answer.value = currentAnswer
    session.value = {
      ...session.value,
      turns: (session.value?.turns || []).map((turn) => (
        turn.turnId === turnId ? { ...turn, status: 'submission_failed' } : turn
      )),
    }
    error.value = messageOf(requestError)
  } finally {
    sending.value = false
  }
}

async function confirmCandidate() {
  if (!candidateTurn.value || confirming.value) return
  confirming.value = true
  error.value = ''
  try {
    session.value = await confirmOnboardingTurn(
      candidateTurn.value.turnId,
      normalizedCandidateFields(),
      candidateTurn.value.status === 'conflict',
    )
    resetCandidate()
    scrollToLatest()
  } catch (requestError) {
    error.value = messageOf(requestError)
  } finally {
    confirming.value = false
  }
}

function chooseEvidenceFile() {
  evidenceInput.value?.click()
}

async function uploadEvidence(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file || uploading.value) return
  uploading.value = true
  error.value = ''
  try {
    session.value = await uploadOnboardingEvidence(evidenceType.value, file)
    resetEvidenceValues()
    if (pendingEvidence.value) scrollToEvidence()
    else scrollToLatest()
  } catch (requestError) {
    error.value = messageOf(requestError)
  } finally {
    uploading.value = false
  }
}

async function confirmEvidence() {
  if (!pendingEvidence.value || evidenceAction.value) return
  evidenceAction.value = pendingEvidence.value.evidenceId
  error.value = ''
  try {
    session.value = await confirmOnboardingEvidence(
      pendingEvidence.value.evidenceId,
      normalizedEvidenceFields(),
    )
    resetEvidenceValues()
  } catch (requestError) {
    error.value = messageOf(requestError)
  } finally {
    evidenceAction.value = ''
  }
}

async function discardEvidence(item) {
  if (!item || evidenceAction.value) return
  evidenceAction.value = item.evidenceId
  error.value = ''
  try {
    session.value = await discardOnboardingEvidence(item.evidenceId)
    resetEvidenceValues()
  } catch (requestError) {
    error.value = messageOf(requestError)
  } finally {
    evidenceAction.value = ''
  }
}

async function finalizeProfile() {
  if (!isConfirmed.value || pendingEvidence.value || confirming.value) return
  confirming.value = true
  error.value = ''
  try {
    session.value = await finalizeOnboardingProfile()
    localStorage.setItem('edumatrix_onboarded', 'true')
  } catch (requestError) {
    error.value = messageOf(requestError)
  } finally {
    confirming.value = false
  }
}

async function finishLegacy() {
  if (!legacyForm.major.trim() || !legacyForm.goal.trim() || !legacyForm.preference.trim()) {
    error.value = '请至少填写专业、目标和学习偏好。'
    return
  }
  confirming.value = true
  error.value = ''
  try {
    const studentId = localStorage.getItem('edumatrix_student_id')
    await updateStudentProfile(studentId, {
      major: legacyForm.major.trim(),
      target_course: session.value?.courseContext?.title || '',
      learning_goals: [legacyForm.goal.trim()],
      learning_preferences: [legacyForm.preference.trim()],
      cognitive_style: legacyForm.preference.trim(),
    })
    localStorage.setItem('edumatrix_onboarded', 'true')
    await router.push('/')
  } catch (requestError) {
    error.value = messageOf(requestError)
  } finally {
    confirming.value = false
  }
}

function enterDiagnostic() {
  if (!isFinalized.value) return
  localStorage.setItem('edumatrix_onboarded', 'true')
  router.push('/workspace/assessment/entry')
}

function useSuggestedPrompt(prompt) {
  if (!prompt || !canSend.value) {
    answer.value = prompt ? `${prompt}：` : answer.value
    return
  }
  answer.value = `${prompt}：`
}

watch(candidateTurn, resetCandidate)
watch(pendingEvidence, resetEvidenceValues)
onMounted(loadSession)
</script>

<template>
  <main class="onboarding-page" data-testid="onboarding-v2">
    <header class="onboarding-header">
      <div class="brand-mark" aria-label="EduMatrix">E</div>
      <div class="header-copy">
        <span>EduMatrix 初始画像</span>
      <strong>{{ session?.courseContext?.title || '尚未选择课程' }}</strong>
      </div>
      <div class="header-status" aria-live="polite">
        <LoaderCircle v-if="loading || sending || confirming" class="spin" :size="16" />
        <CheckCircle2 v-else-if="isFinalized" :size="16" />
        <MessageSquareText v-else :size="16" />
        {{ statusLabel }}
      </div>
    </header>

    <section v-if="session?.featureEnabled !== false" class="onboarding-shell">
      <nav class="dimension-progress" aria-label="画像构建进度" data-testid="onboarding-progress">
        <div class="conversation-progress-copy">
          <span class="eyebrow"><Sparkles :size="14" />边聊边形成你的学习方式</span>
          <strong>{{ completed ? `已经聊到第 ${completed} 段` : '从你最近的经历开始' }}</strong>
          <small>你可以随时补充或改口，不需要按栏目填写</small>
        </div>
        <div class="progress-dots" aria-hidden="true">
          <span v-for="item in session?.dimensions || []" :key="item.key" :class="item.status"></span>
        </div>
        <div class="progress-copy"><strong>{{ completed }}/5</strong><span>段对话</span></div>
      </nav>

      <div class="onboarding-body">
        <section class="conversation-panel" aria-label="自然语言画像对话">
          <div ref="conversation" class="conversation-scroll" data-testid="onboarding-conversation">
            <div v-if="loading" class="stable-state"><LoaderCircle class="spin" :size="20" />正在恢复你的画像进度</div>
            <template v-else>
              <div class="message system-message">
                <span class="message-avatar"><Sparkles :size="16" /></span>
                <div><strong>学习伙伴</strong><p>{{ session?.assistantOpening || '我不会让你按表格填资料。你可以从最近在学什么、为什么想学、遇到什么卡点开始说，我会顺着你的话继续了解你。' }}</p></div>
              </div>

              <template v-for="turn in session?.turns || []" :key="turn.turnId">
                <div class="message system-message compact-message">
                  <span class="message-avatar"><MessageSquareText :size="16" /></span>
                  <div><strong>学习伙伴</strong><p>{{ turn.question || session.question }}</p></div>
                </div>
                <div class="message user-message">
                  <div>
                    <strong>你</strong>
                    <p>{{ turn.userAnswer }}</p>
                    <small v-if="turn.status === 'analyzing'" class="message-status">正在分析你的回答…</small>
                    <small v-else-if="turn.status === 'submission_failed'" class="message-status is-error">本轮未完成，可保留原话后重试</small>
                  </div>
                </div>
                <div v-if="turn.assistantReply" class="message system-message reflection-message">
                  <span class="message-avatar"><Sparkles :size="16" /></span>
                  <div><strong>学习伙伴</strong><p>{{ turn.assistantReply }}</p><small v-if="turn.signalHighlights?.length">{{ turn.signalHighlights[0] }}</small></div>
                </div>
              </template>

              <div v-if="candidateTurn" class="candidate-editor" data-testid="onboarding-candidate-editor">
                <header>
                  <div>
                    <span><Edit3 :size="15" /> 本轮整理结果</span>
                    <strong>{{ candidateTurn.status === 'conflict' ? '请确认是否更新已有信息' : '确认后才会写入画像' }}</strong>
                  </div>
                  <span class="saved-badge"><CheckCircle2 :size="14" />回答已保存</span>
                </header>
                <div v-if="candidateTurn.error" class="candidate-warning"><AlertCircle :size="16" />{{ candidateTurn.error }}</div>
                <div v-if="candidateTurn.extractedCandidates?.understanding" class="candidate-understanding">
                  <div><strong>我先这样理解</strong></div>
                  <p>{{ candidateTurn.extractedCandidates.understanding }}</p>
                </div>
                <div v-if="candidateTurn.extractedCandidates?.uncertainties?.length" class="candidate-uncertainties">
                  <strong>还需要你确认</strong>
                  <ul><li v-for="item in candidateTurn.extractedCandidates.uncertainties" :key="item">{{ item }}</li></ul>
                </div>
                <template v-for="field in candidateFields" :key="field.key">
                  <fieldset v-if="field.key === 'misconception_patterns' && Array.isArray(candidateValues[field.key])" class="candidate-map">
                    <legend>{{ field.label }}</legend>
                    <div v-for="(item, index) in candidateValues[field.key]" :key="index" class="candidate-map-row">
                      <input v-model="item.topic" type="text" :aria-label="`${field.label} ${index + 1}`" />
                      <label>
                        <span>混淆程度 <output>{{ Math.round(item.score * 100) }}%</output></span>
                        <input v-model.number="item.score" type="range" min="0" max="1" step="0.01" :aria-label="`${item.topic}的混淆程度`" />
                      </label>
                    </div>
                  </fieldset>
                  <label v-else>
                    <span>{{ field.label }}</span>
                    <textarea v-if="field.kind === 'list'" v-model="candidateValues[field.key]" rows="2" />
                    <input v-else v-model="candidateValues[field.key]" type="text" />
                  </label>
                </template>
                <button type="button" class="primary-action" :disabled="confirming" @click="confirmCandidate">
                  <LoaderCircle v-if="confirming" class="spin" :size="16" />
                  <Check v-else :size="16" />
                  {{ candidateTurn.status === 'projection_failed' ? '再次保存到画像' : candidateTurn.status === 'conflict' ? '更新为本次回答' : '确认本轮画像' }}
                </button>
              </div>

              <div v-if="pendingEvidence" class="evidence-editor" data-testid="onboarding-evidence-editor">
                <header>
                  <div>
                    <span><FileText :size="15" /> {{ pendingEvidence.evidenceLabel }}抽取结果</span>
                    <strong>只采用你确认过的字段</strong>
                  </div>
                  <button type="button" class="icon-action" title="忽略这份资料" :disabled="Boolean(evidenceAction)" @click="discardEvidence(pendingEvidence)"><Trash2 :size="16" /></button>
                </header>
                <p class="evidence-source">{{ pendingEvidence.filename }} · 文件仅用于本次画像，不会加入课程知识库</p>
                <label v-for="field in pendingEvidence.candidates" :key="field.key">
                  <span>{{ field.label }} <small>置信度 {{ Math.round(field.confidence * 100) }}%</small></span>
                  <div v-if="field.conflict" class="field-conflict">
                    <span><strong>当前值</strong>{{ Array.isArray(field.currentValue) ? field.currentValue.join('；') : field.currentValue }}</span>
                    <small>{{ field.currentSource }} · {{ field.currentSourceRef }}</small>
                    <span><strong>资料值</strong>{{ Array.isArray(field.value) ? field.value.join('；') : field.value }}</span>
                    <small>{{ field.sourceRef }}</small>
                  </div>
                  <textarea v-if="field.kind === 'list'" v-model="evidenceValues[field.key]" rows="2" />
                  <input v-else v-model="evidenceValues[field.key]" type="text" />
                  <small>{{ field.sourceRef }}</small>
                </label>
                <button type="button" class="secondary-action" :disabled="Boolean(evidenceAction)" @click="confirmEvidence">
                  <LoaderCircle v-if="evidenceAction" class="spin" :size="16" />
                  <Check v-else :size="16" />确认资料字段
                </button>
              </div>

              <div v-for="item in failedEvidence" :key="item.evidenceId" class="evidence-failure" data-testid="onboarding-evidence-failure">
                <AlertCircle :size="16" />
                <div><strong>{{ item.filename }} 未形成候选字段</strong><p>{{ item.error }} 对话和入学诊断不受影响。</p></div>
                <button type="button" class="icon-action" title="忽略这份资料" :disabled="Boolean(evidenceAction)" @click="discardEvidence(item)"><Trash2 :size="16" /></button>
              </div>

              <div v-if="!candidateTurn && !isConfirmed" class="message system-message current-question" data-testid="onboarding-current-question">
                <span class="message-avatar"><MessageSquareText :size="16" /></span>
                <div>
                  <strong>{{ completed ? '学习伙伴继续问' : '学习伙伴想先听听你' }}</strong>
                  <p>{{ session.question }}</p>
                </div>
              </div>

              <div v-if="isConfirmed" class="completion-panel" data-testid="onboarding-complete">
                <CheckCircle2 :size="24" />
                <div>
                  <strong>{{ isFinalized ? '初始画像已经建立' : '五轮对话已经完成' }}</strong>
                  <p>{{ isFinalized ? '下一步通过入学诊断把自述与真实作答证据结合，生成第一版学习路径。' : pendingEvidence ? '请先确认或忽略上方资料字段。' : '确认后生成唯一初始画像快照；自述和资料不会直接当作掌握度。' }}</p>
                </div>
                <button v-if="!isFinalized" type="button" class="primary-action" :disabled="Boolean(pendingEvidence) || confirming" @click="finalizeProfile">
                  <LoaderCircle v-if="confirming" class="spin" :size="16" /><Check v-else :size="16" />确认初始画像
                </button>
                <button v-else type="button" class="primary-action" @click="enterDiagnostic">进入入学诊断<ArrowRight :size="16" /></button>
              </div>
            </template>
          </div>

          <div v-if="error" class="error-banner" role="alert"><AlertCircle :size="16" />{{ error }}<button type="button" title="重新加载" @click="loadSession"><RotateCcw :size="15" /></button></div>

          <form class="answer-composer" @submit.prevent="sendAnswer">
            <label for="onboarding-answer">你的回答</label>
            <div class="answer-row">
              <textarea
                id="onboarding-answer"
                v-model="answer"
                :disabled="loading || sending || Boolean(candidateTurn) || isConfirmed"
                rows="2"
                :placeholder="candidateTurn ? '请先确认上方整理结果' : isConfirmed ? '画像已确认' : '用自己的话回答即可，不需要整理格式'"
                @keydown.ctrl.enter="sendAnswer"
              />
              <button type="submit" class="send-action" title="发送回答" :disabled="!canSend"><Send :size="18" /></button>
            </div>
            <div class="composer-tools">
              <div v-if="!candidateTurn && !isConfirmed && suggestedPrompts.length" class="suggested-prompts" aria-label="可以从这里开始">
                <button v-for="prompt in suggestedPrompts" :key="prompt" type="button" @click="useSuggestedPrompt(prompt)">{{ prompt }}</button>
              </div>
              <div class="evidence-type" role="group" aria-label="个人资料类型">
                <button type="button" :class="{ active: evidenceType === 'transcript' }" @click="evidenceType = 'transcript'">成绩单</button>
                <button type="button" :class="{ active: evidenceType === 'timetable' }" @click="evidenceType = 'timetable'">课程表</button>
              </div>
              <button type="button" class="attachment-action" :disabled="uploading || Boolean(pendingEvidence) || isFinalized" @click="chooseEvidenceFile">
                <LoaderCircle v-if="uploading" class="spin" :size="16" /><Paperclip v-else :size="16" />可选个人资料
              </button>
              <input ref="evidenceInput" class="visually-hidden" type="file" accept=".pdf,.docx,.txt,.md" @change="uploadEvidence" />
              <span>不需要上传课程材料，系统直接使用团队预置并已解析的课程知识库。</span>
            </div>
          </form>
        </section>

        <ProfileSummaryPanel onboarding :session="session" />
      </div>
    </section>

    <section v-else class="legacy-onboarding" data-testid="legacy-onboarding">
      <header><BookOpen :size="22" /><div><span>兼容初始化</span><h1>先填写最基本的学习信息</h1></div></header>
      <p>自然语言画像引导当前已关闭。此前保存的对话不会删除，你仍可通过这份简表进入原有学习空间。</p>
      <div class="legacy-grid">
        <label><span>专业方向</span><input v-model="legacyForm.major" /></label>
        <label><span>学习目标</span><input v-model="legacyForm.goal" /></label>
        <label><span>当前基础</span><input v-model="legacyForm.foundation" /></label>
        <label><span>主要困难</span><input v-model="legacyForm.difficulty" /></label>
        <label><span>学习偏好</span><input v-model="legacyForm.preference" /></label>
      </div>
      <div v-if="error" class="error-banner" role="alert"><AlertCircle :size="16" />{{ error }}</div>
      <button type="button" class="primary-action" :disabled="confirming" @click="finishLegacy">进入原有学习空间<ArrowRight :size="16" /></button>
    </section>
  </main>
</template>

<style scoped>
.onboarding-page {
  min-height: 100vh;
  color: var(--color-text);
  background: #f3f6f6;
  font-family: var(--font-sans);
}

.onboarding-header {
  display: flex;
  height: 64px;
  align-items: center;
  gap: 13px;
  padding: 0 28px;
  border-bottom: 1px solid var(--color-border);
  background: #ffffff;
}

.brand-mark {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  color: #ffffff;
  border-radius: 7px;
  background: #06141b;
  font-family: var(--font-display);
  font-size: 19px;
  font-weight: 700;
}

.header-copy {
  display: grid;
  min-width: 0;
  line-height: 1.25;
}

.header-copy span,
.header-status {
  color: var(--color-text-secondary);
  font-size: 14px;
}

.header-copy strong {
  max-width: 520px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 15px;
}

.header-status {
  display: flex;
  align-items: center;
  gap: 7px;
  margin-left: auto;
}

.onboarding-shell {
  width: min(1320px, calc(100% - 48px));
  margin: 0 auto;
  padding: 18px 0 22px;
}

.dimension-progress {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto 84px;
  height: 62px;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
  padding: 0 16px;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: #ffffff;
}

.conversation-progress-copy {
  display: grid;
  min-width: 0;
  gap: 3px;
  line-height: 1.2;
}

.conversation-progress-copy .eyebrow { color: var(--color-accent); font-size: 13px; font-weight: 700; }
.conversation-progress-copy strong { font-size: 15px; }
.conversation-progress-copy small { color: var(--color-text-muted); font-size: 12px; }

.progress-dots { display: flex; align-items: center; gap: 7px; padding: 0 18px; }
.progress-dots span { width: 9px; height: 9px; border: 1px solid var(--color-border-strong); border-radius: 50%; background: #fff; transition: background .2s ease, transform .2s ease; }
.progress-dots span.current { border-color: var(--color-accent); background: var(--color-accent); transform: scale(1.25); }
.progress-dots span.confirmed { border-color: var(--color-accent); background: var(--color-accent-soft); }

.dimension-step {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
  color: var(--color-text-muted);
  font-size: 14px;
}

.dimension-step > span {
  display: grid;
  width: 26px;
  height: 26px;
  flex: 0 0 auto;
  place-items: center;
  border: 1px solid var(--color-border-strong);
  border-radius: 50%;
  background: #ffffff;
  font-weight: 700;
}

.dimension-step.current,
.dimension-step.confirmed {
  color: var(--color-text);
}

.dimension-step.current > span {
  color: #ffffff;
  border-color: var(--color-accent);
  background: var(--color-accent);
}

.dimension-step.confirmed > span {
  color: var(--color-accent);
  border-color: #ccd0cf;
  background: var(--color-accent-soft);
}

.dimension-step strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.progress-copy {
  display: grid;
  justify-items: end;
  padding-left: 12px;
  border-left: 1px solid var(--color-border);
  line-height: 1.2;
}

.progress-copy strong { font-size: 16px; }
.progress-copy span { color: var(--color-text-muted); font-size: 14px; }

.onboarding-body {
  display: grid;
  height: calc(100vh - 180px);
  min-height: 570px;
  grid-template-columns: minmax(0, 68fr) minmax(350px, 32fr);
  gap: 14px;
}

.conversation-panel {
  display: flex;
  min-width: 0;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-panel);
  background: #ffffff;
}

.conversation-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 24px 28px;
  scroll-behavior: smooth;
}

.stable-state {
  display: flex;
  height: 100%;
  align-items: center;
  justify-content: center;
  gap: 9px;
  color: var(--color-text-secondary);
}

.message {
  display: flex;
  max-width: 78%;
  gap: 10px;
  margin-bottom: 18px;
}

.message-avatar {
  display: grid;
  width: 34px;
  height: 34px;
  flex: 0 0 auto;
  place-items: center;
  color: var(--color-accent);
  border: 1px solid var(--color-border);
  border-radius: 50%;
  background: var(--color-surface-subtle);
}

.message > div {
  min-width: 0;
  padding: 12px 14px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface-subtle);
}

.message strong { font-size: 14px; }
.message p { margin: 4px 0 0; font-size: 15px; line-height: 1.7; white-space: pre-line; }
.message-status { display: block; margin-top: 6px; color: #d4e3e6; font-size: 14px; line-height: 1.4; }
.message-status.is-error { color: #f1c9c4; }

.user-message {
  justify-content: flex-end;
  margin-left: auto;
}

.user-message > div {
  color: #ffffff;
  border-color: #11212d;
  background: #11212d;
}

.compact-message { margin-bottom: 10px; }
.current-question { max-width: 86%; }
.reflection-message { max-width: 86%; margin-top: -4px; }
.reflection-message > div { background: #f6f8f8; }
.reflection-message small { display: block; margin-top: 7px; color: var(--color-accent); font-size: 13px; line-height: 1.5; }

.candidate-editor,
.evidence-editor,
.completion-panel {
  margin: 6px 0 22px 44px;
  padding: 18px;
  border: 1px solid #ccd0cf;
  border-radius: 8px;
  background: #ffffff;
}

.candidate-editor > header,
.evidence-editor > header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 14px;
}

.candidate-editor > header > div,
.evidence-editor > header > div { display: grid; gap: 3px; }
.candidate-editor > header span,
.evidence-editor > header span { display: flex; align-items: center; gap: 6px; color: var(--color-text-secondary); font-size: 14px; }
.candidate-editor > header strong,
.evidence-editor > header strong { font-size: 16px; }
.candidate-editor .saved-badge { color: var(--color-accent); white-space: nowrap; }
.candidate-map { min-width: 0; margin: 12px 0 0; padding: 10px 12px; border: 1px solid var(--color-border-strong); border-radius: 6px; }
.candidate-map legend { padding: 0 4px; font-size: 14px; font-weight: 700; }
.candidate-map-row { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; }
.candidate-map-row + .candidate-map-row { margin-top: 10px; }
.candidate-map-row > input { flex: 1 1 180px; min-width: 0; }
.candidate-editor .candidate-map-row label { flex: 1 1 160px; min-width: 0; margin-top: 0; }
.candidate-editor .candidate-map-row input[type="range"] { padding: 0; border: 0; accent-color: var(--color-accent); box-shadow: none; }

.candidate-editor label,
.evidence-editor label {
  display: grid;
  gap: 6px;
  margin-top: 12px;
}

.candidate-editor label > span,
.evidence-editor label > span { font-size: 14px; font-weight: 700; }
.candidate-editor label > span { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.candidate-editor label > span small { color: var(--color-text-muted); font-size: 14px; font-weight: 500; }
.evidence-editor label > span { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.evidence-editor label > span small { color: var(--color-text-muted); font-size: 14px; font-weight: 500; }
.evidence-editor label > small { color: var(--color-text-muted); font-size: 14px; }
.field-conflict {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 4px 12px;
  padding: 10px 12px;
  border: 1px solid #ccd0cf;
  border-radius: 6px;
  background: #f1f4f4;
}
.field-conflict span { min-width: 0; color: var(--color-text); font-size: 14px; line-height: 1.5; overflow-wrap: anywhere; }
.field-conflict span strong { margin-right: 7px; color: var(--color-accent); }
.field-conflict small { min-width: 0; color: var(--color-text-muted); font-size: 14px; overflow-wrap: anywhere; }
.candidate-editor input,
.candidate-editor textarea,
.evidence-editor input,
.evidence-editor textarea,
.answer-composer textarea,
.legacy-grid input {
  width: 100%;
  padding: 10px 12px;
  color: var(--color-text);
  border: 1px solid var(--color-border-strong);
  border-radius: 6px;
  outline: none;
  background: #ffffff;
  font-size: 15px;
  line-height: 1.55;
  resize: vertical;
}

.candidate-editor input:focus,
.candidate-editor textarea:focus,
.evidence-editor input:focus,
.evidence-editor textarea:focus,
.answer-composer textarea:focus,
.legacy-grid input:focus { border-color: var(--color-accent); box-shadow: 0 0 0 3px #11212d14; }

.candidate-warning,
.error-banner {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  color: var(--color-danger);
  border: 1px solid #e7c7c7;
  border-radius: 6px;
  background: var(--color-danger-soft);
  font-size: 14px;
}

.candidate-editor .primary-action { margin-top: 14px; }
.candidate-understanding,
.candidate-uncertainties {
  margin-top: 14px;
  padding: 12px 14px;
  border: 1px solid var(--color-border);
  border-radius: 12px;
  background: var(--color-surface-muted);
}
.candidate-understanding > div { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.candidate-understanding p { margin: 7px 0 0; line-height: 1.65; }
.model-badge { color: var(--color-text-muted); font-size: 14px; font-weight: 500; }
.candidate-uncertainties { background: #fffaf0; border-color: #ead7b0; }
.candidate-uncertainties ul { margin: 7px 0 0; padding-left: 18px; }
.candidate-uncertainties li { margin: 3px 0; line-height: 1.5; }
.candidate-evidence { display: block; margin-top: 5px; color: var(--color-text-muted); font-size: 14px; line-height: 1.5; }

.evidence-source {
  margin: 0 0 4px;
  color: var(--color-text-secondary);
  font-size: 14px;
  line-height: 1.55;
}

.evidence-failure {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: flex-start;
  gap: 10px;
  margin: 6px 0 18px 44px;
  padding: 13px 15px;
  color: var(--color-danger);
  border: 1px solid #e7c7c7;
  border-radius: 6px;
  background: var(--color-danger-soft);
}

.evidence-failure strong { font-size: 14px; }
.evidence-failure p { margin: 4px 0 0; color: var(--color-text-secondary); font-size: 14px; line-height: 1.55; }

.icon-action {
  display: grid;
  width: 36px;
  height: 36px;
  flex: none;
  place-items: center;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: #ffffff;
  cursor: pointer;
}

.secondary-action,
.attachment-action {
  display: inline-flex;
  min-height: 38px;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 0 13px;
  color: var(--color-accent);
  border: 1px solid var(--color-border-strong);
  border-radius: 6px;
  background: #ffffff;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
}

.secondary-action { margin-top: 14px; }
.secondary-action:disabled,
.attachment-action:disabled,
.icon-action:disabled { cursor: not-allowed; opacity: 0.5; }

.primary-action {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 0 16px;
  color: #ffffff;
  border: 1px solid #11212d;
  border-radius: 6px;
  background: #11212d;
  font-size: 15px;
  font-weight: 700;
  cursor: pointer;
}

.primary-action:hover { background: #000000; }
.primary-action:disabled { cursor: not-allowed; opacity: 0.55; }

.completion-panel {
  display: grid;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 14px;
  color: var(--color-accent);
}

.completion-panel strong { color: var(--color-text); font-size: 17px; }
.completion-panel p { margin: 3px 0 0; color: var(--color-text-secondary); font-size: 14px; }

.error-banner {
  margin: 0 20px 10px;
}

.error-banner button {
  display: grid;
  width: 30px;
  height: 30px;
  place-items: center;
  margin-left: auto;
  color: inherit;
  border: 0;
  background: transparent;
  cursor: pointer;
}

.answer-composer {
  display: grid;
  gap: 7px;
  padding: 15px 20px 17px;
  border-top: 1px solid var(--color-border);
  background: #ffffff;
}

.answer-composer > label { font-size: 14px; font-weight: 700; }
.answer-composer > .answer-row { display: grid; grid-template-columns: 1fr 44px; gap: 8px; align-items: stretch; }
.answer-composer textarea { min-height: 68px; max-height: 120px; resize: none; }
.answer-composer > span { color: var(--color-text-muted); font-size: 14px; }

.answer-composer > .composer-tools {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
}

.suggested-prompts {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  gap: 6px;
  margin-right: auto;
}

.suggested-prompts button {
  padding: 6px 9px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  background: var(--color-surface-subtle);
  font-size: 12px;
  cursor: pointer;
}
.suggested-prompts button:hover { color: var(--color-accent); border-color: var(--color-border-strong); }

.composer-tools > span {
  min-width: 0;
  color: var(--color-text-muted);
  font-size: 14px;
  line-height: 1.45;
}

.evidence-type {
  display: inline-grid;
  flex: none;
  grid-template-columns: 1fr 1fr;
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 6px;
}

.evidence-type button {
  min-height: 36px;
  padding: 0 10px;
  color: var(--color-text-secondary);
  border: 0;
  background: #ffffff;
  font-size: 14px;
  cursor: pointer;
}

.evidence-type button + button { border-left: 1px solid var(--color-border); }
.evidence-type button.active { color: #ffffff; background: #11212d; }

.visually-hidden {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  clip-path: inset(50%);
}

.send-action {
  display: grid;
  place-items: center;
  color: #ffffff;
  border: 1px solid #11212d;
  border-radius: 6px;
  background: #11212d;
  cursor: pointer;
}

.send-action:disabled { cursor: not-allowed; opacity: 0.35; }

.legacy-onboarding {
  width: min(760px, calc(100% - 48px));
  margin: 54px auto;
  padding: 30px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: #ffffff;
}

.legacy-onboarding > header { display: flex; align-items: center; gap: 12px; }
.legacy-onboarding h1 { margin: 2px 0 0; font-family: var(--font-heading); font-size: 25px; }
.legacy-onboarding p { color: var(--color-text-secondary); }
.legacy-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin: 22px 0; }
.legacy-grid label { display: grid; gap: 6px; }
.legacy-grid label > span { font-size: 14px; font-weight: 700; }

.spin { animation: spin 0.9s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-height: 800px) {
  .onboarding-shell { padding-top: 12px; }
  .dimension-progress { height: 56px; margin-bottom: 10px; }
  .onboarding-body { height: calc(100vh - 154px); min-height: 560px; }
  .conversation-scroll { padding-top: 18px; padding-bottom: 18px; }
  .message { margin-bottom: 13px; }
}
</style>
