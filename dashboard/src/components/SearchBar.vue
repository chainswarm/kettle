<script setup lang="ts">
import { ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useExplorerApi } from '../composables/useExplorerApi'
import type { SearchResult } from '../types'

const router = useRouter()
const api = useExplorerApi()

const query = ref('')
const results = ref<SearchResult[]>([])
const showDropdown = ref(false)
const searching = ref(false)

let debounceTimer: ReturnType<typeof setTimeout> | null = null

watch(query, (val) => {
  if (debounceTimer) clearTimeout(debounceTimer)
  if (!val || val.trim().length === 0) {
    results.value = []
    showDropdown.value = false
    return
  }
  debounceTimer = setTimeout(async () => {
    searching.value = true
    results.value = await api.search(val)
    showDropdown.value = results.value.length > 0
    searching.value = false
  }, 300)
})

function navigateTo(result: SearchResult) {
  showDropdown.value = false
  query.value = ''
  results.value = []
  router.push(result.route)
}

function onBlur() {
  // Delay to allow click on result
  setTimeout(() => {
    showDropdown.value = false
  }, 200)
}

function onFocus() {
  if (results.value.length > 0) {
    showDropdown.value = true
  }
}

const typeIcons: Record<string, string> = {
  node: 'N',
  epoch: 'E',
  event: 'Ev',
}

const typeColors: Record<string, string> = {
  node: 'bg-green-100 text-green-700',
  epoch: 'bg-blue-100 text-blue-700',
  event: 'bg-purple-100 text-purple-700',
}
</script>

<template>
  <div class="relative">
    <div class="relative">
      <svg
        class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400"
        fill="none" stroke="currentColor" viewBox="0 0 24 24"
      >
        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
      </svg>
      <input
        v-model="query"
        type="text"
        placeholder="Search nodes, epochs..."
        class="w-40 sm:w-52 pl-8 pr-3 py-1.5 text-xs border border-green-200 rounded-lg bg-white focus:outline-none focus:ring-1 focus:ring-green-400 focus:border-green-400 placeholder-gray-400"
        @focus="onFocus"
        @blur="onBlur"
      />
    </div>

    <!-- Dropdown results -->
    <div
      v-if="showDropdown"
      class="absolute top-full mt-1 right-0 w-72 bg-white border border-green-200 rounded-lg shadow-lg overflow-hidden z-50"
    >
      <div
        v-for="(result, index) in results"
        :key="index"
        class="px-3 py-2 hover:bg-green-50 cursor-pointer flex items-center gap-2 border-b border-gray-50 last:border-0"
        @mousedown.prevent="navigateTo(result)"
      >
        <span
          class="w-6 h-6 rounded flex items-center justify-center text-[10px] font-bold flex-shrink-0"
          :class="typeColors[result.type] || 'bg-gray-100 text-gray-600'"
        >
          {{ typeIcons[result.type] || '?' }}
        </span>
        <div class="min-w-0">
          <div class="text-sm font-medium text-gray-800 truncate">{{ result.label }}</div>
          <div class="text-xs text-gray-500 truncate">{{ result.description }}</div>
        </div>
      </div>
    </div>
  </div>
</template>
