<script setup>
defineProps({ columns: { type: Array, default: () => [] }, rows: { type: Array, default: () => [] } })
</script>

<template>
  <div class="data-table-wrap">
    <table class="data-table">
      <thead><tr><th v-for="column in columns" :key="column.key">{{ column.label }}</th></tr></thead>
      <tbody>
        <tr v-for="(row, index) in rows" :key="row.id || index">
          <td v-for="column in columns" :key="column.key"><slot :name="`cell-${column.key}`" :row="row">{{ row[column.key] }}</slot></td>
        </tr>
      </tbody>
    </table>
    <div v-if="!rows.length" class="data-table__empty"><slot name="empty">暂无数据</slot></div>
  </div>
</template>

