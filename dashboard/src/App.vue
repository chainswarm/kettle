<script setup lang="ts">
import { onMounted } from 'vue'
import AppHeader from './components/AppHeader.vue'
import { useWebSocket } from './composables/useWebSocket'
import { useNetworkStore } from './stores/network'

const { connected, connect } = useWebSocket()
const store = useNetworkStore()

onMounted(() => {
  connect()
  store.fetchNodes()
  store.fetchTopology()
  store.fetchOverwatch()

  // Periodic refresh of REST data
  setInterval(() => {
    store.fetchNodes()
    store.fetchTopology()
    store.fetchOverwatch()
  }, 10000)
})
</script>

<template>
  <div class="min-h-screen bg-white">
    <AppHeader :connected="connected" />
    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
      <router-view />
    </main>
  </div>
</template>
