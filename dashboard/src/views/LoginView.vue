<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const auth = useAuthStore()
const tokenInput = ref('')
const error = ref('')

function handleLogin() {
  if (!tokenInput.value.trim()) {
    error.value = 'Please enter an admin token'
    return
  }
  auth.login(tokenInput.value.trim())
  router.push('/admin')
}
</script>

<template>
  <div class="flex items-center justify-center min-h-[60vh]">
    <div class="bg-white border border-green-200 rounded-lg p-6 w-full max-w-sm shadow-sm">
      <h2 class="text-lg font-bold text-gray-800 mb-1 text-center">Admin Login</h2>
      <p class="text-sm text-gray-500 mb-4 text-center">
        Enter your dashboard admin token
      </p>

      <form @submit.prevent="handleLogin">
        <div class="mb-4">
          <label class="block text-sm text-gray-600 mb-1" for="token">Token</label>
          <input
            id="token"
            v-model="tokenInput"
            type="password"
            class="w-full px-3 py-2 border border-gray-300 rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-green-400 focus:border-green-400"
            placeholder="Enter admin token"
          />
        </div>

        <div v-if="error" class="text-sm text-red-500 mb-3">{{ error }}</div>

        <button
          type="submit"
          class="w-full bg-green-500 text-white py-2 px-4 rounded-md text-sm font-medium hover:bg-green-600 transition-colors"
        >
          Login
        </button>
      </form>

      <p class="text-xs text-gray-400 mt-4 text-center">
        The token is set via the DASHBOARD_AUTH_TOKEN environment variable on the server.
      </p>
    </div>
  </div>
</template>
