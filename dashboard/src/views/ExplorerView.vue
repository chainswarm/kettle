<script setup lang="ts">
import { computed } from 'vue'
import { useNetworkStore } from '../stores/network'
import NodeCard from '../components/NodeCard.vue'
import EventFeed from '../components/EventFeed.vue'
import OverwatchFeed from '../components/OverwatchFeed.vue'
import NetworkTopology from '../components/NetworkTopology.vue'

const store = useNetworkStore()

const nodesList = computed(() => Array.from(store.nodes.values()))
const onlineCount = computed(() => nodesList.value.filter(n => n.status === 'online').length)
const currentEpoch = computed(() => Math.max(0, ...nodesList.value.map(n => n.epoch)))
const avgTeeScore = computed(() => {
  if (nodesList.value.length === 0) return 0
  const sum = nodesList.value.reduce((acc, n) => acc + n.tee_score, 0)
  return sum / nodesList.value.length
})
</script>

<template>
  <div>
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
        <div class="text-xs text-gray-500 mb-1">Avg TEE Score</div>
        <div class="text-xl font-bold text-gray-800">{{ avgTeeScore.toFixed(2) }}</div>
      </div>
    </div>

    <!-- Main content: nodes + events -->
    <div class="flex flex-col lg:flex-row gap-6">
      <!-- Left: Node grid (2/3) -->
      <div class="lg:w-2/3">
        <div
          v-if="nodesList.length === 0"
          class="text-center py-12 text-gray-400"
        >
          <p class="text-lg mb-2">No nodes detected yet</p>
          <p class="text-sm">Waiting for heartbeat data from the subnet...</p>
        </div>
        <div
          v-else
          class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4"
        >
          <NodeCard
            v-for="node in nodesList"
            :key="node.peer_id"
            :node="node"
          />
        </div>
      </div>

      <!-- Right: Event feed + Overwatch (1/3) -->
      <div class="lg:w-1/3 space-y-4">
        <EventFeed :events="store.events" />
        <OverwatchFeed :events="store.overwatchEvents" />
      </div>
    </div>

    <!-- Bottom: Network topology -->
    <div class="mt-6">
      <NetworkTopology :topology="store.topology" />
    </div>
  </div>
</template>
