<script setup>
defineProps({
  eyebrow: { type: String, default: '' },
  title: { type: String, required: true },
  description: { type: String, default: '' },
  compact: Boolean,
})
</script>

<template>
  <header class="page-heading" :class="{ 'page-heading--compact': compact }">
    <div class="page-heading__copy">
      <p v-if="eyebrow" class="page-heading__eyebrow">{{ eyebrow }}</p>
      <h1>{{ title }}</h1>
      <p v-if="description && !compact" class="page-heading__description">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="page-heading__actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.page-heading {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  padding: 2px 0;
}

.page-heading__copy {
  min-width: 0;
}

.page-heading__eyebrow {
  margin: 0 0 4px;
  color: var(--color-text-muted);
  font-size: 14px;
  font-weight: 500;
  line-height: 1.4;
  font-family: var(--font-sans);
}

.page-heading h1 {
  margin: 0;
  color: var(--color-text);
  font-family: var(--font-heading);
  font-size: var(--font-size-page-title);
  font-weight: 650;
  line-height: var(--line-height-heading);
}

.page-heading__description {
  max-width: 760px;
  margin: 8px 0 0;
  color: var(--color-text-secondary);
  font-family: var(--font-sans);
  font-size: var(--font-size-body);
  line-height: var(--line-height-body);
}

.page-heading__actions {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 8px;
}

.page-heading--compact {
  align-items: center;
}

.page-heading--compact .page-heading__eyebrow {
  margin-bottom: 2px;
  font-size: 14px;
}

.page-heading--compact h1 {
  overflow: hidden;
  font-size: var(--font-size-page-title-compact);
  line-height: var(--line-height-heading);
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
