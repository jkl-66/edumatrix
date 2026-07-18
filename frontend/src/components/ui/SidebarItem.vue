<script setup>
defineProps({ item: { type: Object, required: true }, collapsed: Boolean, active: Boolean })
</script>

<template>
  <router-link :to="item.path" class="sidebar-item" :class="{ 'sidebar-item--active': active, 'sidebar-item--collapsed': collapsed }" :title="collapsed ? item.label : undefined">
    <span class="sidebar-item__icon"><component :is="item.icon" :size="17" stroke-width="1.8" /></span>
    <span v-if="!collapsed" class="sidebar-item__label">{{ item.label }}</span>
    <span v-if="active && !collapsed" class="sidebar-item__dot" />
  </router-link>
</template>

