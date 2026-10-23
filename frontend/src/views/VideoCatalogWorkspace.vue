<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ExternalLink, FileSearch, RefreshCw, ShieldCheck, Video } from '@lucide/vue'
import { listVideoCatalog } from '../api'

const catalog = ref(null)
const loading = ref(true)
const error = ref('')
const query = ref('')
const topic = ref('')
const language = ref('')
const licenseStatus = ref('')
let timer

const items = computed(() => catalog.value?.items || [])
const facets = computed(() => catalog.value?.facets || { topics: [], languages: [], license_statuses: [] })
const label = value => ({
  reference_only_unverified: '仅来源页引用', repository_license_required: '按仓库核验', platform_link_only: '平台外链引用',
}[value] || value)
function message(e, fallback) { return e?.response?.data?.detail?.message || e?.message || fallback }
async function load() {
  loading.value = true; error.value = ''
  try { catalog.value = await listVideoCatalog({ query: query.value, topic: topic.value, language: language.value, license_status: licenseStatus.value }) }
  catch (e) { error.value = message(e, '本地视频目录加载失败') }
  finally { loading.value = false }
}
function reset() { query.value = ''; topic.value = ''; language.value = ''; licenseStatus.value = ''; load() }
watch([query, topic, language, licenseStatus], () => { clearTimeout(timer); timer = setTimeout(load, 220) })
onMounted(load)
</script>

<template>
  <main class="catalog" data-testid="video-catalog">
    <header>
      <div><p class="eyebrow">LOCAL-FIRST VIDEO DIRECTORY</p><h1>合法来源视频目录</h1><p>仅检索预置白名单的公开来源元数据。系统不会下载、镜像或分发第三方视频。</p></div>
      <div class="policy"><ShieldCheck :size="18"/><div><strong>来源与许可边界</strong><small>每条资源保留来源页、作者说明、许可状态和入选依据。</small></div></div>
    </header>
    <p v-if="error" class="notice error">{{ error }} <button @click="load"><RefreshCw :size="13"/>重试</button></p>
    <section class="filters" aria-label="视频目录筛选">
      <label><span>检索</span><input v-model.trim="query" maxlength="120" placeholder="标题、主题或知识点" aria-label="搜索视频目录"/></label>
      <label><span>主题</span><select v-model="topic" aria-label="按主题筛选"><option value="">全部主题</option><option v-for="item in facets.topics" :key="item" :value="item">{{ item }}</option></select></label>
      <label><span>语言</span><select v-model="language" aria-label="按语言筛选"><option value="">全部语言</option><option v-for="item in facets.languages" :key="item" :value="item">{{ item }}</option></select></label>
      <label><span>许可边界</span><select v-model="licenseStatus" aria-label="按许可状态筛选"><option value="">全部状态</option><option v-for="item in facets.license_statuses" :key="item" :value="item">{{ label(item) }}</option></select></label>
      <button class="reset" @click="reset"><RefreshCw :size="14"/>重置</button>
    </section>
    <p v-if="loading" class="notice">正在读取本地白名单目录...</p>
    <template v-else-if="catalog">
      <div class="summary"><FileSearch :size="15"/><span>找到 {{ catalog.total }} 条来源元数据</span><small>目录版本 {{ catalog.catalog_version }} · SHA-256 {{ catalog.manifest.sha256.slice(0, 12) }}...</small></div>
      <section v-if="items.length" class="cards"><article v-for="item in items" :key="item.source_key" class="card" data-testid="video-catalog-item"><div class="card-title"><Video :size="17"/><div><h2>{{ item.title }}</h2><p>{{ item.source_type }} · {{ item.language }} · {{ item.source_author }}</p></div></div><div class="topics"><span v-for="value in item.topics" :key="value">{{ value }}</span></div><dl><dt>许可状态</dt><dd><strong>{{ label(item.license_status) }}</strong><span>{{ item.license_label }}</span></dd><dt>课程节点</dt><dd>{{ item.course_node }}</dd><dt>时长</dt><dd>{{ item.duration_minutes == null ? '来源页未统一标注' : `${item.duration_minutes} 分钟` }}</dd><dt>入选依据</dt><dd>{{ item.selection_rationale }}</dd></dl><a :href="item.url" target="_blank" rel="noopener noreferrer" :aria-label="`在来源页面查看 ${item.title}`">查看来源页 <ExternalLink :size="14"/></a></article></section>
      <section v-else class="empty"><FileSearch :size="30"/><strong>没有符合条件的来源</strong><span>调整关键词或筛选条件后重试；目录只返回预置白名单，不会联网抓取未知视频。</span></section>
      <footer>目录模式：{{ catalog.catalog_policy.distribution }}。{{ catalog.catalog_policy.license_boundary }}</footer>
    </template>
  </main>
</template>

<style scoped>
.catalog{max-width:1220px;margin:0 auto;color:#26322c}.catalog header{display:flex;justify-content:space-between;gap:24px;padding-bottom:18px;border-bottom:1px solid #d7e0da}.eyebrow{margin:0 0 6px;color:#39765a;font-size:10px;font-weight:800}.catalog h1{margin:0;font-size:24px;letter-spacing:0}.catalog header p:last-child{margin:6px 0 0;color:#6c786f;font-size:12px}.policy{display:flex;gap:9px;min-width:270px;padding:11px 13px;border:1px solid #c9ddd0;background:#f1f7f3;color:#335c42}.policy div{display:flex;flex-direction:column}.policy strong{font-size:11px}.policy small{margin-top:3px;font-size:9px;line-height:1.45}.filters{display:grid;grid-template-columns:1.4fr repeat(3,minmax(120px,.7fr)) auto;gap:9px;align-items:end;margin:14px 0}.filters label{display:grid;gap:4px;color:#6d7a71;font-size:9px}.filters input,.filters select{height:34px;padding:0 9px;border:1px solid #cdd8d1;background:#fff;color:#26322c}.filters button,.notice button{display:inline-flex;align-items:center;justify-content:center;gap:5px;min-height:34px;padding:0 10px;border:1px solid #cbd7cf;background:#fff;color:#35483c}.notice{display:flex;align-items:center;gap:8px;padding:10px;background:#f3f6f4;font-size:11px}.error{background:#fff0ed;color:#8a4339}.summary{display:flex;align-items:center;gap:7px;margin:10px 0;color:#3c5647;font-size:11px}.summary small{margin-left:auto;color:#718078;font-family:monospace;font-size:9px}.cards{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.card{display:flex;min-height:310px;flex-direction:column;border:1px solid #d9e1dc;background:#fff;padding:14px}.card-title{display:flex;gap:9px;color:#17342b}.card h2{margin:0;font-size:15px}.card-title p{margin:4px 0 0;color:#68776e;font-size:9px;line-height:1.45}.topics{display:flex;flex-wrap:wrap;gap:5px;margin:12px 0}.topics span{padding:3px 6px;background:#edf4ef;color:#426654;font-size:9px}.card dl{display:grid;grid-template-columns:76px 1fr;gap:7px 9px;margin:0;font-size:10px;line-height:1.45}.card dt{color:#738077}.card dd{margin:0}.card dd strong,.card dd span{display:block}.card dd span{color:#7a5a50}.card a{display:flex;align-items:center;gap:5px;margin-top:auto;padding-top:12px;color:#1f6244;font-size:11px;font-weight:700;text-decoration:none}.empty{display:flex;min-height:230px;flex-direction:column;align-items:center;justify-content:center;border:1px dashed #cbd7cf;color:#718078}.empty strong{margin-top:8px;font-size:12px}.empty span{max-width:440px;margin-top:5px;text-align:center;font-size:10px;line-height:1.5}footer{margin-top:14px;padding:10px;border-left:3px solid #6b9b7b;background:#f3f6f4;color:#5b6b61;font-size:10px;line-height:1.5}@media(max-width:850px){.catalog header{flex-direction:column}.policy{min-width:0}.filters{grid-template-columns:repeat(2,minmax(0,1fr))}.cards{grid-template-columns:1fr}}@media(max-width:430px){.catalog h1{font-size:20px}.filters{grid-template-columns:1fr}.summary{align-items:flex-start;flex-wrap:wrap}.summary small{width:100%;margin-left:22px}.card{min-height:0}.card dl{grid-template-columns:68px 1fr}}
</style>
