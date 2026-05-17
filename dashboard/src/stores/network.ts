import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { SubnetNode, DHTEvent, TopologyData, OverwatchEvent, NodeDetail } from '../types'

export const useNetworkStore = defineStore('network', () => {
  const nodes = ref<Map<string, SubnetNode>>(new Map())
  const events = ref<DHTEvent[]>([])
  const topology = ref<TopologyData>({ nodes: [], edges: [] })
  const overwatchEvents = ref<OverwatchEvent[]>([])

  const MAX_EVENTS = 200
  const MAX_OVERWATCH = 100

  async function fetchNodes() {
    try {
      const res = await fetch('/api/nodes')
      if (!res.ok) return
      const data: SubnetNode[] = await res.json()
      const m = new Map<string, SubnetNode>()
      for (const node of data) {
        m.set(node.peer_id, node)
      }
      nodes.value = m
    } catch {
      // Silently fail — will retry on next poll or WebSocket event
    }
  }

  async function fetchNodeDetail(peerId: string): Promise<NodeDetail | null> {
    try {
      const res = await fetch(`/api/nodes/${encodeURIComponent(peerId)}`)
      if (!res.ok) return null
      return await res.json()
    } catch {
      return null
    }
  }

  async function fetchTopology() {
    try {
      const res = await fetch('/api/topology')
      if (!res.ok) return
      topology.value = await res.json()
    } catch {
      // Silently fail
    }
  }

  async function fetchOverwatch() {
    try {
      const res = await fetch('/api/overwatch')
      if (!res.ok) return
      const data: OverwatchEvent[] = await res.json()
      overwatchEvents.value = data.slice(0, MAX_OVERWATCH)
    } catch {
      // Silently fail
    }
  }

  function handleEvent(event: DHTEvent) {
    // Prepend to events array (newest first), cap at MAX_EVENTS
    events.value = [event, ...events.value].slice(0, MAX_EVENTS)

    // Update node state for heartbeat events
    if (event.type === 'heartbeat' && event.data) {
      const peerId = event.data.peer_id as string
      if (peerId) {
        const existing = nodes.value.get(peerId)
        const updated: SubnetNode = {
          peer_id: peerId,
          subnet_node_id: (event.data.subnet_node_id as number) ?? existing?.subnet_node_id ?? 0,
          epoch: (event.data.epoch as number) ?? existing?.epoch ?? 0,
          tee_score: (event.data.tee_score as number) ?? existing?.tee_score ?? 0,
          gpu: (event.data.gpu as string | null) ?? existing?.gpu ?? null,
          gpu_uuid: (event.data.gpu_uuid as string | null) ?? existing?.gpu_uuid ?? null,
          gpu_attested: (event.data.gpu_attested as boolean) ?? existing?.gpu_attested ?? false,
          models: (event.data.models as string[] | null) ?? existing?.models ?? null,
          status: 'online',
          last_seen: event.timestamp,
        }
        const m = new Map(nodes.value)
        m.set(peerId, updated)
        nodes.value = m
      }
    }

    // Track overwatch-relevant events
    if (event.type === 'work_record' && event.data) {
      const tampered = event.data.tampered as boolean
      const parityOk = event.data.parity_ok as boolean
      if (tampered || parityOk === false) {
        const owEvent: OverwatchEvent = {
          epoch: (event.data.epoch as number) ?? 0,
          peer_id: (event.data.peer_id as string) ?? 'unknown',
          result: tampered ? 'tampered' : 'fail',
          details: tampered ? 'Work record flagged as tampered' : 'Parity mismatch detected',
        }
        overwatchEvents.value = [owEvent, ...overwatchEvents.value].slice(0, MAX_OVERWATCH)
      }
    }
  }

  return {
    nodes,
    events,
    topology,
    overwatchEvents,
    fetchNodes,
    fetchNodeDetail,
    fetchTopology,
    fetchOverwatch,
    handleEvent,
  }
})
