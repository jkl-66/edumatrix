<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  LoaderCircle,
  MessageCircle,
  RefreshCw,
  Send,
  Sparkles,
  WandSparkles,
} from '@lucide/vue'
import {
  completeProfileUpdate,
  confirmProfileUpdateTurn,
  getProfileUpdateSession,
  startProfileUpdate,
  submitProfileUpdateTurn,
} from '../api/onboarding'
import { useCourseContextStore } from '../stores/courseContext'

const route = useRoute()
const router = useRouter()
const courseContext = useCourseContextStore()
const session = ref(null)
const loading = ref(true)
const busy = ref(false)
const completing = ref(false)
const error = ref('')
const notice = ref('')
const answer = ref('')
const conversation = ref(null)

const courseId = computed(() => String(
  route.query.course_id || courseContext.contextRef?.courseId || courseContext.course?.id || '',
))
const turns = computed(() => session.value?.turns || [])
const pendingTurn = computed(() => [...turns.value].reverse().find((turn) => (
  ['awaiting_confirmation', 'extraction_failed', 'projection_failed'].includes(turn.status)
)))
const active = computed(() => Boolean(session.value?.active))
const currentQuestion = computed(() => session.value?.question || '最近有没有哪一次学习让你觉得终于想通了，或者反复试了几次还是卡住？')
const followUpQuestion = computed(() => pendingTurn.value?.followUpQuestion || currentQuestion.value)
const suggestedPrompts = computed(() => session.value?.suggestedPrompts || [])
const progress = computed(() => session.value?.conversationProgress || { rounds: turns.value.length, exploredCount: 0, totalAngles: 10 })
const courseTitle = computed(() => session.value?.courseContext?.title || courseContext.course?.title || '当前课程')
const canSend = computed(() => Boolean(answer.value.trim()) && !busy.value && !pendingTurn.value && active.value)
const hasConfirmedTurn = computed(() => turns.value.some((turn) => turn.status === 'confirmed'))
const candidate = computed(() => pendingTurn.value?.extractedCandidates || {})
const candidateHighlights = computed(() => {
  const fields = Array.isArray(candidate.value.fields) ? candidate.value.fields : []
  const dimensions = Array.isArray(candidate.value.dimensions) ? candidate.value.dimensions : []
  const weakPoints = Array.isArray(candidate.value.weakPointAttribution) ? candidate.value.weakPointAttribution : []
  return [
    ...fields.map((item) => ({
      label: item.label || '刚才提到的事情',
      value: Array.isArray(item.value) ? item.value.join('；') : item.value,
    })),
    ...dimensions.map((item) => ({
      label: friendlyDimensionLabel(item.key, item.label),
      value: item.value || item.status,
    })),
    ...weakPoints.map((item) => ({
      label: '可能需要再练练',
      value: item.weakPoint || item.weak_point,
    })),
  ].filter((item) => item.value).slice(0, 6)
})

const friendlyTopics = [
  '最近学会的东西',
  '卡住时怎么继续',
  '把知识用到新题',
  '适合你的学习节奏',
  '喜欢怎样被帮助',
  '下一步想做成什么',
]

function friendlyDimensionLabel(key, label) {
  const labels = {
    knowledge_mastery: '最近更有把握的地方',
    misconception_profile: '容易混在一起的地方',
    understanding_fluency_transfer: '把学会的东西用起来',
    cognitive_processing: '面对复杂内容时的感受',
    learning_strategy: '你会怎样练习',
    metacognition: '你判断自己学会的方法',
    motivation_and_purpose: '想把所学用到哪里',
    affect_resilience: '遇到挫折后的状态',
    interaction_preference: '喜欢怎样一起学习',
    learning_context: '什么环境最适合你',
  }
  return labels[key] || (label && !/画像|维度|证据|置信度|ID|prompt/i.test(label) ? label : '刚才提到的学习感受')
}

function messageOf(requestError) {
  const detail = requestError?.response?.data?.detail || requestError?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || requestError?.message || '这一轮暂时没有完成，请稍后再试。'
}

function makeTurnId() {
  return globalThis.crypto?.randomUUID?.() || `profile-update-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function scrollToLatest() {
  nextTick(() => {
    if (conversation.value) conversation.value.scrollTop = conversation.value.scrollHeight
  })
}

async function loadSession() {
  loading.value = true
  error.value = ''
  try {
    let payload = await getProfileUpdateSession()
    if (!payload.active) payload = await startProfileUpdate(courseId.value || null)
    session.value = payload
    scrollToLatest()
  } catch (requestError) {
    error.value = messageOf(requestError)
  } finally {
    loading.value = false
  }
}

async function sendAnswer() {
  if (!canSend.value) return
  const text = answer.value.trim()
  const turnId = makeTurnId()
  answer.value = ''
  busy.value = true
  error.value = ''
  notice.value = ''
  session.value = {
    ...session.value,
    turns: [...turns.value, {
      turnId,
      question: currentQuestion.value,
      userAnswer: text,
      status: 'analyzing',
      extractedCandidates: {},
    }],
  }
  scrollToLatest()
  try {
    session.value = await submitProfileUpdateTurn({
      turn_id: turnId,
      user_answer: text,
      course_id: courseId.value || null,
    })
    scrollToLatest()
  } catch (requestError) {
    answer.value = text
    error.value = messageOf(requestError)
    session.value = {
      ...session.value,
      turns: turns.value.map((turn) => turn.turnId === turnId ? { ...turn, status: 'submission_failed' } : turn),
    }
  } finally {
    busy.value = false
  }
}

async function confirmRound(continueConversation) {
  const turn = pendingTurn.value
  if (!turn || busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  const fields = {}
  for (const item of (Array.isArray(candidate.value.fields) ? candidate.value.fields : [])) {
    if (!item?.key || item.value === undefined || item.value === null) continue
    fields[item.key] = item.value
  }
  try {
    session.value = await confirmProfileUpdateTurn(turn.turnId, {
      fields,
      dimensions: Array.isArray(candidate.value.dimensions) ? candidate.value.dimensions : [],
      weak_point_attribution: Array.isArray(candidate.value.weakPointAttribution) ? candidate.value.weakPointAttribution : [],
      continue_conversation: continueConversation,
    })
    notice.value = continueConversation
      ? '我已经记下刚才的内容。我们再聊一小段，把安排做得更贴合你。'
      : '这次聊到的内容已经保存好了，之后也可以随时回来补充。'
    scrollToLatest()
  } catch (requestError) {
    error.value = messageOf(requestError)
  } finally {
    busy.value = false
  }
}

async function finishConversation() {
  if (!hasConfirmedTurn.value || completing.value || pendingTurn.value) return
  completing.value = true
  error.value = ''
  try {
    session.value = await completeProfileUpdate()
    notice.value = '这次对话已经收好，你的学习安排会继续参考刚才聊到的内容。'
  } catch (requestError) {
    error.value = messageOf(requestError)
  } finally {
    completing.value = false
  }
}

function usePrompt(prompt) {
  if (!prompt || !canSend.value) return
  answer.value = `${prompt} `
}

function backToProfile() {
  router.push({ path: '/profile/learning', query: courseId.value ? { course_id: courseId.value } : undefined })
}

onMounted(loadSession)
</script>

<template>
  <main class="profile-update-page" data-testid="profile-update-page">
    <header class="profile-update-header">
      <button type="button" class="back-button" aria-label="返回学习画像" @click="backToProfile">
        <ArrowLeft :size="18" />
        <span>回到学习画像</span>
      </button>
      <div class="header-title">
        <span class="header-kicker"><WandSparkles :size="15" />学习伙伴</span>
        <h1>聊聊最近的学习</h1>
        <p>{{ courseTitle }}</p>
      </div>
      <div class="header-round" aria-live="polite">
        <strong>{{ progress.rounds }}</strong>
        <span>段对话</span>
      </div>
    </header>

    <section class="profile-update-layout">
      <section class="conversation-card" aria-label="学习伙伴对话">
        <div ref="conversation" class="conversation-scroll">
          <div v-if="loading" class="state-message"><LoaderCircle class="spin" :size="20" />正在把上次聊天接回来</div>
          <template v-else>
            <div class="message partner-message opening-message">
              <span class="avatar"><Sparkles :size="17" /></span>
              <div>
                <span class="message-name">学习伙伴</span>
                <p>{{ session?.assistantOpening || '我们不做表格问答。你可以从最近一次真正动手学习的经历说起，我会顺着你的话，一点点把接下来的安排聊清楚。' }}</p>
              </div>
            </div>

            <template v-for="turn in turns" :key="turn.turnId">
              <div class="message partner-message">
                <span class="avatar"><MessageCircle :size="17" /></span>
                <div><span class="message-name">学习伙伴</span><p>{{ turn.question || currentQuestion }}</p></div>
              </div>
              <div class="message learner-message">
                <div><span class="message-name">你</span><p>{{ turn.userAnswer }}</p></div>
              </div>
              <div v-if="turn.assistantReply" class="message partner-message reflection-message">
                <span class="avatar soft-avatar"><Sparkles :size="17" /></span>
                <div><span class="message-name">学习伙伴</span><p>{{ turn.assistantReply }}</p></div>
              </div>
            </template>

            <section v-if="pendingTurn" class="round-review" data-testid="profile-update-round-review">
              <div class="review-heading">
                <div><span class="review-kicker"><CheckCircle2 :size="15" />我先把刚才听到的放在这里</span><h2>看看我有没有理解对</h2></div>
                <span class="review-note">你可以直接改口或补充</span>
              </div>
              <p v-if="candidate.understanding" class="understanding">{{ candidate.understanding }}</p>
              <div v-if="candidateHighlights.length" class="highlight-list">
                <div v-for="item in candidateHighlights" :key="`${item.label}-${item.value}`" class="highlight-pill">
                  <span>{{ item.label }}</span><strong>{{ item.value }}</strong>
                </div>
              </div>
              <p v-if="pendingTurn.status === 'extraction_failed'" class="review-error">刚才那句话我没听完整。你的原话已经保留，再换一种说法发一次就好。</p>
              <div class="review-actions">
                <button v-if="pendingTurn.status !== 'extraction_failed'" type="button" class="primary-action" :disabled="busy" @click="confirmRound(true)">
                  <LoaderCircle v-if="busy" class="spin" :size="16" /><Check v-else :size="16" />记下这些，继续聊一会儿
                </button>
                <button v-if="pendingTurn.status !== 'extraction_failed'" type="button" class="quiet-action" :disabled="busy" @click="confirmRound(false)">这次先聊到这里</button>
                <button v-else type="button" class="quiet-action" :disabled="busy" @click="answer = pendingTurn.userAnswer; session = { ...session, turns: turns.filter(item => item.turnId !== pendingTurn.turnId) }">换一种说法</button>
              </div>
              <p v-if="pendingTurn.followUpQuestion && pendingTurn.status !== 'extraction_failed'" class="next-question-hint">接下来我想问：{{ pendingTurn.followUpQuestion }}</p>
            </section>

            <div v-if="!pendingTurn && active" class="current-question" data-testid="profile-update-current-question">
              <span class="avatar"><MessageCircle :size="17" /></span>
              <div><span class="message-name">学习伙伴继续问</span><p>{{ currentQuestion }}</p></div>
            </div>

            <div v-if="!active && hasConfirmedTurn" class="complete-message" data-testid="profile-update-complete">
              <CheckCircle2 :size="24" />
              <div><strong>这次聊天已经保存好了</strong><p>之后的讲解、练习和学习节奏会继续参考你刚才说的内容。</p></div>
              <button type="button" class="primary-action" @click="backToProfile">回到学习画像<ArrowRight :size="16" /></button>
            </div>
          </template>
        </div>

        <div v-if="error" class="error-banner" role="alert"><RefreshCw :size="16" />{{ error }}<button type="button" @click="loadSession">重新打开</button></div>
        <div v-if="notice" class="notice-banner" role="status"><CheckCircle2 :size="16" />{{ notice }}</div>

        <form v-if="active" class="composer" @submit.prevent="sendAnswer">
          <label for="profile-update-answer">想和我说什么</label>
          <div class="composer-row">
            <textarea id="profile-update-answer" v-model="answer" rows="3" maxlength="4000" :disabled="loading || busy || Boolean(pendingTurn) || !active" :placeholder="pendingTurn ? '先看看上面的理解，确认后再继续' : '不用整理成答案，想到什么就说什么。按 Ctrl + Enter 发送。'" @keydown.ctrl.enter.prevent="sendAnswer" />
            <button type="submit" class="send-button" aria-label="发送这一段" :disabled="!canSend"><LoaderCircle v-if="busy" class="spin" :size="18" /><Send v-else :size="18" /></button>
          </div>
          <div v-if="!pendingTurn && active" class="composer-footer">
            <div class="suggested-prompts" aria-label="可以从这里聊起">
              <button v-for="prompt in suggestedPrompts.slice(0, 3)" :key="prompt" type="button" :disabled="!canSend" @click="usePrompt(prompt)">{{ prompt }}</button>
            </div>
            <button v-if="hasConfirmedTurn" type="button" class="finish-button" :disabled="completing" @click="finishConversation">{{ completing ? '正在收好这次聊天…' : '这次先聊到这里' }}</button>
          </div>
        </form>
      </section>

      <aside class="conversation-guide">
        <div class="guide-orbit"><Sparkles :size="22" /></div>
        <span class="guide-kicker">慢一点，也没关系</span>
        <h2>我会从你的经历里找线索</h2>
        <p>不需要记住任何专业名词。你说过的具体例子、卡住的瞬间和真正想做成的事，都会帮助我把下一步安排得更贴近你。</p>
        <div class="topic-cloud" aria-label="聊天会自然涉及的内容">
          <span v-for="topic in friendlyTopics" :key="topic">{{ topic }}</span>
        </div>
        <div class="guide-progress">
          <div><span>已经聊到</span><strong>{{ progress.rounds }} 段</strong></div>
          <div><span>了解得更完整</span><strong>{{ progress.exploredCount }}/{{ progress.totalAngles || 10 }}</strong></div>
        </div>
        <div class="guide-note"><CheckCircle2 :size="17" /><span>只有你说“记下这些”，内容才会保存到学习档案；随时可以改口。</span></div>
      </aside>
    </section>
  </main>
</template>

<style scoped>
.profile-update-page { min-height: 100vh; padding: 24px 28px 40px; color: #172a34; background: radial-gradient(circle at 12% 0%, #eef5f4 0, #f7faf9 36%, #f4f7f7 100%); font-family: var(--font-sans); }
.profile-update-header { width: min(1240px, 100%); margin: 0 auto 26px; display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 18px; }
.back-button { display: inline-flex; width: fit-content; align-items: center; gap: 8px; padding: 10px 12px; color: #35515b; border: 1px solid #d6e2e1; border-radius: 12px; background: rgba(255,255,255,.74); font-size: 14px; font-weight: 700; cursor: pointer; }
.back-button:hover { background: #fff; }
.header-title { text-align: center; }
.header-kicker, .guide-kicker, .review-kicker { display: inline-flex; align-items: center; gap: 6px; color: #52737a; font-size: 14px; font-weight: 700; }
.header-title h1 { margin: 5px 0 4px; color: #122730; font-family: var(--font-serif); font-size: clamp(25px, 3vw, 34px); font-weight: 650; letter-spacing: -.02em; }
.header-title p { margin: 0; color: #6b8187; font-size: 14px; }
.header-round { justify-self: end; display: grid; gap: 2px; min-width: 74px; padding: 10px 14px; border: 1px solid #dbe7e6; border-radius: 18px; background: rgba(255,255,255,.76); text-align: center; }
.header-round strong { color: #1e5662; font-size: 22px; line-height: 1; }
.header-round span { color: #71858a; font-size: 14px; }
.profile-update-layout { width: min(1240px, 100%); margin: 0 auto; display: grid; grid-template-columns: minmax(0, 1fr) minmax(280px, 340px); gap: 22px; align-items: start; }
.conversation-card { min-width: 0; overflow: hidden; border: 1px solid #d8e5e3; border-radius: 26px; background: rgba(255,255,255,.9); box-shadow: 0 18px 50px rgba(30,74,81,.08); }
.conversation-scroll { max-height: calc(100vh - 260px); min-height: 490px; overflow-y: auto; padding: 28px 30px 14px; scroll-behavior: smooth; }
.message { display: flex; gap: 11px; max-width: 88%; margin: 0 0 18px; }
.message > div { min-width: 0; }
.partner-message { align-items: flex-start; }
.learner-message { justify-content: flex-end; margin-left: auto; }
.learner-message > div { max-width: min(620px, 100%); padding: 12px 16px; border: 1px solid #cfe1df; border-radius: 18px 18px 5px 18px; background: #edf6f4; }
.avatar { display: grid; width: 32px; height: 32px; flex: none; place-items: center; color: #205765; border: 1px solid #c7ddda; border-radius: 50%; background: #e4f1ef; }
.soft-avatar { color: #496c75; background: #f0f6f5; }
.message-name { display: block; margin-bottom: 4px; color: #668188; font-size: 14px; font-weight: 700; }
.message p { margin: 0; color: #243941; font-size: 16px; line-height: 1.75; white-space: pre-wrap; overflow-wrap: anywhere; }
.opening-message { margin-bottom: 26px; }
.reflection-message { padding-left: 22px; }
.state-message { display: flex; min-height: 320px; align-items: center; justify-content: center; gap: 10px; color: #637a80; font-size: 15px; }
.current-question { display: flex; gap: 11px; margin: 26px 0 10px; padding: 17px 18px; border: 1px dashed #b8d2cf; border-radius: 19px; background: #f5faf9; }
.current-question p { color: #1f4f59; }
.round-review { margin: 22px 0 24px 43px; padding: 21px; border: 1px solid #c7dcda; border-radius: 21px; background: linear-gradient(145deg, #f7fbfa, #ffffff); }
.review-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 15px; }
.review-heading h2 { margin: 6px 0 0; color: #193942; font-size: 20px; font-weight: 750; }
.review-note { color: #73888d; font-size: 14px; }
.understanding { margin: 16px 0 12px; color: #294b52; font-size: 16px; line-height: 1.72; }
.highlight-list { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 9px; }
.highlight-pill { display: grid; gap: 3px; padding: 11px 12px; border: 1px solid #deebe9; border-radius: 14px; background: #fff; }
.highlight-pill span { color: #668188; font-size: 14px; }
.highlight-pill strong { color: #28474d; font-size: 14px; line-height: 1.45; font-weight: 650; }
.review-actions { display: flex; flex-wrap: wrap; align-items: center; gap: 9px; margin-top: 18px; }
.primary-action, .quiet-action, .finish-button { display: inline-flex; min-height: 40px; align-items: center; justify-content: center; gap: 7px; padding: 9px 14px; border-radius: 11px; font-size: 14px; font-weight: 750; cursor: pointer; }
.primary-action { color: #fff; border: 1px solid #1e5662; background: #1e5662; }
.primary-action:hover { background: #164651; }
.quiet-action, .finish-button { color: #315761; border: 1px solid #cbdedc; background: #fff; }
.quiet-action:hover, .finish-button:hover { background: #f1f8f6; }
.primary-action:disabled, .quiet-action:disabled, .finish-button:disabled { cursor: wait; opacity: .55; }
.next-question-hint { margin: 15px 0 0; padding-top: 12px; border-top: 1px solid #e5efed; color: #6c858a; font-size: 14px; line-height: 1.55; }
.review-error { margin: 14px 0 0; padding: 11px 13px; color: #8b4e45; border-radius: 12px; background: #fbf1ef; font-size: 14px; line-height: 1.55; }
.complete-message { display: flex; align-items: center; gap: 13px; margin: 24px 0 12px; padding: 18px; color: #1e5662; border: 1px solid #c7dfda; border-radius: 18px; background: #edf7f4; }
.complete-message > div { flex: 1; }
.complete-message strong { display: block; margin-bottom: 4px; font-size: 16px; }
.complete-message p { margin: 0; color: #47666d; font-size: 14px; line-height: 1.55; }
.error-banner, .notice-banner { display: flex; align-items: center; gap: 8px; margin: 0 28px 12px; padding: 11px 13px; border-radius: 12px; font-size: 14px; line-height: 1.5; }
.error-banner { color: #8f453d; background: #fbefed; }
.notice-banner { color: #235c5d; background: #edf7f4; }
.error-banner button { margin-left: auto; padding: 5px 8px; color: inherit; border: 1px solid currentColor; border-radius: 8px; background: transparent; font-size: 14px; cursor: pointer; }
.composer { padding: 17px 26px 23px; border-top: 1px solid #e1eceb; background: rgba(250,253,252,.9); }
.composer > label { display: block; margin-bottom: 8px; color: #49666d; font-size: 14px; font-weight: 750; }
.composer-row { display: flex; align-items: flex-end; gap: 10px; }
.composer textarea { width: 100%; min-height: 86px; box-sizing: border-box; resize: vertical; padding: 12px 14px; color: #203940; border: 1px solid #c8dcd9; border-radius: 14px; outline: none; background: #fff; font: 16px/1.65 var(--font-sans); }
.composer textarea:focus { border-color: #6a9fa1; box-shadow: 0 0 0 3px rgba(91,145,147,.15); }
.composer textarea:disabled { background: #f2f6f5; }
.send-button { display: grid; width: 48px; height: 48px; flex: none; place-items: center; color: #fff; border: 1px solid #1e5662; border-radius: 14px; background: #1e5662; cursor: pointer; }
.send-button:hover { background: #164651; }
.send-button:disabled { cursor: not-allowed; opacity: .45; }
.composer-footer { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-top: 10px; }
.suggested-prompts { display: flex; flex-wrap: wrap; gap: 7px; }
.suggested-prompts button { max-width: 250px; overflow: hidden; padding: 6px 10px; color: #52727a; border: 1px solid #d4e5e2; border-radius: 999px; background: #fff; font-size: 14px; text-overflow: ellipsis; white-space: nowrap; cursor: pointer; }
.suggested-prompts button:hover { background: #f0f8f6; }
.suggested-prompts button:disabled { cursor: default; opacity: .55; }
.finish-button { min-height: 34px; padding: 7px 11px; white-space: nowrap; }
.conversation-guide { position: sticky; top: 22px; padding: 27px 24px 24px; overflow: hidden; border: 1px solid #dae8e6; border-radius: 28px; background: rgba(255,255,255,.74); box-shadow: 0 14px 36px rgba(31,76,83,.06); }
.conversation-guide::before { position: absolute; top: -90px; right: -72px; width: 180px; height: 180px; border-radius: 50%; background: #e9f4f1; content: ''; }
.guide-orbit { position: relative; display: grid; width: 47px; height: 47px; place-items: center; margin-bottom: 17px; color: #2c6970; border: 1px solid #c8dfda; border-radius: 17px; background: #edf8f5; }
.conversation-guide h2 { position: relative; margin: 8px 0 10px; color: #183a43; font-family: var(--font-serif); font-size: 24px; line-height: 1.28; }
.conversation-guide > p { position: relative; margin: 0; color: #587178; font-size: 15px; line-height: 1.75; }
.topic-cloud { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 20px; }
.topic-cloud span { padding: 7px 10px; color: #3f6670; border: 1px solid #d6e8e4; border-radius: 999px; background: #f5fbf8; font-size: 14px; }
.guide-progress { display: grid; grid-template-columns: 1fr 1fr; gap: 9px; margin-top: 23px; }
.guide-progress div { display: grid; gap: 3px; padding: 11px; border-radius: 14px; background: #f3f8f7; }
.guide-progress span { color: #71868b; font-size: 14px; }
.guide-progress strong { color: #285963; font-size: 17px; }
.guide-note { display: flex; align-items: flex-start; gap: 8px; margin-top: 20px; padding-top: 16px; border-top: 1px solid #e1edeb; color: #668087; font-size: 14px; line-height: 1.6; }
.guide-note svg { flex: none; margin-top: 2px; color: #4c8a83; }
.spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* Keep the update conversation on the shared EduMatrix palette. */
.profile-update-page {
  color: var(--color-text);
  background: var(--color-page);
}
:global(.app-content:has(.profile-update-page)) {
  background: var(--color-surface);
}
.back-button,
.header-round,
.conversation-card,
.conversation-guide,
.highlight-pill,
.quiet-action,
.finish-button,
.composer textarea,
.suggested-prompts button {
  background: var(--color-surface);
}
.back-button,
.header-round,
.conversation-card,
.conversation-guide,
.learner-message > div,
.current-question,
.round-review,
.highlight-pill,
.quiet-action,
.finish-button,
.composer textarea,
.suggested-prompts button {
  border-color: var(--color-border);
}
.conversation-card {
  border-radius: var(--radius-panel);
  box-shadow: var(--shadow-popover);
}
.conversation-guide {
  border-radius: var(--radius-panel);
  box-shadow: var(--shadow-popover);
}
.conversation-guide::before { display: none; }
.learner-message > div,
.current-question,
.round-review,
.highlight-pill,
.guide-progress div,
.guide-orbit,
.error-banner,
.notice-banner,
.complete-message {
  border-radius: var(--radius-control);
}
.learner-message > div { background: var(--color-accent-soft); }
.current-question { background: var(--color-surface-subtle); }
.round-review { background: var(--color-surface); }
.primary-action,
.send-button {
  color: #fff;
  border-color: var(--color-accent);
  background: var(--color-accent);
  border-radius: var(--radius-control);
}
.quiet-action,
.finish-button { color: var(--color-text); border-radius: var(--radius-control); }
.topic-cloud span {
  color: var(--color-text-secondary);
  border-color: var(--color-border);
  border-radius: var(--radius-control);
  background: var(--color-surface);
}
.guide-progress div { background: var(--color-surface-subtle); }
.guide-orbit { background: var(--color-accent-soft); }
.error-banner { color: var(--color-danger); background: var(--color-danger-soft); }
.notice-banner,
.complete-message { color: var(--color-success); background: var(--color-success-soft); }
.suggested-prompts button { border-radius: var(--radius-control); }

/* The profile update flow uses the same ink-and-paper surfaces as the rest of
 * the application. Keep the interaction states legible without introducing a
 * separate pale-cyan theme. */
.profile-update-page,
.conversation-card,
.conversation-guide,
.composer,
.learner-message > div,
.current-question,
.round-review,
.highlight-pill,
.guide-progress div,
.guide-orbit,
.topic-cloud span,
.suggested-prompts button {
  background: var(--color-surface);
}
.profile-update-page { color: var(--color-text); }
.back-button,
.header-title h1,
.conversation-guide h2,
.review-heading h2 { color: var(--color-text); }
.header-kicker,
.guide-kicker,
.review-kicker,
.header-round strong,
.message-name,
.conversation-guide > p,
.review-note,
.next-question-hint,
.composer > label,
.guide-progress span,
.guide-note,
.topic-cloud span,
.suggested-prompts button { color: var(--color-text-secondary); }
.header-title p,
.header-round span,
.state-message,
.message-name,
.guide-note { color: var(--color-text-muted); }
.back-button,
.header-round,
.conversation-card,
.conversation-guide,
.learner-message > div,
.current-question,
.round-review,
.highlight-pill,
.quiet-action,
.finish-button,
.composer textarea,
.suggested-prompts button,
.topic-cloud span {
  border-color: var(--color-border);
}
.learner-message > div,
.current-question,
.round-review,
.highlight-pill,
.guide-progress div,
.guide-orbit {
  border-radius: var(--radius-control);
}
.learner-message > div { border-left: 1px solid var(--color-accent); }
.current-question { border-style: solid; border-color: var(--color-border-strong); }
.round-review { box-shadow: var(--shadow-popover); }
.message p,
.understanding,
.highlight-pill strong { color: var(--color-text); }
.primary-action,
.send-button { background: var(--color-accent); border-color: var(--color-accent); }
.quiet-action,
.finish-button { color: var(--color-text); background: var(--color-surface); }
.composer { border-top-color: var(--color-border); }
.composer textarea { color: var(--color-text); background: var(--color-surface); }
.composer textarea:focus { border-color: var(--color-accent); box-shadow: 0 0 0 3px rgb(49 91 109 / 14%); }
.composer textarea:disabled { background: var(--color-surface-muted); }
.guide-orbit { color: var(--color-accent); border-color: var(--color-border-strong); }
.guide-progress div { border: 1px solid var(--color-border); }
.guide-progress strong { color: var(--color-accent); }
.complete-message,
.notice-banner { color: var(--color-success); background: var(--color-success-soft); border-color: var(--color-border); }
.error-banner,
.review-error { color: var(--color-danger); background: var(--color-danger-soft); }
@media (max-width: 940px) {
  .profile-update-page { padding: 18px 16px 28px; }
  .profile-update-header { grid-template-columns: auto 1fr auto; }
  .header-title { text-align: left; }
  .profile-update-layout { grid-template-columns: 1fr; }
  .conversation-guide { position: static; }
  .conversation-scroll { max-height: none; }
}
@media (max-width: 620px) {
  .profile-update-header { gap: 10px; }
  .back-button span { display: none; }
  .header-title h1 { font-size: 24px; }
  .header-title p { max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .conversation-scroll { padding: 22px 16px 12px; }
  .composer { padding-inline: 16px; }
  .message { max-width: 100%; }
  .round-review { margin-left: 0; padding: 16px; }
  .highlight-list { grid-template-columns: 1fr; }
  .review-heading { flex-direction: column; }
  .composer-footer { align-items: flex-start; flex-direction: column; }
  .finish-button { align-self: flex-end; }
}
</style>
