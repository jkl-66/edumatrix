<script setup>
import { ref } from 'vue'
import { Search, X } from '@lucide/vue'

defineOptions({ inheritAttrs: false })

const props = defineProps({
  modelValue: { type: [String, Number], default: '' },
  placeholder: { type: String, default: '' },
  ariaLabel: { type: String, default: '' },
  id: { type: String, default: undefined },
  name: { type: String, default: undefined },
  autocomplete: { type: String, default: 'off' },
  maxlength: { type: [String, Number], default: undefined },
  disabled: { type: Boolean, default: false },
  clearable: { type: Boolean, default: false },
  bordered: { type: Boolean, default: true },
  iconSize: { type: Number, default: 17 },
})

const emit = defineEmits(['update:modelValue', 'input', 'keydown', 'clear'])
const inputRef = ref(null)

function focus() {
  inputRef.value?.focus()
}

defineExpose({ focus })

function updateValue(event) {
  emit('update:modelValue', event.target.value)
  emit('input', event)
}

function clearValue() {
  if (props.disabled) return
  emit('update:modelValue', '')
  emit('clear')
}
</script>

<template>
  <label class="ui-search-field" :class="{ 'ui-search-field--plain': !bordered }" v-bind="$attrs">
    <Search class="ui-search-field__icon" :size="iconSize" aria-hidden="true" />
    <input
      ref="inputRef"
      :id="id"
      :name="name"
      :value="modelValue"
      type="search"
      :placeholder="placeholder"
      :aria-label="ariaLabel || undefined"
      :autocomplete="autocomplete"
      :maxlength="maxlength"
      :disabled="disabled"
      @input="updateValue"
      @keydown="emit('keydown', $event)"
    >
    <button
      v-if="clearable && String(modelValue || '')"
      type="button"
      class="ui-search-field__clear"
      title="清除搜索"
      aria-label="清除搜索"
      @click.prevent="clearValue"
    >
      <X :size="16" aria-hidden="true" />
    </button>
    <slot name="after" />
  </label>
</template>

<style scoped>
.ui-search-field {
  position: relative;
  display: flex;
  min-width: 0;
  min-height: 40px;
  align-items: center;
  gap: 8px;
  padding: 0 11px;
  color: var(--color-text-muted, #60727c);
  border: 1px solid var(--color-border-strong, #9ba8ab);
  border-radius: var(--radius-control, 6px);
  background: var(--color-surface, #fff);
}

.ui-search-field:focus-within {
  border-color: var(--color-accent, #11212d);
  outline: 3px solid rgb(17 33 45 / 14%);
  outline-offset: 1px;
}

.ui-search-field--plain {
  min-height: 0;
  flex: 1;
  gap: 7px;
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  outline: 0;
}

.ui-search-field--plain:focus-within {
  border: 0;
  outline: 0;
}

.ui-search-field__icon {
  flex: 0 0 auto;
  pointer-events: none;
}

.ui-search-field input {
  width: 100%;
  min-width: 0;
  height: 38px;
  padding: 0;
  color: var(--color-text, #06141b);
  border: 0;
  outline: 0;
  background: transparent;
  font: inherit;
  font-size: 14px;
}

.ui-search-field input::placeholder {
  color: var(--color-text-muted, #60727c);
  opacity: 1;
}

.ui-search-field__clear {
  display: grid;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  place-items: center;
  padding: 0;
  color: var(--color-text-secondary, #4a5c6a);
  border: 0;
  border-radius: 4px;
  background: transparent;
  cursor: pointer;
}

.ui-search-field__clear:hover,
.ui-search-field__clear:focus-visible {
  color: var(--color-text, #06141b);
  background: var(--color-surface-subtle, #f5f7f7);
  outline: 2px solid var(--color-accent, #11212d);
  outline-offset: 1px;
}
</style>
