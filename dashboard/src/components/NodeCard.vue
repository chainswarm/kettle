<script setup lang="ts">
import { computed } from 'vue'
import type { SubnetNode } from '../types'
import StatusBadge from './StatusBadge.vue'
import { truncateAddress } from '../utils'

const props = defineProps<{
  node: SubnetNode
}>()

const truncatedPeerId = computed(() => truncateAddress(props.node.peer_id))

const teeScorePercent = computed(() => Math.round(props.node.tee_score * 100))
</script>

<template>
  <router-link
    :to="{ name: 'node-detail', params: { peerId: node.peer_id } }"
    class="block bg-white rounded-lg border transition-colors hover:bg-green-50 cursor-pointer"
    :class="node.status === 'online' ? 'border-l-4 border-l-green-400 border-green-200' : 'border-l-4 border-l-gray-300 border-gray-200'"
  >
    <div class="p-4">
      <div class="flex items-center justify-between mb-3">
        <span class="text-sm font-semibold text-gray-700">
          Node #{{ node.subnet_node_id }}
        </span>
        <StatusBadge :status="node.status" />
      </div>

      <div class="text-xs text-gray-500 font-mono mb-3">
        {{ truncatedPeerId }}
      </div>

      <div class="mb-3">
        <div class="flex items-center justify-between text-xs mb-1">
          <span class="text-gray-500">TEE Score</span>
          <span class="font-medium" :class="node.tee_score >= 0.5 ? 'text-green-600' : 'text-gray-500'">
            {{ node.tee_score.toFixed(2) }}
          </span>
        </div>
        <div class="w-full h-1.5 bg-gray-100 rounded-full overflow-hidden">
          <div
            class="h-full rounded-full transition-all duration-500"
            :class="node.tee_score >= 0.5 ? 'bg-gradient-to-r from-green-300 to-green-500' : 'bg-gray-300'"
            :style="{ width: `${teeScorePercent}%` }"
          ></div>
        </div>
      </div>

      <div class="flex items-center justify-between text-xs text-gray-500">
        <span v-if="node.gpu" class="truncate mr-2">{{ node.gpu }}</span>
        <span v-else class="text-gray-400">No GPU</span>
        <span>Epoch {{ node.epoch }}</span>
      </div>
    </div>
  </router-link>
</template>
