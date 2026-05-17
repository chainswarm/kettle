<script setup lang="ts">
import { computed, ref, watch, nextTick } from 'vue'
import type { DHTEvent } from '../types'

const props = withDefaults(defineProps<{
  events: DHTEvent[]
  maxItems?: number
}>(), {
  maxItems: 50,
})

const container = ref<HTMLElement | null>(null)
const userScrolled = ref(false)

const displayEvents = computed(() => props.events.slice(0, props.maxItems))

const eventColors: Record<string, string> = {
  heartbeat: 'border-l-green-400',
  tee_quote: 'border-l-blue-400',
  work_record: 'border-l-purple-400',
  overwatch: 'border-l-red-400',
  node_join: 'border-l-yellow-400',
  node_leave: 'border-l-yellow-400',
}

const eventBadgeColors: Record<string, string> = {
  heartbeat: 'bg-green-100 text-green-700',
  tee_quote: 'bg-blue-100 text-blue-700',
  work_record: 'bg-purple-100 text-purple-700',
  overwatch: 'bg-red-100 text-red-700',
  node_join: 'bg-yellow-100 text-yellow-700',
  node_leave: 'bg-yellow-100 text-yellow-700',
}

function formatRelativeTime(timestamp: string): string {
  const now = Date.now()
  const then = new Date(timestamp).getTime()
  const diff = Math.floor((now - then) / 1000)

  if (diff < 5) return 'just now'
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  return `${Math.floor(diff / 3600)}h ago`
}

import { truncateAddress } from '../utils'

function onScroll() {
  if (container.value) {
    userScrolled.value = container.value.scrollTop > 20
  }
}

watch(() => props.events.length, () => {
  if (!userScrolled.value && container.value) {
    nextTick(() => {
      if (container.value) container.value.scrollTop = 0
    })
  }
})
</script>

<template>
  <div class="bg-white border border-green-200 rounded-lg overflow-hidden">
    <div class="px-3 py-2 bg-green-50 border-b border-green-200">
      <h3 class="text-sm font-semibold text-gray-700">Live Events</h3>
    </div>
    <div
      ref="container"
      class="overflow-y-auto max-h-[500px]"
      @scroll="onScroll"
    >
      <div
        v-if="displayEvents.length === 0"
        class="p-4 text-center text-sm text-gray-400"
      >
        Waiting for events...
      </div>
      <div
        v-for="(event, index) in displayEvents"
        :key="`${event.timestamp}-${index}`"
        class="border-l-4 border-b border-gray-100 px-3 py-2 text-xs event-flash"
        :class="eventColors[event.type] || 'border-l-gray-300'"
      >
        <div class="flex items-center justify-between mb-1">
          <span
            class="px-1.5 py-0.5 rounded text-[10px] font-medium"
            :class="eventBadgeColors[event.type] || 'bg-gray-100 text-gray-600'"
          >
            {{ event.type }}
          </span>
          <span class="text-gray-400">{{ formatRelativeTime(event.timestamp) }}</span>
        </div>
        <div class="flex items-center justify-between text-gray-500">
          <span class="font-mono">{{ truncateAddress(event.data?.peer_id as string) }}</span>
          <span v-if="event.data?.epoch">Epoch {{ event.data.epoch }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
