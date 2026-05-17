import type { ExplorerEpoch, ExplorerEvent, OverwatchEvent, SearchResult, SubnetNode } from '../types'

/**
 * Composable for explorer-specific API calls.
 * Wraps the existing /api/* endpoints with explorer-oriented data shaping.
 */
export function useExplorerApi() {
  /**
   * Fetch events grouped by epoch across all topics.
   * Returns epochs sorted newest-first with event counts and participating peers.
   */
  async function fetchEpochs(page = 1, limit = 20): Promise<{ epochs: ExplorerEpoch[]; hasMore: boolean }> {
    const topics = ['heartbeat', 'tee_quote', 'mock_work'] as const
    const allEvents: ExplorerEvent[] = []

    const responses = await Promise.all(
      topics.map(topic =>
        fetch(`/api/events?topic=${topic}&limit=500`)
          .then(r => (r.ok ? r.json() : []))
          .catch(() => [])
      )
    )

    for (const events of responses) {
      if (Array.isArray(events)) {
        allEvents.push(...events)
      }
    }

    // Group by epoch
    const epochMap = new Map<number, { eventsByType: Record<string, number>; peerIds: Set<string> }>()

    for (const event of allEvents) {
      const epoch = event.epoch ?? 0
      if (!epochMap.has(epoch)) {
        epochMap.set(epoch, { eventsByType: {}, peerIds: new Set() })
      }
      const entry = epochMap.get(epoch)!
      const eventType = (event.data?.type as string) || 'unknown'
      entry.eventsByType[eventType] = (entry.eventsByType[eventType] || 0) + 1
      if (event.peer_id) {
        entry.peerIds.add(event.peer_id)
      }
    }

    // Convert to array, sort newest first
    const allEpochs: ExplorerEpoch[] = Array.from(epochMap.entries())
      .map(([epoch, data]) => ({
        epoch,
        eventCount: Object.values(data.eventsByType).reduce((a, b) => a + b, 0),
        eventsByType: data.eventsByType,
        peerIds: Array.from(data.peerIds),
      }))
      .sort((a, b) => b.epoch - a.epoch)

    const start = (page - 1) * limit
    const paged = allEpochs.slice(start, start + limit)

    return { epochs: paged, hasMore: start + limit < allEpochs.length }
  }

  /**
   * Fetch all events for a specific epoch across all topics.
   */
  async function fetchEpochEvents(epoch: number): Promise<ExplorerEvent[]> {
    const topics = ['heartbeat', 'tee_quote', 'mock_work'] as const
    const allEvents: ExplorerEvent[] = []

    const responses = await Promise.all(
      topics.map(topic =>
        fetch(`/api/events?topic=${topic}&limit=500`)
          .then(r => (r.ok ? r.json() : []))
          .catch(() => [])
      )
    )

    for (const events of responses) {
      if (Array.isArray(events)) {
        for (const event of events) {
          if (event.epoch === epoch) {
            allEvents.push(event)
          }
        }
      }
    }

    return allEvents.sort((a, b) => {
      const ta = a.data?.timestamp as string || ''
      const tb = b.data?.timestamp as string || ''
      return tb.localeCompare(ta)
    })
  }

  /**
   * Fetch full history for a specific node: detail + all events mentioning this peer.
   */
  async function fetchNodeHistory(peerId: string): Promise<{
    events: ExplorerEvent[]
    node: SubnetNode | null
  }> {
    const topics = ['heartbeat', 'tee_quote', 'mock_work'] as const
    const allEvents: ExplorerEvent[] = []

    const [eventsResponses, nodesRes] = await Promise.all([
      Promise.all(
        topics.map(topic =>
          fetch(`/api/events?topic=${topic}&limit=500`)
            .then(r => (r.ok ? r.json() : []))
            .catch(() => [])
        )
      ),
      fetch('/api/nodes').then(r => (r.ok ? r.json() : [])).catch(() => []),
    ])

    for (const events of eventsResponses) {
      if (Array.isArray(events)) {
        for (const event of events) {
          if (event.peer_id === peerId) {
            allEvents.push(event)
          }
        }
      }
    }

    const node = Array.isArray(nodesRes)
      ? (nodesRes as SubnetNode[]).find(n => n.peer_id === peerId) ?? null
      : null

    return {
      events: allEvents.sort((a, b) => b.epoch - a.epoch),
      node,
    }
  }

  /**
   * Fetch overwatch audit log with optional result filter.
   */
  async function fetchAuditLog(filter?: 'pass' | 'fail' | 'tampered'): Promise<OverwatchEvent[]> {
    try {
      const res = await fetch('/api/overwatch')
      if (!res.ok) return []
      const events: OverwatchEvent[] = await res.json()
      if (filter) {
        return events.filter(e => e.result === filter)
      }
      return events
    } catch {
      return []
    }
  }

  /**
   * Search across nodes and epochs. Returns categorized results.
   */
  async function search(query: string): Promise<SearchResult[]> {
    if (!query || query.trim().length === 0) return []

    const q = query.trim().toLowerCase()
    const results: SearchResult[] = []

    try {
      // Search nodes
      const nodesRes = await fetch('/api/nodes')
      if (nodesRes.ok) {
        const nodes: SubnetNode[] = await nodesRes.json()
        for (const node of nodes) {
          if (
            node.peer_id.toLowerCase().includes(q) ||
            String(node.subnet_node_id).includes(q) ||
            (node.gpu && node.gpu.toLowerCase().includes(q))
          ) {
            results.push({
              type: 'node',
              label: `Node #${node.subnet_node_id}`,
              description: `${node.peer_id.slice(0, 12)}... - ${node.status}`,
              route: { name: 'node-detail', params: { peerId: node.peer_id } },
            })
          }
        }
      }

      // Search by epoch number
      const epochNum = parseInt(q, 10)
      if (!isNaN(epochNum) && epochNum >= 0) {
        results.push({
          type: 'epoch',
          label: `Epoch ${epochNum}`,
          description: 'View epoch events',
          route: { name: 'epoch-detail', params: { epoch: String(epochNum) } },
        })
      }

      // Search event types
      const eventTypes = ['heartbeat', 'tee_quote', 'work_record', 'overwatch', 'node_join', 'node_leave']
      for (const eventType of eventTypes) {
        if (eventType.includes(q)) {
          results.push({
            type: 'event',
            label: eventType,
            description: 'Event type',
            route: { name: 'epochs' },
          })
        }
      }
    } catch {
      // Search is best-effort
    }

    return results.slice(0, 10)
  }

  return { fetchEpochs, fetchEpochEvents, fetchNodeHistory, fetchAuditLog, search }
}
