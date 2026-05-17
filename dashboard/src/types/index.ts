export interface SubnetNode {
  peer_id: string
  subnet_node_id: number
  epoch: number
  tee_score: number
  gpu: string | null
  gpu_uuid: string | null
  gpu_attested: boolean
  models: string[] | null
  status: 'online' | 'offline'
  last_seen: string
  vram_total_gb?: number | null
  vram_used_gb?: number | null
  requests_in_flight?: number
  latency_p95_ms?: number
  nim_version?: string | null
}

export interface DHTEvent {
  type: 'heartbeat' | 'tee_quote' | 'work_record' | 'mock_work' | 'overwatch' | 'node_join' | 'node_leave'
  data: Record<string, unknown>
  timestamp: string
}

export interface TopologyData {
  nodes: { peer_id: string; subnet_node_id: number; status: string }[]
  edges: { from: string; to: string }[]
}

export interface OverwatchEvent {
  epoch: number
  peer_id: string
  result: 'pass' | 'fail' | 'tampered'
  details: string
  data?: Record<string, unknown>
}

export interface NodeDetail {
  heartbeat: Record<string, unknown> | null
  tee_quote: Record<string, unknown> | null
  work_record: Record<string, unknown> | null
}

export interface DbStats {
  nmaps: { name: string; count: number }[]
  total_entries: number
}

export interface ExplorerEpoch {
  epoch: number
  eventCount: number
  eventsByType: Record<string, number>
  peerIds: string[]
}

export interface ExplorerEvent {
  key: string
  epoch: number
  peer_id: string
  data: Record<string, unknown>
}

export interface SearchResult {
  type: 'node' | 'epoch' | 'event'
  label: string
  description: string
  route: { name: string; params?: Record<string, string> }
}
