<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight, BookOpenCheck, ShieldCheck } from '@lucide/vue'

const props = defineProps({
  context: { type: Object, default: null },
  page: { type: String, required: true },
  primaryActionLabel: { type: String, default: '' },
})
const emit = defineEmits(['primary-action'])

const router = useRouter()
const contract = computed(() => props.context?.page_contracts?.[props.page] || null)

function openPrimaryAction() {
  const route = contract.value?.primary_action?.route
  emit('primary-action', route)
  if (route) router.push(route)
}
</script>

<template>
  <section v-if="context && contract" :data-testid="`competition-demo-context-${page}`" class="demo-context-band">
    <div class="demo-context-band__icon"><BookOpenCheck :size="18" /></div>
    <div class="demo-context-band__body">
      <div class="demo-context-band__meta">
        <span>{{ context.course?.title || 'EduMatrix 比赛演示上下文' }}</span>
        <small><ShieldCheck :size="11" />冻结合成演示数据 · {{ context.manifest_version }}</small>
      </div>
      <strong>{{ contract.status }}</strong>
      <p>{{ contract.next_step }}</p>
    </div>
    <button type="button" @click="openPrimaryAction">
      {{ primaryActionLabel || contract.primary_action.label }} <ArrowRight :size="14" />
    </button>
  </section>
</template>

<style scoped>
.demo-context-band {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  align-items: center;
  gap: 16px;
  margin: 0 0 20px;
  padding: 16px 18px;
  color: #49382d;
  border-block: 1px solid #d8cdc4;
  background: #f8f5f2;
}

.demo-context-band__icon {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  color: #6b4b37;
  background: #ebe2dc;
}

.demo-context-band__body {
  min-width: 0;
}

.demo-context-band__meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 14px;
  margin-bottom: 4px;
}

.demo-context-band__meta span,
.demo-context-band__meta small,
.demo-context-band p,
.demo-context-band button {
  font-size: 14px;
}

.demo-context-band__meta span {
  color: #70503b;
  font-weight: 700;
}

.demo-context-band__meta small {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #7f756d;
}

.demo-context-band strong {
  display: block;
  color: #2b231e;
  font-size: 16px;
}

.demo-context-band p {
  margin: 4px 0 0;
  color: #6e645c;
  line-height: 1.55;
}

.demo-context-band button {
  display: inline-flex;
  min-height: 40px;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 0 14px;
  color: #684936;
  border: 1px solid #cdbbae;
  background: #ffffff;
  font-weight: 700;
  cursor: pointer;
}

.demo-context-band button:hover {
  border-color: #806049;
  background: #f4eee9;
}

@media (max-width: 640px) {
  .demo-context-band {
    grid-template-columns: auto minmax(0, 1fr);
    align-items: start;
  }

  .demo-context-band button {
    grid-column: 1 / -1;
    width: 100%;
  }
}
</style>
