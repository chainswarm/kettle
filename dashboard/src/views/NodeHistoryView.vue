<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useExplorerApi } from '../composables/useExplorerApi'
import StatusBadge from '../components/StatusBadge.vue'
import type { ExplorerEvent, SubnetNode } from '../types'

const props = defineProps<{
  peerId: string
}>()

const router = useRouter()
const api = useExplorerApi()

const events = ref<ExplorerEvent[]>([])
const node = ref<SubnetNode | null>(null)
const loading = ref(true)
const activeFilters = ref<Set<string>>(new Set())
const displayLimit = ref(50)

const allEventTypes = computed(() => {
  const types = new Set<string>()
  for (const event of events.value) {
    const t = (event.data?.type as string) || 'unknown'
    types.add(t)
  }
  return Array.from(types).sort()
})

const filteredEvents = computed(() => {
  let filtered = events.value
  if (activeFilters.value.size > 0) {
    filtered = filtered.filter(e => {
      const t = (e.data?.type as string) || 'unknown'
      return activeFilters.value.has(t)
    })
  }
  return filtered
})

const displayedEvents = computed(() => filteredEvents.value.slice(0, displayLimit.value))
const hasMore = computed(() => filteredEvents.value.length > displayLimit.value)

function loadMore() {
  displayLimit.value += 50
}

import { truncateAddress } from '../utils'

const truncatedPeerId = computed(() => truncateAddress(props.peerId))

function toggleFilter(type: string) {
  const next = new Set(activeFilters.value)
  if (next.has(type)) {
    next.delete(type)
  } else {
    next.add(type)
  }
  activeFilters.value = next
}

async function copyPeerId() {
  try {
    await navigator.clipboard.writeText(props.peerId)
  } catch {
    // Clipboard not available
  }
}

const eventTypeBadge: Record<string, string> = {
  heartbeat: 'bg-green-100 text-green-700',
  tee_quote: 'bg-blue-100 text-blue-700',
  mock_work: 'bg-purple-100 text-purple-700',
  work_record: 'bg-purple-100 text-purple-700',
  overwatch: 'bg-red-100 text-red-700',
  unknown: 'bg-gray-100 text-gray-600',
}

const eventTypeBorder: Record<string, string> = {
  heartbeat: 'border-l-green-400',
  tee_quote: 'border-l-blue-400',
  mock_work: 'border-l-purple-400',
  work_record: 'border-l-purple-400',
  overwatch: 'border-l-red-400',
  unknown: 'border-l-gray-300',
}

onMounted(async () => {
  const result = await api.fetchNodeHistory(props.peerId)
  events.value = result.events
  node.value = result.node
  loading.value = false
})
</script>

<template>
  <div>
    <!-- Back navigation -->
    <button
      class="mb-4 text-sm text-green-600 hover:text-green-800 flex items-center gap-1"
      @click="router.push({ name: 'node-detail', params: { peerId } })"
    >
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
      </svg>
      Back to Node Detail
    </button>

    <div v-if="loading" class="text-center py-12 text-gray-400">Loading node history...</div>

    <div v-else>
      <!-- Node header -->
      <div class="bg-white border border-green-200 rounded-lg p-4 mb-6">
        <div class="flex items-center justify-between flex-wrap gap-2">
          <div>
            <div class="flex items-center gap-2 mb-1">
              <h2 class="text-lg font-bold text-gray-800">
                Node #{{ node?.subnet_node_id ?? '?' }} History
              </h2>
              <StatusBadge :status="node?.status ?? 'offline'" />
            </div>
            <div class="flex items-center gap-2 text-sm text-gray-500 font-mono">
              <span>{{ truncatedPeerId }}</span>
              <button
                class="text-green-500 hover:text-green-700 text-xs"
                title="Copy full peer ID"
                @click="copyPeerId"
              >
                Copy
              </button>
            </div>
          </div>
          <div class="text-right text-sm text-gray-500">
            <div>TEE Score: <span class="font-medium text-gray-800">{{ (node?.tee_score ?? 0).toFixed(2) }}</span></div>
            <div>{{ events.length }} total events</div>
          </div>
        </div>
      </div>

      <!-- Type filter chips -->
      <div v-if="allEventTypes.length > 0" class="flex flex-wrap gap-2 mb-4">
        <span class="text-xs text-gray-500 leading-6">Filter:</span>
        <button
          v-for="type in allEventTypes"
          :key="type"
          class="px-2.5 py-1 rounded-full text-xs font-medium border transition-colors"
          :class="activeFilters.has(type)
            ? 'bg-green-500 text-white border-green-500'
            : 'bg-white text-gray-600 border-green-200 hover:bg-green-50'"
          @click="toggleFilter(type)"
        >
          {{ type }}
        </button>
        <button
          v-if="activeFilters.size > 0"
          class="px-2.5 py-1 rounded-full text-xs font-medium text-gray-500 hover:text-gray-700"
          @click="activeFilters = new Set()"
        >
          Clear
        </button>
      </div>

      <!-- Event timeline -->
      <div v-if="displayedEvents.length === 0" class="text-center py-12 text-gray-400">
        No events found{{ activeFilters.size > 0 ? ' matching filters' : '' }}
      </div>

      <div v-else class="space-y-2">
        <div
          v-for="(event, index) in displayedEvents"
          :key="`${event.key}-${index}`"
          class="bg-white border border-green-200 rounded-lg px-4 py-3 border-l-4"
          :class="eventTypeBorder[(event.data?.type as string)] || eventTypeBorder.unknown"
        >
          <div class="flex items-center justify-between mb-1">
            <div class="flex items-center gap-2">
              <span
                class="px-2 py-0.5 rounded text-xs font-medium"
                :class="eventTypeBadge[(event.data?.type as string)] || eventTypeBadge.unknown"
              >
                {{ event.data?.type || 'unknown' }}
              </span>
              <span class="text-xs text-gray-500">Epoch {{ event.epoch }}</span>
            </div>
            <router-link
              :to="{ name: 'epoch-detail', params: { epoch: String(event.epoch) } }"
              class="text-xs text-green-600 hover:text-green-800"
            >
              View Epoch
            </router-link>
          </div>
          <div class="text-xs text-gray-500 mt-1 flex flex-wrap gap-3">
            <span v-if="event.data?.tee_score !== undefined">TEE: {{ (event.data.tee_score as number).toFixed(2) }}</span>
            <span v-if="event.data?.gpu">GPU: {{ event.data.gpu }}</span>
            <span v-if="event.data?.tampered !== undefined">
              Tampered: <span :class="event.data.tampered ? 'text-red-600 font-medium' : 'text-green-600'">{{ event.data.tampered ? 'Yes' : 'No' }}</span>
            </span>
            <span v-if="event.data?.parity_ok !== undefined">
              Parity: <span :class="event.data.parity_ok ? 'text-green-600' : 'text-red-600 font-medium'">{{ event.data.parity_ok ? 'OK' : 'Fail' }}</span>
            </span>
          </div>
        </div>

        <!-- Load More -->
        <button
          v-if="hasMore"
          class="w-full py-3 text-sm text-green-600 hover:text-green-800 hover:bg-green-50 border border-green-200 rounded-lg mt-4"
          @click="loadMore"
        >
          Load more ({{ filteredEvents.length - displayLimit }} remaining)
        </button>
      </div>
    </div>
  </div>
</template>
