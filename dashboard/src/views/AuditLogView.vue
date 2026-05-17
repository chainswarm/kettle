<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useExplorerApi } from '../composables/useExplorerApi'
import type { OverwatchEvent } from '../types'

const api = useExplorerApi()

const events = ref<OverwatchEvent[]>([])
const loading = ref(true)
const activeFilter = ref<'all' | 'pass' | 'fail' | 'tampered'>('all')

const filteredEvents = computed(() => {
  if (activeFilter.value === 'all') return events.value
  return events.value.filter(e => e.result === activeFilter.value)
})

const stats = computed(() => {
  const total = events.value.length
  const pass = events.value.filter(e => e.result === 'pass').length
  const fail = events.value.filter(e => e.result === 'fail').length
  const tampered = events.value.filter(e => e.result === 'tampered').length
  return { total, pass, fail, tampered }
})

function truncatePeerId(peerId: string): string {
  if (!peerId || peerId.length <= 12) return peerId || ''
  return `${peerId.slice(0, 6)}...${peerId.slice(-4)}`
}

const resultColors: Record<string, string> = {
  pass: 'bg-green-100 text-green-700',
  fail: 'bg-red-100 text-red-700',
  tampered: 'bg-red-200 text-red-800',
}

const resultBorderColors: Record<string, string> = {
  pass: 'border-l-green-400',
  fail: 'border-l-red-400',
  tampered: 'border-l-red-600',
}

onMounted(async () => {
  events.value = await api.fetchAuditLog()
  loading.value = false
})
</script>

<template>
  <div>
    <h2 class="text-lg font-bold text-gray-800 mb-6">Overwatch Audit Log</h2>

    <!-- Stats summary -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
      <div class="bg-green-50 rounded-lg p-3 border border-green-200">
        <div class="text-xs text-gray-500 mb-1">Total Audits</div>
        <div class="text-xl font-bold text-gray-800">{{ stats.total }}</div>
      </div>
      <div class="bg-green-50 rounded-lg p-3 border border-green-200">
        <div class="text-xs text-gray-500 mb-1">Passed</div>
        <div class="text-xl font-bold text-green-600">{{ stats.pass }}</div>
      </div>
      <div class="bg-green-50 rounded-lg p-3 border border-green-200">
        <div class="text-xs text-gray-500 mb-1">Failed</div>
        <div class="text-xl font-bold" :class="stats.fail > 0 ? 'text-red-600' : 'text-gray-800'">{{ stats.fail }}</div>
      </div>
      <div class="bg-green-50 rounded-lg p-3 border border-green-200">
        <div class="text-xs text-gray-500 mb-1">Tampered</div>
        <div class="text-xl font-bold" :class="stats.tampered > 0 ? 'text-red-700' : 'text-gray-800'">{{ stats.tampered }}</div>
      </div>
    </div>

    <!-- Filter buttons -->
    <div class="flex gap-2 mb-4">
      <button
        v-for="filter in (['all', 'pass', 'fail', 'tampered'] as const)"
        :key="filter"
        class="px-3 py-1.5 text-xs font-medium rounded-lg border transition-colors"
        :class="activeFilter === filter
          ? 'bg-green-500 text-white border-green-500'
          : 'bg-white text-gray-600 border-green-200 hover:bg-green-50'"
        @click="activeFilter = filter"
      >
        {{ filter === 'all' ? 'All' : filter.charAt(0).toUpperCase() + filter.slice(1) }}
        <span class="ml-1 opacity-75">
          ({{ filter === 'all' ? stats.total : stats[filter] }})
        </span>
      </button>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="text-center py-12 text-gray-400">Loading audit log...</div>

    <!-- Empty state -->
    <div v-else-if="filteredEvents.length === 0" class="text-center py-12 text-gray-400">
      <p class="text-lg mb-2">No audit events found</p>
      <p class="text-sm">{{ activeFilter !== 'all' ? 'Try a different filter' : 'Waiting for overwatch data...' }}</p>
    </div>

    <!-- Event list -->
    <div v-else class="space-y-2">
      <div
        v-for="(event, index) in filteredEvents"
        :key="`${event.epoch}-${event.peer_id}-${index}`"
        class="bg-white border border-green-200 rounded-lg px-4 py-3 border-l-4"
        :class="resultBorderColors[event.result] || 'border-l-gray-300'"
      >
        <div class="flex items-center justify-between mb-1">
          <div class="flex items-center gap-3">
            <span
              class="px-2 py-0.5 rounded text-xs font-medium"
              :class="resultColors[event.result] || 'bg-gray-100 text-gray-600'"
            >
              {{ event.result.toUpperCase() }}
            </span>
            <span class="text-sm text-gray-700">Epoch {{ event.epoch }}</span>
          </div>
          <router-link
            :to="{ name: 'node-detail', params: { peerId: event.peer_id } }"
            class="text-xs font-mono text-green-600 hover:text-green-800"
          >
            {{ truncatePeerId(event.peer_id) }}
          </router-link>
        </div>
        <div class="text-xs text-gray-500">
          {{ event.details }}
        </div>
      </div>
    </div>
  </div>
</template>
