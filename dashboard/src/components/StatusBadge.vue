<script setup lang="ts">
defineProps<{
  status: 'online' | 'offline'
}>()
</script>

<template>
  <span
    class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium"
    :class="status === 'online'
      ? 'bg-green-500 text-white'
      : 'bg-gray-400 text-white'"
  >
    <span
      v-if="status === 'online'"
      class="w-1.5 h-1.5 rounded-full bg-white animate-pulse"
    ></span>
    {{ status }}
  </span>
</template>
