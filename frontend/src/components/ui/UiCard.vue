<script setup>
defineProps({
  as: { type: String, default: 'section' },
  interactive: Boolean,
  tone: { type: String, default: 'default' },
})
</script>

<template>
  <component :is="as" class="ui-card" :class="[`ui-card--${tone}`, { 'ui-card--interactive': interactive }]">
    <slot />
  </component>
</template>

