<script setup lang="ts">
import { computed, ref, reactive } from 'vue'
import { useRouter } from 'vue-router'
import type { TopologyData } from '../types'
import { truncateAddress } from '../utils'

const props = defineProps<{
  topology: TopologyData
}>()

const router = useRouter()

const svgSize = 400
const centerX = svgSize / 2
const centerY = svgSize / 2
const radius = 140

// Track dragged node offsets (peer_id → {dx, dy})
const offsets = reactive<Record<string, { dx: number; dy: number }>>({})
const dragging = ref<string | null>(null)
const dragStart = ref<{ x: number; y: number } | null>(null)
const dragDistance = ref(0)
const svgRef = ref<SVGSVGElement | null>(null)

function getBasePosition(index: number, total: number) {
  const angle = (2 * Math.PI * index) / total - Math.PI / 2
  return {
    x: centerX + radius * Math.cos(angle),
    y: centerY + radius * Math.sin(angle),
  }
}

const nodePositions = computed(() => {
  const nodes = props.topology.nodes
  if (nodes.length === 0) return []

  return nodes.map((node, index) => {
    const base = getBasePosition(index, nodes.length)
    const offset = offsets[node.peer_id] || { dx: 0, dy: 0 }
    return {
      ...node,
      x: base.x + offset.dx,
      y: base.y + offset.dy,
    }
  })
})

const edgeLines = computed(() => {
  const positions = nodePositions.value
  if (positions.length === 0) return []

  const posMap = new Map(positions.map(p => [p.peer_id, p]))

  return props.topology.edges
    .map(edge => {
      const from = posMap.get(edge.from)
      const to = posMap.get(edge.to)
      if (!from || !to) return null
      return { x1: from.x, y1: from.y, x2: to.x, y2: to.y }
    })
    .filter((e): e is NonNullable<typeof e> => e !== null)
})

function svgPoint(event: MouseEvent | TouchEvent): { x: number; y: number } | null {
  const svg = svgRef.value
  if (!svg) return null
  const rect = svg.getBoundingClientRect()
  const clientX = 'touches' in event ? event.touches[0].clientX : event.clientX
  const clientY = 'touches' in event ? event.touches[0].clientY : event.clientY
  return {
    x: ((clientX - rect.left) / rect.width) * svgSize,
    y: ((clientY - rect.top) / rect.height) * svgSize,
  }
}

function onPointerDown(peerId: string, event: MouseEvent | TouchEvent) {
  event.preventDefault()
  const pt = svgPoint(event)
  if (!pt) return
  dragging.value = peerId
  dragStart.value = pt
  dragDistance.value = 0
}

function onPointerMove(event: MouseEvent | TouchEvent) {
  if (!dragging.value || !dragStart.value) return
  const pt = svgPoint(event)
  if (!pt) return
  const dx = pt.x - dragStart.value.x
  const dy = pt.y - dragStart.value.y
  dragDistance.value += Math.abs(dx) + Math.abs(dy)
  const peerId = dragging.value
  const prev = offsets[peerId] || { dx: 0, dy: 0 }
  offsets[peerId] = { dx: prev.dx + dx, dy: prev.dy + dy }
  dragStart.value = pt
}

function onPointerUp() {
  // Click (not drag) → navigate to node detail
  if (dragging.value && dragDistance.value < 5) {
    router.push({ name: 'node-detail', params: { peerId: dragging.value } })
  }
  dragging.value = null
  dragStart.value = null
}

// truncateAddress imported from utils.ts
</script>

<template>
  <div class="bg-white border border-green-200 rounded-lg overflow-hidden">
    <div class="px-3 py-2 bg-green-50 border-b border-green-200">
      <h3 class="text-sm font-semibold text-gray-700">Network Topology</h3>
    </div>
    <div class="p-4 flex items-center justify-center">
      <svg
        v-if="nodePositions.length > 0"
        ref="svgRef"
        :viewBox="`0 0 ${svgSize} ${svgSize}`"
        class="w-full max-w-[400px] select-none"
        @mousemove="onPointerMove"
        @mouseup="onPointerUp"
        @mouseleave="onPointerUp"
        @touchmove.prevent="onPointerMove"
        @touchend="onPointerUp"
      >
        <!-- Edges -->
        <line
          v-for="(edge, i) in edgeLines"
          :key="`edge-${i}`"
          :x1="edge.x1"
          :y1="edge.y1"
          :x2="edge.x2"
          :y2="edge.y2"
          stroke="#bbf7d0"
          stroke-width="2"
        />

        <!-- Nodes -->
        <g
          v-for="node in nodePositions"
          :key="node.peer_id"
          :class="{ 'cursor-grabbing': dragging === node.peer_id, 'cursor-grab': dragging !== node.peer_id }"
          @mousedown="onPointerDown(node.peer_id, $event)"
          @touchstart.prevent="onPointerDown(node.peer_id, $event)"
        >
          <circle
            :cx="node.x"
            :cy="node.y"
            r="20"
            :fill="node.status === 'online' ? '#4ade80' : '#d1d5db'"
            stroke="white"
            stroke-width="3"
          />
          <!-- Node ID inside circle -->
          <text
            :x="node.x"
            :y="node.y"
            text-anchor="middle"
            dominant-baseline="central"
            class="text-[11px] font-bold fill-white pointer-events-none"
          >
            #{{ node.subnet_node_id }}
          </text>
          <!-- Peer ID label below -->
          <text
            :x="node.x"
            :y="node.y + 32"
            text-anchor="middle"
            class="text-[9px] fill-gray-500 pointer-events-none font-mono"
          >
            {{ truncateAddress(node.peer_id) }}
          </text>
          <title>{{ node.peer_id }} (Node #{{ node.subnet_node_id }}, {{ node.status }})</title>
        </g>
      </svg>
      <div
        v-else
        class="text-sm text-gray-400 py-8"
      >
        No topology data available
      </div>
    </div>
  </div>
</template>
