<script setup>
defineProps({ open: Boolean, title: String })
defineEmits(['close'])
</script>

<template>
  <Teleport to="body">
    <Transition name="modal-fade">
      <div v-if="open" class="ui-modal" @click.self="$emit('close')">
        <section class="ui-modal__panel" role="dialog" aria-modal="true" :aria-label="title">
          <header class="ui-modal__header">
            <h2>{{ title }}</h2>
            <button class="ui-modal__close" aria-label="关闭" @click="$emit('close')">×</button>
          </header>
          <div class="ui-modal__content"><slot /></div>
          <footer v-if="$slots.footer" class="ui-modal__footer"><slot name="footer" /></footer>
        </section>
      </div>
    </Transition>
  </Teleport>
</template>

