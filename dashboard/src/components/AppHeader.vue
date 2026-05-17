<script setup lang="ts">
import { useAuthStore } from '../stores/auth'
import SearchBar from './SearchBar.vue'

defineProps<{
  connected: boolean
}>()

const auth = useAuthStore()
</script>

<template>
  <header class="bg-white border-b border-green-200 sticky top-0 z-50">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
      <div class="flex items-center justify-between h-14">
        <div class="flex items-center gap-2">
          <div class="w-8 h-8 bg-green-500 rounded-lg flex items-center justify-center">
            <svg class="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
          </div>
          <h1 class="text-lg font-semibold text-gray-800">TEE Subnet Monitor</h1>
        </div>

        <nav class="flex items-center gap-4 sm:gap-6">
          <router-link
            to="/"
            class="text-sm font-medium text-gray-600 hover:text-green-600 transition-colors"
            active-class="text-green-600"
          >
            Explorer
          </router-link>
          <router-link
            to="/epochs"
            class="text-sm font-medium text-gray-600 hover:text-green-600 transition-colors"
            active-class="text-green-600"
          >
            Epochs
          </router-link>
          <router-link
            to="/audit-log"
            class="text-sm font-medium text-gray-600 hover:text-green-600 transition-colors"
            active-class="text-green-600"
          >
            Audit Log
          </router-link>
          <router-link
            v-if="auth.isAuthenticated"
            to="/admin"
            class="text-sm font-medium text-gray-600 hover:text-green-600 transition-colors"
            active-class="text-green-600"
          >
            Admin
          </router-link>
          <router-link
            v-else
            to="/login"
            class="text-sm font-medium text-gray-600 hover:text-green-600 transition-colors"
            active-class="text-green-600"
          >
            Login
          </router-link>

          <SearchBar />

          <div class="flex items-center gap-1.5">
            <span
              class="w-2.5 h-2.5 rounded-full"
              :class="connected ? 'bg-green-500 animate-pulse' : 'bg-red-400'"
            ></span>
            <span class="text-xs text-gray-500">{{ connected ? 'Live' : 'Offline' }}</span>
          </div>
        </nav>
      </div>
    </div>
  </header>
</template>
