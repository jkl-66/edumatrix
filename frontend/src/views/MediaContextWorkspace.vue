<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { CheckCircle2, Code2, FilePlus2, Film, LoaderCircle, MessageSquareText, RefreshCw, Save, ShieldCheck, X } from '@lucide/vue'
import { appendMediaMessage, createMediaContextResource, createMediaConversation, getMediaContextResource, listMediaContextResources, saveMediaContextPosition } from '../api'

const resources = ref([])
const selected = ref(null)
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const notice = ref('')
const activeConversationId = ref('')
const messageRole = ref('note')
const messageText = ref('')
const form = ref({ resource_type: 'code', title: '', language: 'python', content: '', locator: '', duration_ms: 180000 })
const lineInput = ref(1)
const playbackInput = ref(0)
const scrollInput = ref(0)
const videoRef = ref(null)

const activeConversation = computed(() => selected.value?.conversations?.find(item => item.id === activeConversationId.value) || selected.value?.conversations?.find(item => item.status === 'active') || null)
const codeLines = computed(() => (selected.value?.content || '').split('\n'))
const isPlayable = computed(() => selected.value?.resource_type === 'video' && Boolean(selected.value.locator))

function detail(err) {
  const value = err?.detail || err?.response?.data?.detail
  return value?.message || (typeof value === 'string' ? value : '') || err?.message || '请求失败'
}

function syncPosition() {
  const position = selected.value?.position
  if (!position) return
  lineInput.value = position.line_number
  playbackInput.value = position.playback_ms
  scrollInput.value = position.scroll_ratio
  activeConversationId.value = selected.value.conversations?.find(item => item.status === 'active')?.id || ''
  nextTick(() => {
    if (videoRef.value && selected.value.resource_type === 'video') videoRef.value.currentTime = position.playback_ms / 1000
    document.querySelector(`[data-code-line="${position.line_number}"]`)?.scrollIntoView({ block: 'center' })
  })
}

async function refresh(preferredId = selected.value?.id) {
  loading.value = true
  error.value = ''
  try {
    const response = await listMediaContextResources()
    resources.value = response.items || []
    const id = resources.value.some(item => item.id === preferredId) ? preferredId : resources.value[0]?.id
    if (id) await selectResource(id)
    else selected.value = null
  } catch (caught) { error.value = detail(caught) } finally { loading.value = false }
}

async function selectResource(id) {
  saving.value = true
  error.value = ''
  try { selected.value = await getMediaContextResource(id); syncPosition() }
  catch (caught) { error.value = detail(caught) }
  finally { saving.value = false }
}

async function createResource() {
  saving.value = true; error.value = ''; notice.value = ''
  try {
    const payload = { ...form.value, duration_ms: form.value.resource_type === 'video' ? Number(form.value.duration_ms) : 0, content: form.value.resource_type === 'code' ? form.value.content : '', locator: form.value.resource_type === 'video' ? form.value.locator : '' }
    const created = await createMediaContextResource(payload)
    form.value = { resource_type: 'code', title: '', language: 'python', content: '', locator: '', duration_ms: 180000 }
    notice.value = '资源已固化，可在切换与刷新后恢复独立上下文。'
    await refresh(created.id)
  } catch (caught) { error.value = detail(caught) } finally { saving.value = false }
}

async function savePosition() {
  if (!selected.value) return
  saving.value = true; error.value = ''
  try {
    const playback = selected.value.resource_type === 'video' && videoRef.value ? Math.round(videoRef.value.currentTime * 1000) : Number(playbackInput.value)
    const position = await saveMediaContextPosition(selected.value.id, { expected_lock_version: selected.value.position.lock_version, line_number: Number(lineInput.value), column_number: 1, playback_ms: playback, scroll_ratio: Number(scrollInput.value) })
    selected.value.position = position; playbackInput.value = position.playback_ms
    notice.value = '当前位置已保存。'
  } catch (caught) { error.value = detail(caught) } finally { saving.value = false }
}

async function ensureConversation() {
  if (activeConversation.value) return activeConversation.value
  const conversation = await createMediaConversation(selected.value.id, `${selected.value.title} 训练记录`)
  selected.value.conversations.push(conversation)
  activeConversationId.value = conversation.id
  return conversation
}

async function appendMessage() {
  if (!selected.value || !messageText.value.trim()) return
  saving.value = true; error.value = ''
  try {
    const conversation = await ensureConversation()
    const updated = await appendMediaMessage(conversation.id, { expected_lock_version: conversation.lock_version, role: messageRole.value, content: messageText.value.trim() })
    selected.value.conversations = selected.value.conversations.map(item => item.id === updated.id ? updated : item)
    messageText.value = ''
    notice.value = '上下文消息已追加；系统未伪造 AI 回答。'
  } catch (caught) { error.value = detail(caught) } finally { saving.value = false }
}

onMounted(() => refresh())
</script>

<template>
  <section class="media-page" data-testid="media-context-workspace">
    <header class="media-head"><div><p>RESOURCE-BOUND CONTEXT</p><h1>代码与视频上下文</h1><span>每个资源独立保存阅读位置与训练对话，切换和刷新不会丢失。</span></div><button class="icon" title="刷新" @click="refresh()"><RefreshCw :size="16" /></button></header>
    <div v-if="error" class="banner error"><X :size="15" />{{ error }}</div>
    <div v-if="notice" class="banner notice"><CheckCircle2 :size="15" />{{ notice }}</div>
    <div v-if="loading" class="loading"><LoaderCircle class="spin" :size="18" />加载媒体上下文...</div>
    <div v-else class="media-grid">
      <aside class="resource-list">
        <div class="panel-title"><strong>资源</strong><small>{{ resources.length }}</small></div>
        <button v-for="item in resources" :key="item.id" data-testid="media-resource" :class="{ active: selected?.id === item.id }" @click="selectResource(item.id)"><Code2 v-if="item.resource_type === 'code'" :size="16" /><Film v-else :size="16" /><span><strong>{{ item.title }}</strong><small>{{ item.resource_type }} · {{ item.position.lock_version }} 次位置版本</small></span></button>
        <div v-if="!resources.length" class="empty">暂无资源</div>
      </aside>

      <main class="reader" data-testid="media-reader">
        <template v-if="selected">
          <header class="reader-head"><div><small>{{ selected.resource_type }} · {{ selected.content_sha256.slice(0, 12) }}</small><h2>{{ selected.title }}</h2></div><span v-if="selected.resource_type === 'code'">行 {{ selected.position.line_number }}</span><span v-else>{{ Math.round(selected.position.playback_ms / 1000) }} 秒</span></header>
          <div v-if="selected.resource_type === 'code'" class="code-reader" data-testid="code-reader"><div v-for="(line, index) in codeLines" :key="index" :data-code-line="index + 1" :class="{ current: index + 1 === selected.position.line_number }"><span>{{ index + 1 }}</span><code>{{ line || ' ' }}</code></div></div>
          <div v-else class="video-reader" data-testid="video-reader">
            <video v-if="isPlayable" ref="videoRef" :src="selected.locator" controls preload="metadata" @timeupdate="playbackInput = Math.round($event.target.currentTime * 1000)" />
            <div v-else class="video-unavailable"><Film :size="28" /><strong>时间轴上下文</strong><span>未注册可播放媒体，只保存学习位置，不宣称播放成功。</span></div>
          </div>
          <div class="position-bar" data-testid="media-position-controls"><label v-if="selected.resource_type === 'code'">定位行<input v-model.number="lineInput" type="number" min="1" :max="codeLines.length" /></label><label v-else>毫秒位置<input v-model.number="playbackInput" type="number" min="0" :max="selected.duration_ms" /></label><label>阅读进度<input v-model.number="scrollInput" type="number" min="0" max="1" step="0.01" /></label><button :disabled="saving" @click="savePosition"><Save :size="14" />保存位置</button></div>
        </template>
        <div v-else class="empty large">选择或创建一个代码/视频资源</div>
      </main>

      <aside class="conversation" data-testid="media-conversation-panel">
        <div class="panel-title"><strong>绑定对话</strong><ShieldCheck :size="15" /></div>
        <div v-if="activeConversation" class="messages"><article v-for="message in activeConversation.messages" :key="message.id"><small>{{ message.role === 'note' ? '训练笔记' : '学习者提问' }} · #{{ message.sequence }}</small><p>{{ message.content }}</p><span v-if="selected?.resource_type === 'code'">记录于第 {{ message.position_snapshot.line_number }} 行</span><span v-else>记录于 {{ Math.round(message.position_snapshot.playback_ms / 1000) }} 秒</span></article></div>
        <div v-else class="empty">首次发送时创建绑定会话</div>
        <div v-if="selected" class="composer"><select v-model="messageRole"><option value="note">训练笔记</option><option value="user">学习者提问</option></select><textarea v-model="messageText" rows="4" maxlength="12000" placeholder="记录当前代码行或视频时间点的问题。" /><button :disabled="saving || !messageText.trim()" @click="appendMessage"><MessageSquareText :size="14" />追加消息</button><small>本页不调用模型，不把人工内容冒充 AI 回答。</small></div>
      </aside>
    </div>

    <form class="create-panel" data-testid="media-resource-form" @submit.prevent="createResource">
      <div class="panel-title"><strong>注册资源</strong><FilePlus2 :size="16" /></div>
      <div class="form-grid"><label>类型<select v-model="form.resource_type"><option value="code">代码</option><option value="video">视频</option></select></label><label>标题<input v-model="form.title" required maxlength="256" /></label><label v-if="form.resource_type === 'code'">语言<input v-model="form.language" maxlength="32" /></label><label v-else>时长（毫秒）<input v-model.number="form.duration_ms" type="number" min="0" max="86400000" /></label><label v-if="form.resource_type === 'video'" class="wide">本地路径或 HTTPS URL<input v-model="form.locator" maxlength="2048" placeholder="/media/demo.mp4 或 https://..." /></label><label v-else class="wide">代码正文<textarea v-model="form.content" required rows="6" maxlength="200000" /></label></div><button class="create" :disabled="saving"><FilePlus2 :size="15" />固化资源</button>
    </form>
  </section>
</template>

<style scoped>
.media-page{max-width:1440px;margin:0 auto;color:#29332c}.media-head{display:flex;align-items:flex-start;justify-content:space-between;padding-bottom:16px;border-bottom:1px solid #dce4dd}.media-head p,.reader-head small{margin:0 0 4px;color:#849087;font-size:9px;letter-spacing:.08em}.media-head h1,.reader-head h2{margin:0;font-size:19px}.media-head span{display:block;margin-top:5px;color:#68766d;font-size:11px}.icon{display:grid;width:36px;height:36px;place-items:center;border:1px solid #dce4dd;border-radius:7px;background:#fff;color:#66736a}.banner{display:flex;align-items:center;gap:7px;margin-top:10px;padding:9px 11px;font-size:11px}.banner.error{border:1px solid #ebcbc7;background:#fff4f2;color:#954f47}.banner.notice{border:1px solid #c8dfce;background:#f0f8f2;color:#3c6848}.loading,.empty{display:grid;min-height:130px;place-items:center;color:#8b978e;font-size:10px}.loading{display:flex;justify-content:center;gap:7px}.media-grid{display:grid;grid-template-columns:220px minmax(420px,1fr)300px;min-height:590px;margin-top:14px;border-block:1px solid #dce4dd}.resource-list,.conversation{min-width:0}.resource-list{border-right:1px solid #dce4dd}.conversation{border-left:1px solid #dce4dd}.panel-title{display:flex;height:43px;align-items:center;justify-content:space-between;padding:0 12px;border-bottom:1px solid #e4eae5;font-size:11px}.resource-list>button{display:grid;width:100%;grid-template-columns:20px 1fr;gap:7px;padding:11px;border:0;border-bottom:1px solid #edf1ed;background:transparent;color:#6d796f;text-align:left}.resource-list>button.active{background:#edf6ef;color:#315b3c}.resource-list strong,.resource-list small{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.resource-list strong{font-size:10px}.resource-list small{margin-top:4px;color:#919b94;font-size:8px}.reader{min-width:0;padding:15px}.reader-head{display:flex;align-items:flex-start;justify-content:space-between;padding-bottom:12px;border-bottom:1px solid #e4eae5}.reader-head>span{padding:4px 7px;background:#edf3ee;color:#52675a;font-size:9px}.code-reader{height:390px;overflow:auto;margin-top:12px;border:1px solid #dfe5e0;background:#172019;color:#dfe9df;font:12px/1.65 Consolas,monospace}.code-reader>div{display:grid;grid-template-columns:42px 1fr;min-height:20px}.code-reader>div>span{padding-right:9px;color:#748078;text-align:right;user-select:none}.code-reader code{padding-left:10px;white-space:pre;border-left:1px solid #344038}.code-reader .current{background:#314737}.video-reader{display:grid;height:390px;margin-top:12px;place-items:center;background:#151b17}.video-reader video{width:100%;height:100%;object-fit:contain}.video-unavailable{display:grid;gap:7px;place-items:center;color:#aab4ad;text-align:center}.video-unavailable strong{color:#edf2ee;font-size:13px}.video-unavailable span{max-width:300px;font-size:10px}.position-bar{display:flex;flex-wrap:wrap;align-items:end;gap:8px;margin-top:10px}.position-bar label{color:#718078;font-size:9px}.position-bar input{display:block;width:100px;margin-top:4px;padding:7px;border:1px solid #d7e0d9}.position-bar button,.composer button,.create{display:flex;height:34px;align-items:center;gap:5px;padding:0 10px;border:0;background:#315b3c;color:#fff;font-size:10px}.messages{max-height:390px;overflow:auto;padding:10px}.messages article{margin-bottom:8px;padding:9px;border-left:2px solid #b9cdbf;background:#f4f7f4}.messages small,.messages span{color:#87938a;font-size:8px}.messages p{margin:5px 0;color:#38453b;font-size:10px;line-height:1.5}.composer{padding:10px;border-top:1px solid #e4eae5}.composer select,.composer textarea,.form-grid input,.form-grid select,.form-grid textarea{box-sizing:border-box;width:100%;margin-bottom:7px;padding:8px;border:1px solid #d8e1da;background:#fff;font-size:10px}.composer small{display:block;margin-top:6px;color:#89958c;font-size:8px}.create-panel{margin-top:16px;border:1px solid #dce4dd;background:#fff}.form-grid{display:grid;grid-template-columns:160px 1fr 180px;gap:9px;padding:12px}.form-grid label{color:#68766d;font-size:9px}.form-grid input,.form-grid select,.form-grid textarea{display:block;margin:4px 0 0}.form-grid .wide{grid-column:1/-1}.create{margin:0 12px 12px}.spin{animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}.empty.large{min-height:500px}
@media(max-width:1050px){.media-grid{grid-template-columns:200px 1fr}.conversation{grid-column:1/-1;border-top:1px solid #dce4dd;border-left:0}.messages{max-height:240px}}
@media(max-width:700px){.media-grid{grid-template-columns:1fr}.resource-list{max-height:220px;overflow:auto;border-right:0;border-bottom:1px solid #dce4dd}.reader{padding:10px}.code-reader,.video-reader{height:300px}.conversation{grid-column:auto}.form-grid{grid-template-columns:1fr}.form-grid .wide{grid-column:auto}.media-head{gap:10px}.media-head h1{font-size:17px}.position-bar label{flex:1}.position-bar input{width:100%;box-sizing:border-box}}
</style>
