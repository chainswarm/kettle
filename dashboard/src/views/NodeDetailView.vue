<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useNetworkStore } from '../stores/network'
import type { NodeDetail } from '../types'
import StatusBadge from '../components/StatusBadge.vue'

const props = defineProps<{
  peerId: string
}>()

const router = useRouter()
const store = useNetworkStore()
const detail = ref<NodeDetail | null>(null)
const loading = ref(true)

const node = computed(() => store.nodes.get(props.peerId))

import { truncateAddress } from '../utils'

const truncatedPeerId = computed(() => truncateAddress(props.peerId))

const teeScorePercent = computed(() => {
  const hb = detail.value?.heartbeat
  const score = (hb?.tee_score as number) ?? node.value?.tee_score ?? 0
  return Math.round(score * 100)
})

const recentEvents = computed(() =>
  store.events
    .filter(e => e.data?.peer_id === props.peerId)
    .slice(0, 20)
)

async function copyPeerId() {
  try {
    await navigator.clipboard.writeText(props.peerId)
  } catch {
    // Clipboard not available
  }
}

onMounted(async () => {
  detail.value = await store.fetchNodeDetail(props.peerId)
  loading.value = false
})
</script>

<template>
  <div>
    <button
      class="mb-4 text-sm text-green-600 hover:text-green-800 flex items-center gap-1"
      @click="router.push('/')"
    >
      <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7" />
      </svg>
      Back to Explorer
    </button>

    <div v-if="loading" class="text-center py-12 text-gray-400">Loading node details...</div>

    <div v-else>
      <!-- Header -->
      <div class="bg-white border border-green-200 rounded-lg p-4 mb-4">
        <div class="flex items-center justify-between flex-wrap gap-2">
          <div>
            <div class="flex items-center gap-2 mb-1">
              <h2 class="text-lg font-bold text-gray-800">
                Node #{{ node?.subnet_node_id ?? detail?.heartbeat?.subnet_node_id ?? '?' }}
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
          <div>
            <router-link
              :to="{ name: 'node-history', params: { peerId } }"
              class="px-3 py-1.5 text-xs font-medium border border-green-200 rounded-lg text-green-600 hover:bg-green-50 transition-colors"
            >
              View Full History
            </router-link>
          </div>
        </div>
      </div>

      <div class="grid grid-cols-1 md:grid-cols-2 gap-4 mb-4">
        <!-- TEE Section -->
        <div class="bg-white border border-green-200 rounded-lg p-4">
          <h3 class="text-sm font-semibold text-gray-700 mb-3">TEE Attestation</h3>
          <div class="space-y-3">
            <div>
              <div class="flex justify-between text-sm mb-1">
                <span class="text-gray-500">TEE Score</span>
                <span class="font-medium text-gray-800">
                  {{ ((detail?.heartbeat?.tee_score as number) ?? node?.tee_score ?? 0).toFixed(2) }}
                </span>
              </div>
              <div class="w-full h-2 bg-gray-100 rounded-full overflow-hidden">
                <div
                  class="h-full rounded-full bg-gradient-to-r from-green-300 to-green-500"
                  :style="{ width: `${teeScorePercent}%` }"
                ></div>
              </div>
            </div>
            <div v-if="detail?.tee_quote" class="text-sm space-y-1">
              <div class="flex justify-between">
                <span class="text-gray-500">Backend</span>
                <span>{{ detail.tee_quote.backend ?? detail.tee_quote.tee_type ?? 'unknown' }}</span>
              </div>
              <div class="flex justify-between">
                <span class="text-gray-500">Last Quote Epoch</span>
                <span>{{ detail.tee_quote.epoch ?? '-' }}</span>
              </div>
            </div>
            <div v-else class="text-sm text-gray-400">No TEE quote data available</div>
          </div>
        </div>

        <!-- Hardware Section -->
        <div class="bg-white border border-green-200 rounded-lg p-4">
          <h3 class="text-sm font-semibold text-gray-700 mb-3">Hardware</h3>
          <div class="text-sm space-y-2">
            <div class="flex justify-between">
              <span class="text-gray-500">GPU</span>
              <span>{{ (detail?.heartbeat?.gpu as string) ?? node?.gpu ?? 'N/A' }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-gray-500">GPU UUID</span>
              <span class="font-mono text-xs">{{ (detail?.heartbeat?.gpu_uuid as string) ?? node?.gpu_uuid ?? 'N/A' }}</span>
            </div>
            <div class="flex justify-between">
              <span class="text-gray-500">GPU Attested</span>
              <span
                class="px-1.5 py-0.5 rounded text-xs"
                :class="(detail?.heartbeat?.gpu_attested ?? node?.gpu_attested)
                  ? 'bg-green-100 text-green-700'
                  : 'bg-gray-100 text-gray-500'"
              >
                {{ (detail?.heartbeat?.gpu_attested ?? node?.gpu_attested) ? 'Yes' : 'No' }}
              </span>
            </div>
            <div v-if="(detail?.heartbeat?.vram_total_gb as number)" class="flex justify-between">
              <span class="text-gray-500">VRAM</span>
              <span>{{ detail?.heartbeat?.vram_used_gb ?? 0 }} / {{ detail?.heartbeat?.vram_total_gb }} GB</span>
            </div>
          </div>
        </div>
      </div>

      <!-- Models Section -->
      <div
        v-if="node?.models && node.models.length > 0"
        class="bg-white border border-green-200 rounded-lg p-4 mb-4"
      >
        <h3 class="text-sm font-semibold text-gray-700 mb-2">Assigned Models</h3>
        <div class="flex flex-wrap gap-2">
          <span
            v-for="model in node.models"
            :key="model"
            class="px-2 py-1 bg-green-50 border border-green-200 rounded text-xs text-gray-700"
          >
            {{ model }}
          </span>
        </div>
      </div>

      <!-- Recent Activity -->
      <div class="bg-white border border-green-200 rounded-lg p-4">
        <h3 class="text-sm font-semibold text-gray-700 mb-3">Recent Activity</h3>
        <div v-if="recentEvents.length === 0" class="text-sm text-gray-400">
          No recent events for this node
        </div>
        <div v-else class="space-y-2">
          <div
            v-for="(event, index) in recentEvents"
            :key="index"
            class="text-xs py-2 border-b border-gray-50"
          >
            <div class="flex items-center gap-2 mb-1">
              <span
                class="px-1.5 py-0.5 rounded"
                :class="{
                  'bg-green-100 text-green-700': event.type === 'heartbeat',
                  'bg-blue-100 text-blue-700': event.type === 'tee_quote',
                  'bg-purple-100 text-purple-700': event.type === 'work_record' || event.type === 'mock_work',
                  'bg-gray-100 text-gray-600': !['heartbeat','tee_quote','work_record','mock_work'].includes(event.type),
                }"
              >{{ event.type }}</span>
              <span class="text-gray-400">Epoch {{ event.data?.epoch }}</span>
            </div>
            <div class="text-gray-500 flex flex-wrap gap-3 ml-1">
              <span v-if="event.data?.tee_score !== undefined">TEE: {{ (event.data.tee_score as number).toFixed(2) }}</span>
              <span v-if="event.data?.subnet_node_id">Node #{{ event.data.subnet_node_id }}</span>
              <span v-if="event.data?.gpu">GPU: {{ event.data.gpu }}</span>
              <span v-if="event.data?.backend">Backend: {{ event.data.backend }}</span>
              <span v-if="event.data?.measurement" class="font-mono">{{ (event.data.measurement as string).slice(0, 12) }}...</span>
              <span v-if="event.data?.tampered !== undefined">
                Tampered: <span :class="event.data.tampered ? 'text-red-600 font-medium' : 'text-green-600'">{{ event.data.tampered ? 'Yes' : 'No' }}</span>
              </span>
              <span v-if="event.data?.parity !== undefined">Parity: {{ event.data.parity }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
