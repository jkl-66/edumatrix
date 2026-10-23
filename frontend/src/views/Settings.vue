<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  AlertTriangle,
  BrainCircuit,
  CheckCircle2,
  Eye,
  FileDown,
  Heart,
  History,
  Image,
  Loader2,
  Mic,
  Pencil,
  Plus,
  RotateCw,
  Save,
  ShieldCheck,
  Trash2,
  Volume2,
  X,
} from '@lucide/vue'
import { api, buildHeaders } from '../api/common'
import {
  createLongTermMemory,
  getLongTermMemories,
  getMemoryAudit,
  getMemorySubscriptions,
  revokeProfileMemorySubscription,
  saveProfileMemorySubscription,
  updateLongTermMemory,
  withdrawLongTermMemory,
} from '../api/nextCore'
import TaskState from '../components/TaskState.vue'
import { translateError } from '../services/errorTranslator'

const role = localStorage.getItem('edumatrix_role') || 'student'
const isAdmin = role === 'admin'
const introCopy = isAdmin
  ? {
      title: '系统能力是否可以正常使用',
      description: '检查文本模型、视觉模型和本地回退状态；凭据只由部署环境提供。',
    }
  : {
      title: '设置系统如何协助你学习',
      description: '偏好只影响资源表达和交互方式，不会直接改变掌握度。',
    }

const teachingStyle = ref(localStorage.getItem('edumatrix_teaching_style') || 'socratic')
const responseDepth = ref(localStorage.getItem('edumatrix_response_depth') || 'focused')
const imageAnalysis = ref(localStorage.getItem('edumatrix_multimodal_image_enabled') !== 'false')
const speechInput = ref(localStorage.getItem('edumatrix_speech_input_enabled') !== 'false')
const readAloud = ref(localStorage.getItem('edumatrix_read_aloud_enabled') === 'true')
const saved = ref(false)
const dirty = ref(false)

const health = ref(null)
const healthLoading = ref(true)
const testing = ref('')
const testResults = reactive({ text: null, vision: null })

const memoryLoading = ref(false)
const memoryLoaded = ref(false)
const memorySaving = ref(false)
const memoryError = ref('')
const memoryNotice = ref('')
const memories = ref([])
const subscriptions = ref([])
const auditItems = ref([])
const includeWithdrawn = ref(false)
const selectedProfileFields = ref([])
const editingMemoryId = ref('')
const editDraft = reactive({ title: '', content: '' })
const newMemory = reactive({ title: '', memory_type: 'preference', content: '' })

const profileFields = [
  ['major', '专业方向'],
  ['target_course', '目标课程'],
  ['cognitive_style', '认知风格'],
  ['motivation_type', '学习动机'],
  ['learning_goals', '学习目标'],
  ['interaction_preferences', '交互偏好'],
  ['weak_points', '薄弱知识点'],
]

const memoryTypeLabels = {
  preference: '偏好',
  goal: '目标',
  constraint: '约束',
  learning_context: '学习背景',
}

const credits = [
  ['FastAPI', 'MIT'], ['SQLAlchemy', 'MIT'], ['Vue 3', 'MIT'],
  ['Vite', 'MIT'], ['Tailwind CSS', 'MIT'], ['ECharts', 'Apache-2.0'],
  ['KaTeX', 'MIT'], ['FAISS', 'MIT'], ['PyMuPDF', 'AGPL-3.0'],
  ['SQLite', 'Public Domain'], ['Lucide', 'ISC'],
]

const profileSubscription = computed(() => subscriptions.value.find((item) => item.subscriber_key === 'profile'))
const textModel = computed(() => health.value?.dependencies?.text_model)
const visionModel = computed(() => health.value?.dependencies?.vision_model)

watch([teachingStyle, responseDepth, imageAnalysis, speechInput, readAloud], () => {
  dirty.value = true
  saved.value = false
})

function savePreferences() {
  localStorage.setItem('edumatrix_teaching_style', teachingStyle.value)
  localStorage.setItem('edumatrix_response_depth', responseDepth.value)
  localStorage.setItem('edumatrix_multimodal_image_enabled', String(imageAnalysis.value))
  localStorage.setItem('edumatrix_speech_input_enabled', String(speechInput.value))
  localStorage.setItem('edumatrix_read_aloud_enabled', String(readAloud.value))
  dirty.value = false
  saved.value = true
  window.setTimeout(() => { saved.value = false }, 3000)
}

async function loadHealth() {
  healthLoading.value = true
  try {
    health.value = (await api.get('/health')).data
  } catch {
    health.value = { status: 'unavailable', dependencies: {} }
  } finally {
    healthLoading.value = false
  }
}

async function testConnection(kind) {
  testing.value = kind
  testResults[kind] = null
  try {
    const endpoint = kind === 'vision' ? '/llm/test-vision' : '/llm/test'
    testResults[kind] = (await api.get(endpoint, { headers: buildHeaders(), timeout: 30000 })).data
  } catch (error) {
    const translated = translateError(error, `${kind === 'vision' ? '视觉' : '文本'}模型连接测试失败。`)
    testResults[kind] = { status: 'error', message: translated.message }
  } finally {
    testing.value = ''
    await loadHealth()
  }
}

function memoryMessage(error) {
  return translateError(error, '个人记忆服务暂时不可用，其他设置仍可保存。').message
}

async function loadMemoryGovernance() {
  memoryLoading.value = true
  memoryError.value = ''
  try {
    const [memoryData, subscriptionData, auditData] = await Promise.all([
      getLongTermMemories(includeWithdrawn.value),
      getMemorySubscriptions(),
      getMemoryAudit(),
    ])
    memories.value = memoryData.items || []
    subscriptions.value = subscriptionData.items || []
    auditItems.value = auditData.items || []
    selectedProfileFields.value = [...(profileSubscription.value?.profile_fields || [])]
    memoryLoaded.value = true
  } catch (error) {
    memoryError.value = memoryMessage(error)
  } finally {
    memoryLoading.value = false
  }
}

function handleMemoryToggle(event) {
  if (event.currentTarget.open && !memoryLoaded.value && !memoryLoading.value) loadMemoryGovernance()
}

function setMemoryNotice(text) {
  memoryNotice.value = text
  window.setTimeout(() => { memoryNotice.value = '' }, 3000)
}

async function saveSubscription() {
  memorySaving.value = true
  memoryError.value = ''
  try {
    await saveProfileMemorySubscription({
      profile_fields: selectedProfileFields.value,
      expected_version: profileSubscription.value?.lock_version || 0,
    })
    setMemoryNotice('画像同步范围已更新。')
    await loadMemoryGovernance()
  } catch (error) {
    memoryError.value = memoryMessage(error)
  } finally {
    memorySaving.value = false
  }
}

async function revokeSubscription() {
  if (!profileSubscription.value || !window.confirm('确认撤回画像同步及其长期记忆投影？')) return
  memorySaving.value = true
  try {
    await revokeProfileMemorySubscription({
      expected_version: profileSubscription.value.lock_version,
      reason: 'user_revoked_from_settings',
    })
    setMemoryNotice('画像同步已撤回。')
    await loadMemoryGovernance()
  } catch (error) {
    memoryError.value = memoryMessage(error)
  } finally {
    memorySaving.value = false
  }
}

async function addMemory() {
  memorySaving.value = true
  memoryError.value = ''
  try {
    await createLongTermMemory({ ...newMemory, sensitivity: 'personal' })
    newMemory.title = ''
    newMemory.content = ''
    setMemoryNotice('个人记忆已保存。')
    await loadMemoryGovernance()
  } catch (error) {
    memoryError.value = memoryMessage(error)
  } finally {
    memorySaving.value = false
  }
}

function beginEdit(item) {
  editingMemoryId.value = item.id
  editDraft.title = item.title
  editDraft.content = item.content
}

async function saveMemory(item) {
  memorySaving.value = true
  try {
    await updateLongTermMemory(item.id, {
      expected_version: item.lock_version,
      title: editDraft.title,
      content: editDraft.content,
    })
    editingMemoryId.value = ''
    setMemoryNotice('个人记忆已更新。')
    await loadMemoryGovernance()
  } catch (error) {
    memoryError.value = memoryMessage(error)
  } finally {
    memorySaving.value = false
  }
}

async function withdrawMemory(item) {
  if (!window.confirm(`确认撤回“${item.title}”？`)) return
  memorySaving.value = true
  try {
    await withdrawLongTermMemory(item.id, {
      expected_version: item.lock_version,
      reason: 'user_withdrawn_from_settings',
    })
    setMemoryNotice('个人记忆已撤回。')
    await loadMemoryGovernance()
  } catch (error) {
    memoryError.value = memoryMessage(error)
  } finally {
    memorySaving.value = false
  }
}

onMounted(() => {
  localStorage.removeItem('edumatrix_llm_config')
  loadHealth()
})
</script>

<template>
  <div class="settings-page">
    <div class="settings-surface">
      <header class="settings-intro">
      <div>
        <h2>{{ introCopy.title }}</h2>
        <span>{{ introCopy.description }}</span>
      </div>
      <div v-if="!isAdmin" class="settings-save">
        <span v-if="saved"><CheckCircle2 :size="16" /> 已保存</span>
        <button type="button" class="ui-button ui-button--primary" :disabled="!dirty" data-testid="save-settings" @click="savePreferences">
          <Save :size="17" />
          保存当前设置
        </button>
      </div>
      </header>

      <section v-if="!isAdmin" class="settings-section" aria-labelledby="learning-preferences-title">
      <div class="settings-section__heading">
        <div>
          <span>学习偏好</span>
          <h3 id="learning-preferences-title">回答方式</h3>
        </div>
        <p>系统生成讲义和回答时优先采用这些表达方式。</p>
      </div>

      <div class="setting-row">
        <div>
          <strong>教学引导</strong>
          <span>选择先提问引导，还是先给出结构化讲解。</span>
        </div>
        <div class="option-segments" role="radiogroup" aria-label="教学引导方式">
          <label :class="{ active: teachingStyle === 'socratic' }">
            <input v-model="teachingStyle" type="radio" value="socratic" />
            启发提问
          </label>
          <label :class="{ active: teachingStyle === 'formal' }">
            <input v-model="teachingStyle" type="radio" value="formal" />
            系统讲解
          </label>
        </div>
      </div>

      <div class="setting-row">
        <div>
          <strong>回答详细程度</strong>
          <span>需要时仍可在对话中要求展开。</span>
        </div>
        <div class="option-segments" role="radiogroup" aria-label="回答详细程度">
          <label :class="{ active: responseDepth === 'focused' }">
            <input v-model="responseDepth" type="radio" value="focused" />
            聚焦重点
          </label>
          <label :class="{ active: responseDepth === 'detailed' }">
            <input v-model="responseDepth" type="radio" value="detailed" />
            详细推导
          </label>
        </div>
      </div>
      </section>

      <section v-if="!isAdmin" class="settings-section" aria-labelledby="multimodal-title">
      <div class="settings-section__heading">
        <div>
          <span>多模态</span>
          <h3 id="multimodal-title">图片与语音</h3>
        </div>
        <p>关闭后，相应入口会隐藏；已有学习内容不会被删除。</p>
      </div>

      <label class="toggle-row">
        <span class="toggle-row__icon"><Image :size="18" /></span>
        <span><strong>图片理解</strong><small>允许在智能对话和知识库中提交图片区域。</small></span>
        <input v-model="imageAnalysis" type="checkbox" />
      </label>
      <label class="toggle-row">
        <span class="toggle-row__icon"><Mic :size="18" /></span>
        <span><strong>语音输入</strong><small>允许通过麦克风输入问题和费曼复述。</small></span>
        <input v-model="speechInput" type="checkbox" />
      </label>
      <label class="toggle-row">
        <span class="toggle-row__icon"><Volume2 :size="18" /></span>
        <span><strong>朗读回答</strong><small>生成完成后提供朗读动作，不自动播放。</small></span>
        <input v-model="readAloud" type="checkbox" />
      </label>
      </section>

      <section class="settings-section" aria-labelledby="model-status-title">
      <div class="settings-section__heading">
        <div>
          <span>运行连接</span>
          <h3 id="model-status-title">模型状态</h3>
        </div>
        <p>{{ isAdmin ? '模型凭据由部署环境配置，页面只显示脱敏状态。' : '连接由系统管理员统一配置，不需要填写 API Key。' }}</p>
      </div>

      <TaskState v-if="healthLoading" state="loading" title="正在检查运行环境" message="本地页面仍可继续使用。" />
      <template v-else>
        <div class="connection-row">
          <span class="connection-row__icon"><BrainCircuit :size="18" /></span>
          <div>
            <strong>文本模型</strong>
            <span>{{ textModel?.available ? '已连接' : '未连接，系统将使用可用的本地能力' }}</span>
          </div>
          <i :class="{ available: textModel?.available }" />
          <button type="button" class="ui-button ui-button--secondary ui-button--sm" :disabled="testing === 'text'" @click="testConnection('text')">
            <Loader2 v-if="testing === 'text'" :size="16" class="spin" />
            <RotateCw v-else :size="16" />
            测试连接
          </button>
        </div>
        <TaskState
          v-if="testResults.text"
          :state="testResults.text.status === 'ok' ? 'success' : testResults.text.status === 'warning' ? 'warning' : 'error'"
          title="文本模型测试结果"
          :message="testResults.text.message"
        />

        <div class="connection-row">
          <span class="connection-row__icon"><Eye :size="18" /></span>
          <div>
            <strong>视觉模型</strong>
            <span>{{ visionModel?.available ? '已连接' : '未连接，图片分析入口会提示不可用' }}</span>
          </div>
          <i :class="{ available: visionModel?.available }" />
          <button type="button" class="ui-button ui-button--secondary ui-button--sm" :disabled="testing === 'vision'" @click="testConnection('vision')">
            <Loader2 v-if="testing === 'vision'" :size="16" class="spin" />
            <RotateCw v-else :size="16" />
            测试连接
          </button>
        </div>
        <TaskState
          v-if="testResults.vision"
          :state="testResults.vision.status === 'ok' ? 'success' : testResults.vision.status === 'warning' ? 'warning' : 'error'"
          title="视觉模型测试结果"
          :message="testResults.vision.message"
        />
      </template>

      <details v-if="isAdmin" class="settings-disclosure">
        <summary>查看部署配置说明</summary>
        <div class="disclosure-copy">
          <ShieldCheck :size="18" />
          <p>文本与视觉模型的端点、模型名和密钥由后端环境变量提供。浏览器不会保存或回显完整密钥，修改部署配置后需要重启后端服务。</p>
        </div>
      </details>
      </section>

      <details v-if="!isAdmin" class="settings-section settings-disclosure settings-disclosure--major" data-testid="memory-governance" @toggle="handleMemoryToggle">
      <summary>
        <span><BrainCircuit :size="18" /><strong>个人数据与长期记忆</strong></span>
        <small>查看、修改或撤回系统跨会话使用的个人信息</small>
      </summary>

      <div class="memory-body">
        <TaskState v-if="memoryError" state="error" title="个人数据暂未加载" :message="memoryError" data-testid="memory-error" />
        <TaskState v-if="memoryNotice" state="success" title="操作完成" :message="memoryNotice" />
        <div v-if="memoryLoading" class="memory-loading" data-testid="memory-loading"><Loader2 :size="20" class="spin" /> 正在加载个人数据</div>

        <template v-else-if="memoryLoaded">
          <section class="memory-subsection">
            <div class="memory-subsection__heading">
              <div>
                <strong>画像同步范围</strong>
                <span>{{ profileSubscription?.status === 'active' ? `已启用 · 版本 ${profileSubscription.lock_version}` : '尚未启用' }}</span>
              </div>
              <div>
                <button v-if="profileSubscription?.status === 'active'" type="button" class="ui-button ui-button--ghost ui-button--sm" :disabled="memorySaving" @click="revokeSubscription"><Trash2 :size="16" /> 撤回</button>
                <button type="button" class="ui-button ui-button--secondary ui-button--sm" :disabled="memorySaving" @click="saveSubscription"><Save :size="16" /> 保存范围</button>
              </div>
            </div>
            <div class="field-checks">
              <label v-for="field in profileFields" :key="field[0]"><input v-model="selectedProfileFields" type="checkbox" :value="field[0]" /> {{ field[1] }}</label>
            </div>
          </section>

          <section class="memory-subsection">
            <div class="memory-subsection__heading">
              <div><strong>手动添加个人记忆</strong><span>仅用于你希望系统跨会话记住的偏好、目标或约束。</span></div>
            </div>
            <form class="memory-form" @submit.prevent="addMemory">
              <input v-model.trim="newMemory.title" required maxlength="256" class="input" placeholder="标题" aria-label="记忆标题" />
              <select v-model="newMemory.memory_type" class="input" aria-label="记忆类型">
                <option v-for="(label, key) in memoryTypeLabels" :key="key" :value="key">{{ label }}</option>
              </select>
              <textarea v-model.trim="newMemory.content" required maxlength="12000" rows="3" class="input" placeholder="希望系统记住的内容" aria-label="记忆内容" />
              <button class="ui-button ui-button--secondary" :disabled="memorySaving"><Plus :size="16" /> 添加</button>
            </form>
          </section>

          <section class="memory-subsection">
            <div class="memory-subsection__heading">
              <div><strong>已保存记忆</strong><span>撤回后不再用于后续对话和资源生成。</span></div>
              <label class="withdrawn-toggle"><input v-model="includeWithdrawn" type="checkbox" @change="loadMemoryGovernance" /> 显示已撤回</label>
            </div>

            <div v-if="!memories.length" class="memory-empty" data-testid="memory-empty">暂无长期记忆。</div>
            <div v-else class="memory-list" data-testid="memory-list">
              <article v-for="item in memories" :key="item.id" :class="{ withdrawn: item.status !== 'active' }">
                <template v-if="editingMemoryId === item.id">
                  <input v-model.trim="editDraft.title" class="input" aria-label="编辑记忆标题" />
                  <textarea v-model.trim="editDraft.content" rows="3" class="input" aria-label="编辑记忆内容" />
                  <div class="memory-actions"><button type="button" class="ui-button ui-button--ghost ui-button--sm" @click="editingMemoryId = ''"><X :size="16" /> 取消</button><button type="button" class="ui-button ui-button--secondary ui-button--sm" data-testid="memory-edit-save" :disabled="memorySaving" @click="saveMemory(item)"><Save :size="16" /> 保存</button></div>
                </template>
                <template v-else>
                  <div class="memory-copy">
                    <div><strong>{{ item.title }}</strong><span>{{ memoryTypeLabels[item.memory_type] || item.memory_type }} · 版本 {{ item.lock_version }}</span></div>
                    <p>{{ item.content }}</p>
                  </div>
                  <div v-if="item.status === 'active'" class="memory-icon-actions">
                    <button v-if="item.source_type === 'manual'" type="button" title="编辑记忆" aria-label="编辑记忆" @click="beginEdit(item)"><Pencil :size="16" /></button>
                    <button type="button" title="撤回记忆" aria-label="撤回记忆" @click="withdrawMemory(item)"><Trash2 :size="16" /></button>
                  </div>
                </template>
              </article>
            </div>
          </section>

          <details class="audit-disclosure">
            <summary><History :size="16" /> 操作记录（{{ auditItems.length }}）</summary>
            <div class="audit-list">
              <p v-if="!auditItems.length">暂无操作记录。</p>
              <div v-for="item in auditItems" :key="item.id"><strong>{{ item.action }}</strong><span>{{ item.created_at?.replace('T', ' ').slice(0, 19) }}</span></div>
            </div>
          </details>
        </template>
      </div>
      </details>

      <details class="settings-section settings-disclosure settings-disclosure--major">
      <summary>
        <span><Heart :size="18" /><strong>开源组件与许可</strong></span>
        <small>查看本项目使用的主要开源组件</small>
      </summary>
      <div class="credits-list">
        <div v-for="dependency in credits" :key="dependency[0]"><strong>{{ dependency[0] }}</strong><span>{{ dependency[1] }}</span></div>
      </div>
      </details>
    </div>
  </div>
</template>

<style scoped>
.settings-page {
  width: min(100%, 1180px);
  margin: 0 auto;
  padding: 30px 34px 72px;
}

.settings-surface {
  overflow: hidden;
  border: 1px solid var(--color-border);
  border-radius: 12px;
  background: var(--color-surface);
  box-shadow: 0 10px 30px rgb(6 20 27 / 5%);
}

.settings-intro {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 32px;
  padding: 28px 34px 26px;
  border-bottom: 1px solid var(--color-border);
}

.settings-intro p,
.settings-intro h2,
.settings-intro span {
  margin: 0;
}

.settings-intro p,
.settings-section__heading span {
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 600;
}

.settings-intro h2 {
  margin-top: 4px;
  font-size: 24px;
  font-weight: 650;
  line-height: 1.4;
}

.settings-intro > div:first-child > span {
  display: block;
  margin-top: 6px;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.settings-save {
  display: flex;
  align-items: center;
  gap: 14px;
}

.settings-save > span {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--color-success);
  font-size: 14px;
}

.settings-section {
  padding: 28px 34px;
  border-bottom: 1px solid var(--color-border);
}

.settings-surface > .settings-section:last-child {
  border-bottom: 0;
}

.settings-section__heading {
  display: grid;
  grid-template-columns: minmax(260px, 0.65fr) minmax(360px, 1fr);
  gap: 40px;
  margin-bottom: 18px;
}

.settings-section__heading h3 {
  margin: 3px 0 0;
  font-size: 18px;
  font-weight: 650;
}

.settings-section__heading p {
  margin: 22px 0 0;
  color: var(--color-text-secondary);
  font-size: 14px;
}

.setting-row,
.toggle-row,
.connection-row {
  display: grid;
  min-height: 66px;
  align-items: center;
  gap: 24px;
  border-top: 1px solid #eceef0;
}

.setting-row {
  grid-template-columns: minmax(300px, 1fr) auto;
}

.setting-row > div:first-child,
.toggle-row > span:nth-child(2),
.connection-row > div {
  display: grid;
  gap: 2px;
}

.setting-row strong,
.toggle-row strong,
.connection-row strong {
  font-size: 15px;
  font-weight: 620;
}

.setting-row span,
.toggle-row small,
.connection-row span {
  color: var(--color-text-secondary);
  font-size: 14px;
}

.option-segments {
  display: grid;
  grid-template-columns: 1fr 1fr;
  padding: 3px;
  border: 1px solid var(--color-border-strong);
  border-radius: 6px;
  background: var(--color-surface-subtle);
}

.option-segments label {
  display: grid;
  min-width: 112px;
  min-height: 36px;
  place-items: center;
  padding: 0 12px;
  color: var(--color-text-secondary);
  border-radius: 4px;
  font-size: 14px;
  cursor: pointer;
}

.option-segments label.active {
  color: #ffffff;
  background: #292b2e;
  font-weight: 600;
}

.option-segments input {
  position: absolute;
  opacity: 0;
  pointer-events: none;
}

.toggle-row {
  grid-template-columns: 38px minmax(0, 1fr) auto;
  cursor: pointer;
}

.toggle-row__icon,
.connection-row__icon {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  color: var(--color-accent);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface-subtle);
}

.toggle-row input,
.field-checks input,
.withdrawn-toggle input {
  width: 17px;
  height: 17px;
  accent-color: #292b2e;
}

.connection-row {
  grid-template-columns: 38px minmax(0, 1fr) 12px auto;
}

.connection-row > i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #b4b8bd;
}

.connection-row > i.available {
  background: var(--color-success);
}

.spin {
  animation: settings-spin 900ms linear infinite;
}

@keyframes settings-spin {
  to { transform: rotate(360deg); }
}

.settings-disclosure {
  margin-top: 14px;
}

.settings-disclosure summary {
  color: var(--color-text-secondary);
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.settings-disclosure--major {
  margin: 0;
}

.settings-disclosure--major > summary {
  display: grid;
  grid-template-columns: minmax(280px, 0.65fr) minmax(380px, 1fr);
  gap: 40px;
  color: var(--color-text);
  list-style-position: outside;
}

.settings-disclosure--major > summary > span {
  display: flex;
  align-items: center;
  gap: 9px;
}

.settings-disclosure--major > summary strong {
  font-size: 17px;
  font-weight: 650;
}

.settings-disclosure--major > summary small {
  color: var(--color-text-secondary);
  font-size: 14px;
  font-weight: 400;
}

.disclosure-copy {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-top: 12px;
  padding: 13px 14px;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: var(--color-surface-subtle);
}

.disclosure-copy p {
  margin: 0;
  font-size: 14px;
}

.memory-body {
  padding-top: 22px;
}

.memory-loading,
.memory-empty {
  display: flex;
  min-height: 84px;
  align-items: center;
  justify-content: center;
  gap: 9px;
  color: var(--color-text-muted);
  border: 1px dashed var(--color-border-strong);
  font-size: 14px;
}

.memory-subsection {
  padding: 20px 0;
  border-top: 1px solid #eceef0;
}

.memory-subsection__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 14px;
}

.memory-subsection__heading > div:first-child {
  display: grid;
}

.memory-subsection__heading > div:last-child {
  display: flex;
  gap: 8px;
}

.memory-subsection__heading strong,
.memory-subsection__heading span,
.withdrawn-toggle {
  font-size: 14px;
}

.memory-subsection__heading span {
  color: var(--color-text-secondary);
}

.field-checks {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.field-checks label {
  display: flex;
  min-height: 40px;
  align-items: center;
  gap: 8px;
  padding: 0 10px;
  border: 1px solid var(--color-border);
  border-radius: 6px;
  font-size: 14px;
}

.memory-form {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) 160px auto;
  gap: 10px;
}

.memory-form textarea {
  grid-column: 1 / 3;
  padding: 10px 12px;
  resize: vertical;
}

.memory-form > button {
  grid-row: 1 / 3;
  grid-column: 3;
}

.withdrawn-toggle {
  display: flex;
  align-items: center;
  gap: 7px;
  color: var(--color-text-secondary);
}

.memory-list article {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  padding: 14px 0;
  border-top: 1px solid #eceef0;
}

.memory-list article.withdrawn {
  opacity: 0.62;
}

.memory-list article:has(> input) {
  grid-template-columns: 1fr;
}

.memory-copy > div {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.memory-copy strong,
.memory-copy span,
.memory-copy p {
  font-size: 14px;
}

.memory-copy span {
  color: var(--color-text-muted);
}

.memory-copy p {
  margin: 5px 0 0;
  color: var(--color-text-secondary);
  white-space: pre-wrap;
}

.memory-icon-actions,
.memory-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
}

.memory-icon-actions button {
  display: grid;
  width: 34px;
  height: 34px;
  place-items: center;
  color: var(--color-text-secondary);
  border: 1px solid var(--color-border);
  border-radius: 6px;
  background: #ffffff;
  cursor: pointer;
}

.audit-disclosure {
  margin-top: 12px;
  padding-top: 14px;
  border-top: 1px solid #eceef0;
}

.audit-disclosure summary {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 14px;
  font-weight: 600;
  cursor: pointer;
}

.audit-list {
  max-height: 240px;
  margin-top: 10px;
  overflow: auto;
}

.audit-list > div {
  display: flex;
  justify-content: space-between;
  padding: 9px 0;
  border-top: 1px solid #eceef0;
}

.audit-list p,
.audit-list strong,
.audit-list span {
  color: var(--color-text-secondary);
  font-size: 14px;
}

.credits-list {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0;
  margin-top: 20px;
  border-top: 1px solid #eceef0;
  border-left: 1px solid #eceef0;
}

.credits-list > div {
  display: grid;
  padding: 12px;
  border-right: 1px solid #eceef0;
  border-bottom: 1px solid #eceef0;
}

.credits-list strong,
.credits-list span {
  font-size: 14px;
}

.credits-list span {
  color: var(--color-text-muted);
}
</style>
