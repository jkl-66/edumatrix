<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  AlertTriangle, ArrowLeft, ArrowRight, BookOpen, Boxes, Check, CheckCircle2,
  ChevronRight, ExternalLink, FileText, Heart, Library, ListFilter, LoaderCircle,
  PackageOpen, Plus, RefreshCw, Route as RouteIcon, Search, ShieldCheck, Store,
} from '@lucide/vue'
import {
  acquireMarketplaceListing, getMarketplaceListing, getMarketplaceWorkspace,
  searchMarketplace, setMarketplaceFavorite, submitMarketplaceListing,
} from '../api/marketplace'
import SearchField from '../components/ui/SearchField.vue'

const route = useRoute()
const router = useRouter()
const workspace = ref(null)
const items = ref([])
const selected = ref(null)
const loading = ref(true)
const detailLoading = ref(false)
const busy = ref('')
const error = ref('')
const detailError = ref('')
const notice = ref('')
const query = ref('')
const category = ref('')
const itemType = ref('')
const mineTab = ref('copies')
const publishStep = ref(1)
const publishedResult = ref(null)
const draft = ref({
  item_type: 'resource',
  source_object_id: '',
  title: '',
  summary: '',
  category: '人工智能',
  tags: '',
})

const typeOptions = [
  { value: '', label: '全部', icon: Store },
  { value: 'resource', label: '单份资源', icon: FileText },
  { value: 'resource_bundle', label: '资源包', icon: Boxes },
  { value: 'learning_path', label: '学习路径', icon: RouteIcon },
  { value: 'course', label: '完整课程', icon: BookOpen },
]
const publishTypes = typeOptions.filter((item) => ['resource', 'resource_bundle', 'learning_path'].includes(item.value))
const isPublish = computed(() => route.name === 'MarketplacePublish')
const isMine = computed(() => route.name === 'MarketplaceMine')
const isDiscover = computed(() => !isPublish.value && !isMine.value)
const categories = computed(() => Array.from(new Set(items.value.map((item) => item.category).filter(Boolean))).sort())
const publishableSources = computed(() => workspace.value?.publishable_sources?.[draft.value.item_type] || [])
const selectedSource = computed(() => publishableSources.value.find((item) => item.id === draft.value.source_object_id) || null)
const provenance = computed(() => selectedSource.value?.provenance || null)
const favoriteItems = computed(() => (workspace.value?.published || []).filter((item) => item.engagement?.is_favorited))
const managedItems = computed(() => workspace.value?.managed || [])
const personalCopies = computed(() => workspace.value?.personal_copies || [])
const mineItems = computed(() => {
  if (mineTab.value === 'published') return managedItems.value
  if (mineTab.value === 'favorites') return favoriteItems.value
  return personalCopies.value
})
const currentType = computed(() => typeOptions.find((item) => item.value === selected.value?.item_type) || typeOptions[0])
const selectedSavedCopy = computed(() => selected.value?.saved_copy || null)
const previewItems = computed(() => selected.value?.preview?.included_items || [])
const publishPreviewItems = computed(() => selectedSource.value?.preview?.included_items || [])
const pageHeading = computed(() => {
  if (isPublish.value) return { eyebrow: '发布学习内容', title: '分享一份可复用的学习成果', copy: '选择个人内容、确认来源，再提交公开审核。原内容不会被修改。' }
  if (isMine.value) return { eyebrow: '我的学习市场', title: '管理分享、收藏与个人副本', copy: '个人副本独立保存，上游更新或下架不会覆盖你的内容。' }
  return { eyebrow: '学习市场', title: '发现值得继续学习的内容', copy: '预览来源清晰的资源、资源包和学习路径，再保存为自己的学习副本。' }
})

function message(exception, fallback = '操作失败，请稍后重试。') {
  const detail = exception?.response?.data?.detail || exception?.detail
  return detail?.message || (typeof detail === 'string' ? detail : '') || exception?.message || fallback
}
function typeLabel(value) { return typeOptions.find((item) => item.value === value)?.label || '学习内容' }
function typeIcon(value) { return typeOptions.find((item) => item.value === value)?.icon || PackageOpen }
function statusLabel(value) {
  return {
    pending: '等待审核', changes_requested: '需要修改', approved: '等待公开',
    published: '已公开', withdrawn: '已下架', available: '来源可用',
  }[value] || value || '状态未知'
}
function openRoute(path) { if (path) router.push(path) }

async function loadWorkspace() {
  workspace.value = await getMarketplaceWorkspace()
  items.value = workspace.value.published || []
}
async function loadSelected(itemId = route.params.itemId) {
  if (!itemId) {
    selected.value = null
    detailError.value = ''
    return
  }
  detailLoading.value = true
  detailError.value = ''
  try {
    selected.value = await getMarketplaceListing(String(itemId))
  } catch (exception) {
    selected.value = null
    detailError.value = message(exception, '这份内容已不可公开查看。')
  } finally {
    detailLoading.value = false
  }
}
async function load() {
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    await loadWorkspace()
    if (isDiscover.value) await loadSelected()
  } catch (exception) {
    error.value = message(exception, '学习市场暂时无法加载。')
  } finally {
    loading.value = false
  }
}
async function runSearch() {
  busy.value = 'search'
  error.value = ''
  try {
    const result = await searchMarketplace({
      q: query.value.trim(),
      category: category.value,
      item_type: itemType.value || undefined,
    })
    items.value = result.items || []
  } catch (exception) {
    error.value = message(exception, '筛选失败，原结果仍保留。')
  } finally {
    busy.value = ''
  }
}
function selectType(value) { itemType.value = value; runSearch() }
function clearFilters() { query.value = ''; category.value = ''; itemType.value = ''; runSearch() }
function selectItem(item) { router.push({ name: 'MarketplaceItem', params: { itemId: item.id } }) }

async function saveCopy() {
  if (!selected.value || busy.value) return
  busy.value = 'save'
  detailError.value = ''
  try {
    const result = await acquireMarketplaceListing(selected.value.id)
    const target = result.open_route || (result.derived_course_id ? `/knowledge/courses/${result.derived_course_id}` : '')
    notice.value = '已保存为独立个人副本，可以从学习空间继续。'
    await loadWorkspace()
    await loadSelected(selected.value.id)
    if (!selected.value.saved_copy && target) selected.value = { ...selected.value, saved_copy: { ...result, open_route: target } }
  } catch (exception) {
    detailError.value = message(exception, '保存失败，当前预览和选择不会丢失。')
  } finally {
    busy.value = ''
  }
}
async function toggleFavorite() {
  if (!selected.value || busy.value) return
  busy.value = 'favorite'
  detailError.value = ''
  try {
    const active = !selected.value.engagement?.is_favorited
    await setMarketplaceFavorite(selected.value.id, { active, expected_version: null })
    selected.value.engagement = { ...(selected.value.engagement || {}), is_favorited: active }
    notice.value = active ? '已加入收藏。' : '已取消收藏。'
    await loadWorkspace()
  } catch (exception) {
    detailError.value = message(exception, '收藏状态更新失败。')
  } finally {
    busy.value = ''
  }
}

function choosePublishType(value) {
  draft.value.item_type = value
  draft.value.source_object_id = ''
  publishedResult.value = null
  error.value = ''
}
function selectPublishSource(source) {
  draft.value.source_object_id = source.id
  if (!draft.value.title) draft.value.title = source.title
}
function nextPublishStep() {
  error.value = ''
  if (publishStep.value === 1) {
    publishStep.value = 2
    return
  }
  if (!selectedSource.value) {
    error.value = '请先选择一份要分享的个人内容。'
    return
  }
  if (!provenance.value?.complete) {
    error.value = '当前内容的来源或许可信息不完整，暂时不能公开发布。'
    return
  }
  if (!draft.value.title.trim() || draft.value.summary.trim().length < 8 || !draft.value.category.trim()) {
    error.value = '请补全标题、分类和不少于 8 个字的分享说明。'
    return
  }
  publishStep.value = 3
}
async function submitPublication() {
  if (!selectedSource.value || busy.value) return
  busy.value = 'publish'
  error.value = ''
  try {
    publishedResult.value = await submitMarketplaceListing({
      item_type: draft.value.item_type,
      source_object_id: selectedSource.value.id,
      source_version_id: selectedSource.value.version_id,
      title: draft.value.title.trim(),
      summary: draft.value.summary.trim(),
      category: draft.value.category.trim(),
      tags: draft.value.tags.split(',').map((tag) => tag.trim()).filter(Boolean),
    })
    notice.value = '已提交公开审核。个人原件和版本历史保持不变。'
    await loadWorkspace()
  } catch (exception) {
    error.value = message(exception, '提交失败，已填写内容仍然保留。')
  } finally {
    busy.value = ''
  }
}

onMounted(load)
</script>

<template>
  <main class="market-page" data-testid="marketplace-workspace">
    <header class="page-head">
      <div>
        <p class="eyebrow">{{ pageHeading.eyebrow }}</p>
        <h1>{{ pageHeading.title }}</h1>
        <p class="page-copy">{{ pageHeading.copy }}</p>
      </div>
      <nav class="page-actions" aria-label="学习市场页面">
        <button type="button" :class="{ active: isDiscover }" @click="router.push('/marketplace')"><Store :size="17" /> 发现</button>
        <button type="button" :class="{ active: isMine }" @click="router.push('/marketplace/mine')"><Library :size="17" /> 我的内容</button>
        <button type="button" class="publish-button" :class="{ secondary: !isDiscover || selected }" @click="router.push('/marketplace/publish')"><Plus :size="17" /> 发布</button>
      </nav>
    </header>

    <p v-if="notice" class="feedback feedback--success" role="status"><CheckCircle2 :size="18" /> {{ notice }}</p>
    <p v-if="error" class="feedback feedback--error" role="alert"><AlertTriangle :size="18" /> {{ error }}</p>

    <section v-if="loading" class="loading-surface" aria-live="polite">
      <LoaderCircle class="spin" :size="24" />
      <div><strong>正在打开学习市场</strong><span>保留页面位置，完成后即可继续。</span></div>
    </section>
    <section v-else-if="error && !workspace" class="error-surface">
      <AlertTriangle :size="24" />
      <div><h2>暂时无法进入学习市场</h2><p>你的学习内容没有被修改，可以重新加载。</p></div>
      <button type="button" class="secondary-button" @click="load"><RefreshCw :size="17" /> 重新加载</button>
    </section>

    <template v-else-if="workspace && isDiscover">
      <section class="filter-bar" aria-label="筛选学习内容">
        <SearchField v-model="query" class="market-search-field" style="flex: 1" placeholder="搜索标题、知识点或标签" aria-label="搜索学习市场" @keydown.enter="runSearch" />
        <div class="type-filter" aria-label="内容类型">
          <button v-for="option in typeOptions" :key="option.value" type="button" :class="{ active: itemType === option.value }" @click="selectType(option.value)">
            <component :is="option.icon" :size="16" /> {{ option.label }}
          </button>
        </div>
        <label class="category-filter"><ListFilter :size="17" /><select v-model="category" aria-label="课程分类" @change="runSearch"><option value="">全部分类</option><option v-for="option in categories" :key="option" :value="option">{{ option }}</option></select></label>
      </section>

      <section class="market-layout">
        <div class="catalog-surface">
          <div class="section-heading">
            <div><h2>公开分享</h2><p>{{ items.length }} 份可预览内容</p></div>
            <button type="button" class="icon-button" title="刷新结果" aria-label="刷新市场结果" :disabled="busy === 'search'" @click="runSearch"><RefreshCw :class="{ spin: busy === 'search' }" :size="17" /></button>
          </div>
          <div v-if="items.length" class="market-list">
            <button v-for="item in items" :key="item.id" type="button" class="market-row" :class="{ selected: selected?.id === item.id }" @click="selectItem(item)">
              <span class="type-icon"><component :is="typeIcon(item.item_type)" :size="19" /></span>
              <span class="row-main">
                <span class="row-meta"><b>{{ typeLabel(item.item_type) }}</b><span>{{ item.category }}</span></span>
                <strong>{{ item.title }}</strong>
                <span class="row-summary">{{ item.summary }}</span>
                <span class="row-tags"><i v-for="tag in item.tags?.slice(0, 3)" :key="tag">{{ tag }}</i></span>
              </span>
              <span class="row-side"><span>{{ item.provenance?.course_title || '来源课程' }}</span><span>{{ item.saved_copy ? '已保存' : '可保存副本' }}</span><ChevronRight :size="18" /></span>
            </button>
          </div>
          <div v-else class="empty-surface">
            <Search :size="24" /><strong>没有找到符合条件的内容</strong>
            <p>调整关键词或类型，已保存的个人副本不会受影响。</p>
            <button type="button" class="secondary-button" @click="clearFilters">清空筛选</button>
          </div>
        </div>

        <aside class="preview-surface" data-testid="marketplace-preview">
          <div v-if="detailLoading" class="preview-loading"><LoaderCircle class="spin" :size="22" /><span>正在加载预览</span></div>
          <div v-else-if="detailError && !selected" class="preview-empty" role="alert">
            <AlertTriangle :size="24" /><strong>这份分享当前不可查看</strong><p>{{ detailError }}</p>
            <button type="button" class="secondary-button" @click="router.push('/marketplace')">返回市场</button>
          </div>
          <div v-else-if="selected" class="preview-content">
            <div class="preview-type"><component :is="currentType.icon" :size="17" />{{ currentType.label }}</div>
            <h2>{{ selected.title }}</h2>
            <p class="preview-author">来自 {{ selected.provenance?.course_title || selected.author?.public_id || '公开分享者' }}</p>
            <p class="preview-summary">{{ selected.summary }}</p>
            <dl class="preview-metrics">
              <div><dt>版本</dt><dd>{{ selected.course_version || '冻结版本' }}</dd></div>
              <div><dt>包含</dt><dd>{{ selected.preview?.document_count ?? selected.preview?.node_count ?? previewItems.length }} 项</dd></div>
              <div><dt>保存状态</dt><dd>{{ selectedSavedCopy ? '已加入个人空间' : '尚未保存' }}</dd></div>
            </dl>
            <section v-if="previewItems.length" class="included-list">
              <h3>包含内容</h3>
              <div v-for="(item, index) in previewItems.slice(0, 6)" :key="`${item.title}-${index}`"><span>{{ index + 1 }}</span><p>{{ item.title }}</p></div>
            </section>
            <section class="source-panel">
              <div><ShieldCheck :size="18" /><strong>来源与许可</strong></div>
              <p>{{ selected.provenance?.source_label || '来源说明待补充' }}</p>
              <span>{{ selected.provenance?.license_label || selected.license?.course_license || '许可信息待补充' }}</span>
              <em v-if="selected.provenance?.is_demo_data">{{ selected.provenance.demo_label || '演示数据' }}</em>
            </section>
            <p v-if="detailError" class="inline-error"><AlertTriangle :size="16" />{{ detailError }}</p>
            <div class="preview-actions">
              <button type="button" class="icon-button" :title="selected.engagement?.is_favorited ? '取消收藏' : '收藏'" :aria-label="selected.engagement?.is_favorited ? '取消收藏' : '收藏'" @click="toggleFavorite"><Heart :size="19" :fill="selected.engagement?.is_favorited ? 'currentColor' : 'none'" /></button>
              <button v-if="selectedSavedCopy" type="button" class="primary-button" @click="openRoute(selectedSavedCopy.open_route)">打开个人副本 <ExternalLink :size="17" /></button>
              <button v-else type="button" class="primary-button" :disabled="Boolean(busy)" @click="saveCopy"><LoaderCircle v-if="busy === 'save'" class="spin" :size="17" /><PackageOpen v-else :size="17" /> 保存到学习空间</button>
            </div>
          </div>
          <div v-else class="preview-empty"><PackageOpen :size="28" /><strong>选择一份内容查看概览</strong><p>先看包含内容与来源，再决定是否保存个人副本。</p></div>
        </aside>
      </section>
    </template>

    <section v-else-if="workspace && isPublish" class="publish-surface" data-testid="marketplace-publish-wizard">
      <ol class="wizard-steps" aria-label="发布步骤">
        <li v-for="step in 3" :key="step" :class="{ active: publishStep === step, done: publishStep > step || publishedResult }">
          <span><Check v-if="publishStep > step || publishedResult" :size="15" /><template v-else>{{ step }}</template></span>
          <div><strong>{{ ['选择类型', '选择内容并说明', '确认并提交'][step - 1] }}</strong><small>{{ ['确定分享什么', '使用个人冻结版本', '核对来源与公开信息'][step - 1] }}</small></div>
        </li>
      </ol>
      <div v-if="publishedResult" class="publish-complete">
        <CheckCircle2 :size="30" /><h2>已提交公开审核</h2>
        <p>发布的是冻结副本，不会修改你的个人原件。审核完成前可在“我的内容”查看状态。</p>
        <button type="button" class="primary-button" @click="router.push('/marketplace/mine')">查看我的发布 <ArrowRight :size="17" /></button>
      </div>
      <template v-else>
        <div v-if="publishStep === 1" class="publish-step">
          <div class="step-heading"><h2>选择发布类型</h2><p>三类内容保持独立身份，保存后会进入对应学习空间。</p></div>
          <div class="publish-type-grid">
            <label v-for="option in publishTypes" :key="option.value" :class="{ selected: draft.item_type === option.value }">
              <input :checked="draft.item_type === option.value" type="radio" name="publish-type" :value="option.value" @change="choosePublishType(option.value)" />
              <component :is="option.icon" :size="22" /><strong>{{ option.label }}</strong>
              <span>{{ option.value === 'resource' ? '分享一份讲义、测验或其他学习资源' : option.value === 'resource_bundle' ? '分享一组按目标组织的资源' : '分享一条有顺序的个人学习路径' }}</span>
            </label>
          </div>
        </div>
        <div v-else-if="publishStep === 2" class="publish-step publish-editor">
          <section class="source-selector">
            <div class="step-heading"><h2>选择个人内容</h2><p>只显示你拥有且已冻结当前版本的{{ typeLabel(draft.item_type) }}。</p></div>
            <div v-if="publishableSources.length" class="source-list">
              <button v-for="source in publishableSources" :key="source.id" type="button" :class="{ selected: draft.source_object_id === source.id }" @click="selectPublishSource(source)">
                <span><component :is="typeIcon(draft.item_type)" :size="18" /></span>
                <span><strong>{{ source.title }}</strong><small>{{ source.course.title }} · v{{ source.course.version }}</small></span>
                <Check v-if="draft.source_object_id === source.id" :size="18" />
              </button>
            </div>
            <div v-else class="empty-surface compact"><PackageOpen :size="22" /><strong>暂无可发布的{{ typeLabel(draft.item_type) }}</strong><p>先在学习空间生成或保存一份完整内容。</p><button type="button" class="secondary-button" @click="router.push('/workspace/resources')">前往资源中心</button></div>
          </section>
          <section class="publication-form">
            <label>发布标题<input v-model="draft.title" maxlength="256" placeholder="让学习者一眼看懂内容" /></label>
            <div class="form-row"><label>分类<input v-model="draft.category" maxlength="128" /></label><label>标签<input v-model="draft.tags" maxlength="180" placeholder="例如：机器学习, 模型评估" /></label></div>
            <label>分享说明<textarea v-model="draft.summary" maxlength="4000" placeholder="说明适合谁、解决什么学习问题，至少 8 个字。" /></label>
            <div v-if="selectedSource" class="source-check" :class="{ incomplete: !provenance?.complete }">
              <ShieldCheck :size="19" /><div><strong>{{ provenance?.complete ? '来源信息完整' : '来源信息需要补充' }}</strong><p>{{ provenance?.source_label || '缺少来源说明' }} · {{ provenance?.license_label || '缺少许可信息' }}</p></div>
            </div>
          </section>
        </div>
        <div v-else class="publish-step publish-review">
          <section>
            <p class="preview-type"><component :is="typeIcon(draft.item_type)" :size="17" />{{ typeLabel(draft.item_type) }}</p>
            <h2>{{ draft.title }}</h2><p>{{ draft.summary }}</p>
            <div class="review-tags"><span>{{ draft.category }}</span><span v-for="tag in draft.tags.split(',').map((value) => value.trim()).filter(Boolean)" :key="tag">{{ tag }}</span></div>
            <div v-if="publishPreviewItems.length" class="included-list"><h3>预览包含内容</h3><div v-for="(item, index) in publishPreviewItems.slice(0, 6)" :key="`${item.title}-${index}`"><span>{{ index + 1 }}</span><p>{{ item.title }}</p></div></div>
          </section>
          <aside class="source-panel">
            <div><ShieldCheck :size="18" /><strong>发布前确认</strong></div>
            <p>{{ provenance?.course_title }} · v{{ provenance?.course_version }}</p><span>{{ provenance?.source_label }}</span><span>{{ provenance?.license_label }}</span>
            <em v-if="provenance?.is_demo_data">{{ provenance.demo_label || '演示数据' }}</em><small>{{ provenance?.legal_boundary }}</small>
          </aside>
        </div>
        <footer class="wizard-actions">
          <button v-if="publishStep > 1" type="button" class="secondary-button" :disabled="Boolean(busy)" @click="publishStep -= 1"><ArrowLeft :size="17" /> 上一步</button><span v-else />
          <button v-if="publishStep < 3" type="button" class="primary-button" @click="nextPublishStep">下一步 <ArrowRight :size="17" /></button>
          <button v-else type="button" class="primary-button" :disabled="Boolean(busy) || !provenance?.complete" @click="submitPublication"><LoaderCircle v-if="busy === 'publish'" class="spin" :size="17" /><Store v-else :size="17" /> 提交公开审核</button>
        </footer>
      </template>
    </section>

    <section v-else-if="workspace && isMine" class="mine-surface" data-testid="marketplace-mine">
      <div class="mine-tabs" role="tablist" aria-label="我的市场内容">
        <button type="button" :class="{ active: mineTab === 'copies' }" @click="mineTab = 'copies'">个人副本 <span>{{ personalCopies.length }}</span></button>
        <button type="button" :class="{ active: mineTab === 'published' }" @click="mineTab = 'published'">我的发布 <span>{{ managedItems.length }}</span></button>
        <button type="button" :class="{ active: mineTab === 'favorites' }" @click="mineTab = 'favorites'">收藏 <span>{{ favoriteItems.length }}</span></button>
      </div>
      <div v-if="mineItems.length" class="mine-list">
        <article v-for="item in mineItems" :key="item.id" class="mine-row">
          <span class="type-icon"><component :is="typeIcon(item.item_type)" :size="19" /></span>
          <div>
            <span class="row-meta"><b>{{ typeLabel(item.item_type) }}</b><span>{{ statusLabel(item.source_status || item.status) }}</span></span>
            <strong>{{ item.title || item.copy_object_id }}</strong>
            <p v-if="item.source_status === 'withdrawn'">来源已下架，个人副本仍可继续使用。</p>
            <p v-else-if="mineTab === 'copies'">保存于 {{ item.created_at ? new Date(item.created_at).toLocaleDateString('zh-CN') : '个人空间' }}</p>
            <p v-else>{{ item.summary }}</p>
          </div>
          <button v-if="mineTab === 'copies'" type="button" class="secondary-button" @click="openRoute(item.open_route)">打开个人副本 <ExternalLink :size="16" /></button>
          <button v-else type="button" class="secondary-button" @click="selectItem(item)">查看详情 <ChevronRight :size="16" /></button>
        </article>
      </div>
      <div v-else class="empty-surface">
        <Library :size="25" /><strong>{{ mineTab === 'copies' ? '还没有个人副本' : mineTab === 'published' ? '还没有发布记录' : '还没有收藏内容' }}</strong>
        <p>{{ mineTab === 'copies' ? '从市场预览内容并保存后，会在这里形成独立副本。' : '返回发现页继续浏览可学习内容。' }}</p>
        <button type="button" class="primary-button" @click="router.push('/marketplace')">返回市场</button>
      </div>
    </section>
  </main>
</template>

<style scoped>
.market-page{width:min(1180px,calc(100% - 48px));margin:0 auto;padding:26px 0 48px;color:var(--color-text)}
.page-head{display:flex;align-items:flex-start;justify-content:space-between;gap:32px;padding-bottom:22px;border-bottom:1px solid var(--color-border)}
.eyebrow{margin:0 0 6px;color:var(--color-text-secondary);font-size:14px;font-weight:650}.page-head h1{margin:0;font-family:var(--font-heading);font-size:32px;line-height:1.3}.page-copy{max-width:660px;margin:8px 0 0;color:var(--color-text-secondary);font-size:15px;line-height:1.6}
.page-actions{display:flex;gap:8px}.page-actions button,.secondary-button,.primary-button,.icon-button{display:inline-flex;min-height:40px;align-items:center;justify-content:center;gap:7px;padding:0 14px;border:1px solid var(--color-border-strong);border-radius:var(--radius-control);background:var(--color-surface);color:var(--color-text);font-size:14px;font-weight:650;cursor:pointer}.page-actions button.active{background:var(--color-surface-subtle)}.page-actions .publish-button,.primary-button{color:#fff;border-color:var(--color-accent);background:var(--color-accent)}.page-actions .publish-button.secondary{color:var(--color-text);border-color:var(--color-border-strong);background:var(--color-surface)}button:disabled{opacity:.5;cursor:not-allowed}.icon-button{width:40px;padding:0}
.feedback{display:flex;align-items:center;gap:8px;margin:14px 0 0;padding:11px 13px;border:1px solid var(--color-border);border-radius:var(--radius-control);background:var(--color-accent-soft);font-size:14px}.feedback--error,.inline-error{color:var(--color-danger);border-color:#e8caca;background:var(--color-danger-soft)}
.loading-surface,.error-surface{display:flex;align-items:center;gap:16px;margin-top:18px;padding:28px;border:1px solid var(--color-border);border-radius:var(--radius-panel);background:var(--color-surface)}.loading-surface strong,.loading-surface span{display:block}.loading-surface span,.error-surface p{margin:4px 0 0;color:var(--color-text-secondary);font-size:14px}.error-surface div{flex:1}.error-surface h2{margin:0;font-size:20px}
.filter-bar{display:grid;grid-template-columns:minmax(230px,1fr) auto 180px;gap:10px;align-items:center;margin:18px 0 12px}.search-field,.category-filter{display:flex;min-height:42px;align-items:center;gap:8px;padding:0 12px;border:1px solid var(--color-border-strong);border-radius:var(--radius-control);background:var(--color-surface)}.search-field input,.category-filter select{width:100%;min-width:0;border:0;outline:0;background:transparent;color:var(--color-text);font:inherit;font-size:14px}.type-filter{display:flex;gap:4px;padding:4px;border:1px solid var(--color-border);border-radius:var(--radius-control);background:var(--color-surface)}.type-filter button{display:flex;min-height:34px;align-items:center;gap:5px;padding:0 9px;border:0;border-radius:5px;background:transparent;color:var(--color-text-secondary);font-size:14px;cursor:pointer}.type-filter button.active{background:var(--color-accent);color:#fff}
.market-layout{display:grid;grid-template-columns:minmax(0,74fr) minmax(300px,26fr);gap:12px;align-items:start}.catalog-surface,.preview-surface,.publish-surface,.mine-surface{border:1px solid var(--color-border);border-radius:var(--radius-panel);background:var(--color-surface)}.catalog-surface{min-width:0;overflow:hidden}.section-heading{display:flex;align-items:center;justify-content:space-between;padding:16px 18px;border-bottom:1px solid var(--color-border)}.section-heading h2,.section-heading p{margin:0}.section-heading h2{font-size:19px}.section-heading p{margin-top:3px;color:var(--color-text-muted);font-size:14px}
.market-list{display:flex;flex-direction:column}.market-row{display:grid;width:100%;grid-template-columns:42px minmax(0,1fr) 150px;gap:13px;align-items:center;min-height:112px;padding:15px 18px;border:0;border-bottom:1px solid var(--color-border);background:var(--color-surface);color:var(--color-text);text-align:left;cursor:pointer}.market-row:last-child{border-bottom:0}.market-row:hover,.market-row.selected{background:var(--color-surface-subtle)}.market-row.selected{box-shadow:inset 3px 0 0 var(--color-accent)}.type-icon{display:grid;width:40px;height:40px;place-items:center;border:1px solid var(--color-border);border-radius:var(--radius-control);background:var(--color-surface-subtle);color:var(--color-text-secondary)}.row-main,.row-side{min-width:0}.row-main>strong{display:block;margin-top:5px;font-size:16px}.row-meta{display:flex;align-items:center;gap:8px;color:var(--color-text-muted);font-size:14px}.row-meta b{color:var(--color-text-secondary)}.row-summary{display:-webkit-box;margin-top:5px;overflow:hidden;color:var(--color-text-secondary);font-size:14px;line-height:1.5;-webkit-box-orient:vertical;-webkit-line-clamp:2}.row-tags{display:flex;gap:5px;margin-top:8px}.row-tags i,.review-tags span{padding:3px 7px;border:1px solid var(--color-border);border-radius:4px;color:var(--color-text-secondary);font-size:14px;font-style:normal}.row-side{display:grid;grid-template-columns:1fr auto;gap:5px 6px;align-items:center;color:var(--color-text-muted);font-size:14px}.row-side span{grid-column:1}.row-side svg{grid-column:2;grid-row:1/3}
.preview-surface{position:sticky;top:12px;min-height:480px;overflow:hidden}.preview-content{padding:20px}.preview-type{display:flex;align-items:center;gap:7px;margin:0;color:var(--color-text-secondary);font-size:14px;font-weight:650}.preview-content h2{margin:10px 0 4px;font-size:22px;line-height:1.4}.preview-author{margin:0;color:var(--color-text-muted);font-size:14px}.preview-summary{margin:16px 0;color:var(--color-text-secondary);font-size:14px;line-height:1.65}.preview-metrics{display:grid;grid-template-columns:repeat(3,1fr);margin:0;border:1px solid var(--color-border);border-radius:var(--radius-control);overflow:hidden}.preview-metrics div{padding:10px;border-right:1px solid var(--color-border)}.preview-metrics div:last-child{border-right:0}.preview-metrics dt{color:var(--color-text-muted);font-size:14px}.preview-metrics dd{margin:5px 0 0;font-size:14px;font-weight:650}.included-list{margin-top:18px}.included-list h3{margin:0 0 8px;font-size:15px}.included-list>div{display:grid;grid-template-columns:24px minmax(0,1fr);gap:8px;align-items:start;padding:7px 0;border-top:1px solid var(--color-border)}.included-list>div>span{display:grid;width:22px;height:22px;place-items:center;border-radius:4px;background:var(--color-surface-subtle);color:var(--color-text-secondary);font-size:14px}.included-list p{margin:0;font-size:14px;line-height:1.5}.source-panel{margin-top:18px;padding:13px;border:1px solid var(--color-border);border-radius:var(--radius-control);background:var(--color-surface-subtle)}.source-panel>div{display:flex;align-items:center;gap:7px}.source-panel p,.source-panel span,.source-panel small{display:block;margin:7px 0 0;color:var(--color-text-secondary);font-size:14px;line-height:1.5;overflow-wrap:anywhere}.source-panel em{display:inline-block;margin-top:8px;padding:3px 7px;border:1px solid var(--color-border-strong);border-radius:4px;font-size:14px;font-style:normal}.preview-actions{display:flex;gap:8px;margin-top:18px}.preview-actions .primary-button{flex:1}.inline-error{display:flex;align-items:center;gap:6px;margin:14px 0 0;padding:9px;border:1px solid;font-size:14px}.preview-empty,.preview-loading,.empty-surface{display:grid;min-height:330px;place-items:center;align-content:center;gap:8px;padding:24px;text-align:center}.preview-empty strong,.empty-surface strong{font-size:16px}.preview-empty p,.empty-surface p{max-width:420px;margin:0;color:var(--color-text-secondary);font-size:14px;line-height:1.55}.preview-loading{display:flex;color:var(--color-text-secondary);font-size:14px}
.publish-surface,.mine-surface{margin-top:18px;overflow:hidden}.wizard-steps{display:grid;grid-template-columns:repeat(3,1fr);margin:0;padding:0;border-bottom:1px solid var(--color-border);list-style:none}.wizard-steps li{display:flex;align-items:center;gap:10px;padding:15px 18px;border-right:1px solid var(--color-border);color:var(--color-text-muted)}.wizard-steps li:last-child{border-right:0}.wizard-steps li.active,.wizard-steps li.done{color:var(--color-text)}.wizard-steps li>span{display:grid;width:28px;height:28px;place-items:center;border:1px solid var(--color-border-strong);border-radius:50%;font-size:14px}.wizard-steps li.active>span,.wizard-steps li.done>span{color:#fff;border-color:var(--color-accent);background:var(--color-accent)}.wizard-steps strong,.wizard-steps small{display:block}.wizard-steps strong{font-size:14px}.wizard-steps small{margin-top:2px;font-size:14px}.publish-step{padding:24px}.step-heading h2,.step-heading p{margin:0}.step-heading h2{font-size:21px}.step-heading p{margin-top:6px;color:var(--color-text-secondary);font-size:14px}.publish-type-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:18px}.publish-type-grid label{display:grid;min-height:150px;align-content:start;gap:8px;padding:18px;border:1px solid var(--color-border-strong);border-radius:var(--radius-panel);cursor:pointer}.publish-type-grid label.selected{box-shadow:inset 0 0 0 2px var(--color-accent);background:var(--color-surface-subtle)}.publish-type-grid input{position:absolute;opacity:0}.publish-type-grid strong{font-size:16px}.publish-type-grid span{color:var(--color-text-secondary);font-size:14px;line-height:1.55}.publish-editor{display:grid;grid-template-columns:minmax(300px,.9fr) minmax(0,1.1fr);gap:24px}.source-selector{padding-right:24px;border-right:1px solid var(--color-border)}.source-list{display:flex;flex-direction:column;gap:7px;margin-top:16px}.source-list button{display:grid;grid-template-columns:38px minmax(0,1fr) 22px;gap:10px;align-items:center;padding:11px;border:1px solid var(--color-border);border-radius:var(--radius-control);background:var(--color-surface);color:var(--color-text);text-align:left;cursor:pointer}.source-list button.selected{border-color:var(--color-accent);background:var(--color-surface-subtle)}.source-list button>span:first-child{display:grid;width:36px;height:36px;place-items:center;background:var(--color-surface-subtle)}.source-list strong,.source-list small{display:block}.source-list strong{font-size:14px}.source-list small{margin-top:3px;color:var(--color-text-muted);font-size:14px}.empty-surface.compact{min-height:220px;margin-top:16px;border:1px dashed var(--color-border-strong)}.publication-form{display:flex;flex-direction:column;gap:14px}.publication-form label{font-size:14px;font-weight:650}.publication-form input,.publication-form textarea{display:block;width:100%;box-sizing:border-box;margin-top:6px;padding:10px 11px;border:1px solid var(--color-border-strong);border-radius:var(--radius-control);background:var(--color-surface);color:var(--color-text);font:inherit;font-size:14px}.publication-form textarea{min-height:128px;resize:vertical}.form-row{display:grid;grid-template-columns:.7fr 1.3fr;gap:10px}.source-check{display:flex;align-items:flex-start;gap:10px;padding:12px;border:1px solid var(--color-border);border-radius:var(--radius-control);background:var(--color-accent-soft)}.source-check.incomplete{color:var(--color-danger);border-color:#e8caca;background:var(--color-danger-soft)}.source-check strong,.source-check p{display:block;margin:0;font-size:14px}.source-check p{margin-top:4px;font-weight:400}.publish-review{display:grid;grid-template-columns:minmax(0,1fr) 320px;gap:24px}.publish-review h2{margin:8px 0;font-size:23px}.publish-review>section>p:not(.preview-type){color:var(--color-text-secondary);font-size:15px;line-height:1.65}.review-tags{display:flex;flex-wrap:wrap;gap:6px;margin-top:14px}.publish-review .source-panel{margin-top:0}.wizard-actions{display:flex;align-items:center;justify-content:space-between;padding:16px 24px;border-top:1px solid var(--color-border);background:var(--color-surface-subtle)}.publish-complete{display:grid;min-height:390px;place-items:center;align-content:center;gap:9px;padding:30px;text-align:center}.publish-complete h2,.publish-complete p{margin:0}.publish-complete p{max-width:560px;color:var(--color-text-secondary);font-size:15px;line-height:1.6}.publish-complete .primary-button{margin-top:10px}
.mine-tabs{display:flex;padding:8px;border-bottom:1px solid var(--color-border);background:var(--color-surface-subtle)}.mine-tabs button{display:flex;min-height:38px;align-items:center;gap:7px;padding:0 13px;border:0;border-radius:var(--radius-control);background:transparent;color:var(--color-text-secondary);font-size:14px;cursor:pointer}.mine-tabs button.active{background:var(--color-surface);color:var(--color-text);box-shadow:0 0 0 1px var(--color-border)}.mine-tabs span{font-variant-numeric:tabular-nums}.mine-list{display:flex;flex-direction:column}.mine-row{display:grid;grid-template-columns:42px minmax(0,1fr) auto;gap:13px;align-items:center;min-height:92px;padding:14px 18px;border-bottom:1px solid var(--color-border)}.mine-row:last-child{border-bottom:0}.mine-row>div>strong{display:block;margin-top:5px;font-size:15px}.mine-row p{margin:5px 0 0;color:var(--color-text-secondary);font-size:14px}
.spin{animation:spin .9s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
@media(max-width:1260px){.market-page{width:calc(100% - 32px)}.filter-bar{grid-template-columns:minmax(210px,1fr) auto}.category-filter{grid-column:1/-1}.market-layout{grid-template-columns:minmax(0,72fr) minmax(290px,28fr)}.type-filter button{padding-inline:7px}.market-row{grid-template-columns:42px minmax(0,1fr) 130px}.publish-editor{grid-template-columns:minmax(270px,.8fr) minmax(0,1.2fr)}}
</style>
