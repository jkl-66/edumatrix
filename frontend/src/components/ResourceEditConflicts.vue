<script setup>
import { editConflictText } from '../utils/resourceEditMerge.js'
const props = defineProps({ items: { type: Array, default: () => [] }, sourceRefs: { type: Array, default: () => [] } })
const emit = defineEmits(['choose'])
function display(item, side) {
  if (item.label.endsWith('来源选择')) return (item[side] || []).map(id => props.sourceRefs.find(source => source.source_ref_id === id)?.title || '课程材料').join('、') || '未选择'
  return editConflictText(item[side])
}
</script>

<template>
  <section v-if="items.length" class="edit-conflicts" aria-label="处理同时修改的内容">
    <strong>有些内容在两个页面都改过，请选择要保留的写法。</strong>
    <p>其余改动会一起保留。选择完成后可继续编辑，再保存为新版本。</p>
    <article v-for="item in items" :key="item.key">
      <h3>{{ item.label }}</h3>
      <div class="edit-choices">
        <div><strong>本页草稿</strong><pre>{{ display(item, 'local') }}</pre><button type="button" @click="emit('choose', item.key, 'local')">保留本页写法</button></div>
        <div><strong>另一页已保存的内容</strong><pre>{{ display(item, 'latest') }}</pre><button type="button" @click="emit('choose', item.key, 'latest')">采用已保存写法</button></div>
      </div>
    </article>
  </section>
</template>

<style scoped>
.edit-conflicts{margin:14px 0;padding:16px;border:1px solid var(--color-border);border-radius:8px;background:var(--color-warning-soft);font-size:14px;line-height:1.6}.edit-conflicts p{margin:6px 0 12px}.edit-conflicts h3{font-size:15px}.edit-choices{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.edit-choices>div{min-width:0;padding:12px;background:white;border:1px solid var(--color-border);border-radius:6px}.edit-choices pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:240px;overflow:auto;font:inherit}.edit-choices button{padding:8px 12px;border:1px solid var(--color-border-strong);border-radius:6px;background:white;color:var(--color-text);cursor:pointer}@media(max-width:700px){.edit-choices{grid-template-columns:1fr}}
</style>
