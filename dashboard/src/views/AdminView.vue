<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useNetworkStore } from '../stores/network'
import { useAuthStore } from '../stores/auth'
import type { DbStats } from '../types'
import NodeCard from '../components/NodeCard.vue'
import EventFeed from '../components/EventFeed.vue'
import OverwatchFeed from '../components/OverwatchFeed.vue'
import NetworkTopology from '../components/NetworkTopology.vue'

const store = useNetworkStore()
const auth = useAuthStore()
const dbStats = ref<DbStats | null>(null)
const expandedEvent = ref<number | null>(null)

const nodesList = computed(() => Array.from(store.nodes.values()))
const onlineCount = computed(() => nodesList.value.filter(n => n.status === 'online').length)
const currentEpoch = computed(() => Math.max(0, ...nodesList.value.map(n => n.epoch)))

async function fetchDbStats() {
  try {
    const res = await fetch('/api/admin/db-stats', {
      headers: auth.getAuthHeaders(),
    })
    if (res.ok) {
      dbStats.value = await res.json()
    }
  } catch {
    // Silently fail
  }
}

function toggleEvent(index: number) {
  expandedEvent.value = expandedEvent.value === index ? null : index
}

function handleLogout() {
  auth.logout()
  window.location.href = '/'
}

onMounted(() => {
  fetchDbStats()
  setInterval(fetchDbStats, 15000)
})
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <h2 class="text-lg font-bold text-gray-800">Admin Dashboard</h2>
      <button
        class="text-sm text-gray-500 hover:text-red-500"
        @click="handleLogout"
      >
        Logout
      </button>
    </div>

    <!-- Stats bar -->
    <div class="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-6">
      <div class="bg-green-50 rounded-lg p-3 border border-green-200">
        <div class="text-xs text-gray-500 mb-1">Total Nodes</div>
        <div class="text-xl font-bold text-gray-800">{{ nodesList.length }}</div>
      </div>
      <div class="bg-green-50 rounded-lg p-3 border border-green-200">
        <div class="text-xs text-gray-500 mb-1">Online</div>
        <div class="text-xl font-bold text-green-600">{{ onlineCount }}</div>
      </div>
      <div class="bg-green-50 rounded-lg p-3 border border-green-200">
        <div class="text-xs text-gray-500 mb-1">Current Epoch</div>
        <div class="text-xl font-bold text-gray-800">{{ currentEpoch }}</div>
      </div>
      <div class="bg-green-50 rounded-lg p-3 border border-green-200">
        <div class="text-xs text-gray-500 mb-1">DB Entries</div>
        <div class="text-xl font-bold text-gray-800">{{ dbStats?.total_entries ?? '-' }}</div>
      </div>
    </div>

    <!-- DB Stats panel -->
    <div v-if="dbStats" class="bg-white border border-green-200 rounded-lg p-4 mb-6">
      <h3 class="text-sm font-semibold text-gray-700 mb-3">Database Statistics</h3>
      <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div
          v-for="nmap in dbStats.nmaps"
          :key="nmap.name"
          class="bg-green-50 rounded p-2 text-center"
        >
          <div class="text-xs text-gray-500 mb-0.5">{{ nmap.name }}</div>
          <div class="text-lg font-semibold text-gray-700">{{ nmap.count }}</div>
        </div>
      </div>
    </div>

    <!-- Main layout -->
    <div class="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
      <!-- Overwatch feed -->
      <OverwatchFeed :events="store.overwatchEvents" />

      <!-- Event feed with raw JSON inspector -->
      <div class="bg-white border border-green-200 rounded-lg overflow-hidden">
        <div class="px-3 py-2 bg-green-50 border-b border-green-200">
          <h3 class="text-sm font-semibold text-gray-700">Event Inspector</h3>
        </div>
        <div class="overflow-y-auto max-h-[400px]">
          <div
            v-for="(event, index) in store.events.slice(0, 30)"
            :key="`admin-${index}`"
            class="border-b border-gray-100"
          >
            <button
              class="w-full text-left px-3 py-2 text-xs hover:bg-green-50 flex items-center justify-between"
              @click="toggleEvent(index)"
            >
              <span class="flex items-center gap-2">
                <span class="font-medium text-gray-700">{{ event.type }}</span>
                <span class="text-gray-400">{{ event.data?.peer_id ? String(event.data.peer_id).slice(0, 8) : '' }}...</span>
              </span>
              <svg
                class="w-3 h-3 text-gray-400 transition-transform"
                :class="{ 'rotate-180': expandedEvent === index }"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
              </svg>
            </button>
            <div
              v-if="expandedEvent === index"
              class="px-3 pb-2"
            >
              <pre class="text-[10px] bg-gray-50 rounded p-2 overflow-x-auto text-gray-600">{{ JSON.stringify(event, null, 2) }}</pre>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Node grid -->
    <div class="mb-6">
      <h3 class="text-sm font-semibold text-gray-700 mb-3">All Nodes</h3>
      <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        <NodeCard
          v-for="node in nodesList"
          :key="node.peer_id"
          :node="node"
        />
      </div>
    </div>

    <!-- Network topology -->
    <NetworkTopology :topology="store.topology" />
  </div>
</template>
