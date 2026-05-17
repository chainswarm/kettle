<script setup lang="ts">
import type { OverwatchEvent } from '../types'

defineProps<{
  events: OverwatchEvent[]
}>()

import { truncateAddress } from '../utils'

const resultColors: Record<string, string> = {
  pass: 'bg-green-100 text-green-700',
  fail: 'bg-red-100 text-red-700',
  tampered: 'bg-red-200 text-red-800',
}
</script>

<template>
  <div class="bg-white border border-green-200 rounded-lg overflow-hidden">
    <div class="px-3 py-2 bg-green-50 border-b border-green-200">
      <h3 class="text-sm font-semibold text-gray-700">Overwatch Activity</h3>
    </div>
    <div class="overflow-y-auto max-h-[400px]">
      <div
        v-if="events.length === 0"
        class="p-4 text-center text-sm text-gray-400"
      >
        No overwatch events yet
      </div>
      <div
        v-for="(event, index) in events"
        :key="`${event.epoch}-${event.peer_id}-${index}`"
        class="border-b border-gray-100 px-3 py-2 text-xs"
        :class="event.result === 'pass' ? 'border-l-4 border-l-green-400' : 'border-l-4 border-l-red-400'"
      >
        <div class="flex items-center justify-between mb-1">
          <span
            class="px-1.5 py-0.5 rounded text-[10px] font-medium"
            :class="resultColors[event.result] || 'bg-gray-100 text-gray-600'"
          >
            {{ event.result.toUpperCase() }}
          </span>
          <span class="text-gray-400">Epoch {{ event.epoch }}</span>
        </div>
        <div class="flex items-center justify-between text-gray-500">
          <span class="font-mono">{{ truncateAddress(event.peer_id) }}</span>
          <span class="truncate ml-2">{{ event.details }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
