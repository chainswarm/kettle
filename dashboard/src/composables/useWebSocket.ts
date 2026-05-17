import { ref, onUnmounted } from 'vue'
import type { DHTEvent } from '../types'
import { useNetworkStore } from '../stores/network'

export function useWebSocket() {
  const connected = ref(false)
  const lastEvent = ref<DHTEvent | null>(null)
  let ws: WebSocket | null = null
  let reconnectTimeout: ReturnType<typeof setTimeout> | null = null
  let reconnectDelay = 1000
  const maxReconnectDelay = 30000

  function connect() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
    const url = `${protocol}//${location.host}/ws`

    try {
      ws = new WebSocket(url)
    } catch {
      scheduleReconnect()
      return
    }

    ws.onopen = () => {
      connected.value = true
      reconnectDelay = 1000
    }

    ws.onclose = () => {
      connected.value = false
      scheduleReconnect()
    }

    ws.onerror = () => {
      connected.value = false
    }

    ws.onmessage = (event: MessageEvent) => {
      try {
        const parsed: DHTEvent = JSON.parse(event.data)
        lastEvent.value = parsed

        const store = useNetworkStore()
        store.handleEvent(parsed)
      } catch {
        // Ignore malformed messages
      }
    }
  }

  function scheduleReconnect() {
    if (reconnectTimeout) clearTimeout(reconnectTimeout)
    reconnectTimeout = setTimeout(() => {
      reconnectDelay = Math.min(reconnectDelay * 2, maxReconnectDelay)
      connect()
    }, reconnectDelay)
  }

  function disconnect() {
    if (reconnectTimeout) {
      clearTimeout(reconnectTimeout)
      reconnectTimeout = null
    }
    if (ws) {
      ws.close()
      ws = null
    }
    connected.value = false
  }

  onUnmounted(() => {
    disconnect()
  })

  return { connected, lastEvent, connect, disconnect }
}
