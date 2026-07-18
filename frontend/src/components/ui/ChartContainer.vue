<script setup>
defineProps({ title: String, subtitle: String, eyebrow: String })
</script>

<template>
  <section class="chart-container">
    <header class="chart-container__header">
      <div>
        <p v-if="eyebrow" class="chart-container__eyebrow">{{ eyebrow }}</p>
        <h2>{{ title }}</h2>
        <p v-if="subtitle">{{ subtitle }}</p>
      </div>
      <slot name="action" />
    </header>
    <div class="chart-container__body"><slot /></div>
  </section>
</template>

