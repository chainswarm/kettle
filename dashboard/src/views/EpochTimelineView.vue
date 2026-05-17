<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useExplorerApi } from '../composables/useExplorerApi'
import type { ExplorerEpoch, ExplorerEvent } from '../types'

const route = useRoute()
const router = useRouter()
const api = useExplorerApi()

const epochs = ref<ExplorerEpoch[]>([])
const loading = ref(true)
const page = ref(1)
const hasMore = ref(false)
const expandedEpoch = ref<number | null>(null)
const expandedEvents = ref<ExplorerEvent[]>([])
const loadingEvents = ref(false)

// If route has epoch param, we show single epoch detail
const singleEpoch = computed(() => {
  const ep = route.params.epoch
  return ep ? parseInt(ep as string, 10) : null
})

async function loadEpochs() {
  loading.value = true
  const result = await api.fetchEpochs(page.value, 20)
  epochs.value = result.epochs
  hasMore.value = result.hasMore
  loading.value = false
}

async function toggleEpoch(epoch: number) {
  if (expandedEpoch.value === epoch) {
    expandedEpoch.value = null
    expandedEvents.value = []
    return
  }
  expandedEpoch.value = epoch
  loadingEvents.value = true
  expandedEvents.value = await api.fetchEpochEvents(epoch)
  loadingEvents.value = false
}

async function loadSingleEpoch() {
  if (singleEpoch.value === null) return
  loading.value = true
  expandedEpoch.value = singleEpoch.value
  expandedEvents.value = await api.fetchEpochEvents(singleEpoch.value)
  loading.value = false
}

function prevPage() {
  if (page.value > 1) {
    page.value--
    loadEpochs()
  }
}

function nextPage() {
  if (hasMore.value) {
    page.value++
    loadEpochs()
  }
}

import { truncateAddress } from '../utils'

const eventTypeBadge: Record<string, string> = {
  heartbeat: 'bg-green-100 text-green-700',
  tee_quote: 'bg-blue-100 text-blue-700',
  mock_work: 'bg-purple-100 text-purple-700',
  work_record: 'bg-purple-100 text-purple-700',
  overwatch: 'bg-red-100 text-red-700',
  unknown: 'bg-gray-100 text-gray-600',
}

onMounted(() => {
  if (singleEpoch.value !== null) {
    loadSingleEpoch()
  } else {
    loadEpochs()
  }
})
</script>

<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <div>
        <button
          v-if="singleEpoch !== null"
          class="text-sm text-green-600 hover:text-green-800 flex items-center gap-1 mb-2"
          @click="router.push({ name: 'epochs' })"
        >
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
          </svg>
          All Epochs
        </button>
        <h2 class="text-lg font-bold text-gray-800">
          {{ singleEpoch !== null ? `Epoch ${singleEpoch}` : 'Epoch Timeline' }}
        </h2>
      </div>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="text-center py-12 text-gray-400">
      Loading epochs...
    </div>

    <!-- Single epoch detail -->
    <div v-else-if="singleEpoch !== null">
      <div v-if="expandedEvents.length === 0" class="text-center py-12 text-gray-400">
        No events found for epoch {{ singleEpoch }}
      </div>
      <div v-else class="space-y-2">
        <div
          v-for="(event, index) in expandedEvents"
          :key="`${event.key}-${index}`"
          class="bg-white border border-green-200 rounded-lg px-4 py-3 text-sm"
        >
          <div class="flex items-center justify-between mb-1">
            <span
              class="px-2 py-0.5 rounded text-xs font-medium"
              :class="eventTypeBadge[event.data?.type as string] || eventTypeBadge.unknown"
            >
              {{ event.data?.type || 'unknown' }}
            </span>
            <router-link
              :to="{ name: 'node-detail', params: { peerId: event.peer_id } }"
              class="text-xs font-mono text-green-600 hover:text-green-800"
            >
              {{ truncateAddress(event.peer_id) }}
            </router-link>
          </div>
          <div class="text-xs text-gray-500 mt-1">
            <span v-if="event.data?.tee_score !== undefined">TEE Score: {{ (event.data.tee_score as number).toFixed(2) }}</span>
            <span v-if="event.data?.gpu" class="ml-3">GPU: {{ event.data.gpu }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Epoch list -->
    <div v-else>
      <div v-if="epochs.length === 0" class="text-center py-12 text-gray-400">
        <p class="text-lg mb-2">No epochs found</p>
        <p class="text-sm">Waiting for data from the subnet...</p>
      </div>

      <div v-else class="space-y-3">
        <div
          v-for="ep in epochs"
          :key="ep.epoch"
          class="bg-white border border-green-200 rounded-lg overflow-hidden"
        >
          <button
            class="w-full text-left px-4 py-3 hover:bg-green-50 transition-colors flex items-center justify-between"
            @click="toggleEpoch(ep.epoch)"
          >
            <div class="flex items-center gap-4">
              <span class="text-lg font-bold text-gray-800 w-20">
                #{{ ep.epoch }}
              </span>
              <div class="flex items-center gap-2">
                <span
                  v-for="(count, type) in ep.eventsByType"
                  :key="type"
                  class="px-2 py-0.5 rounded text-[10px] font-medium"
                  :class="eventTypeBadge[type as string] || eventTypeBadge.unknown"
                >
                  {{ type }}: {{ count }}
                </span>
              </div>
            </div>
            <div class="flex items-center gap-3 text-xs text-gray-500">
              <span>{{ ep.peerIds.length }} node{{ ep.peerIds.length !== 1 ? 's' : '' }}</span>
              <span>{{ ep.eventCount }} event{{ ep.eventCount !== 1 ? 's' : '' }}</span>
              <svg
                class="w-4 h-4 text-gray-400 transition-transform"
                :class="{ 'rotate-180': expandedEpoch === ep.epoch }"
                fill="none" stroke="currentColor" viewBox="0 0 24 24"
              >
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7" />
              </svg>
            </div>
          </button>

          <!-- Expanded events for this epoch -->
          <div v-if="expandedEpoch === ep.epoch" class="border-t border-green-200 bg-green-50/30 px-4 py-3">
            <div v-if="loadingEvents" class="text-center py-4 text-sm text-gray-400">
              Loading events...
            </div>
            <div v-else-if="expandedEvents.length === 0" class="text-center py-4 text-sm text-gray-400">
              No events found
            </div>
            <div v-else class="space-y-2">
              <div
                v-for="(event, index) in expandedEvents"
                :key="`${event.key}-${index}`"
                class="bg-white border border-green-100 rounded px-3 py-2 text-xs"
              >
                <div class="flex items-center justify-between">
                  <span
                    class="px-1.5 py-0.5 rounded text-[10px] font-medium"
                    :class="eventTypeBadge[event.data?.type as string] || eventTypeBadge.unknown"
                  >
                    {{ event.data?.type || 'unknown' }}
                  </span>
                  <router-link
                    :to="{ name: 'node-detail', params: { peerId: event.peer_id } }"
                    class="font-mono text-green-600 hover:text-green-800"
                  >
                    {{ truncateAddress(event.peer_id) }}
                  </router-link>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- Pagination -->
      <div class="flex items-center justify-between mt-6">
        <button
          class="px-3 py-1.5 text-sm border border-green-200 rounded-lg hover:bg-green-50 disabled:opacity-50 disabled:cursor-not-allowed"
          :disabled="page <= 1"
          @click="prevPage"
        >
          Previous
        </button>
        <span class="text-sm text-gray-500">Page {{ page }}</span>
        <button
          class="px-3 py-1.5 text-sm border border-green-200 rounded-lg hover:bg-green-50 disabled:opacity-50 disabled:cursor-not-allowed"
          :disabled="!hasMore"
          @click="nextPage"
        >
          Next
        </button>
      </div>
    </div>
  </div>
</template>
