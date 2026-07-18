<script setup>
defineProps({
  label: String,
  value: [String, Number],
  detail: String,
  tone: { type: String, default: 'sage' },
})
</script>

<template>
  <article class="dashboard-widget" :class="`dashboard-widget--${tone}`">
    <div class="dashboard-widget__topline">
      <span class="dashboard-widget__icon"><slot name="icon" /></span>
      <span class="dashboard-widget__signal"><slot name="signal">实时</slot></span>
    </div>
    <div>
      <p class="dashboard-widget__label">{{ label }}</p>
      <strong class="dashboard-widget__value">{{ value }}</strong>
      <p v-if="detail" class="dashboard-widget__detail">{{ detail }}</p>
    </div>
  </article>
</template>

