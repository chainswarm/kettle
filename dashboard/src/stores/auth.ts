import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const token = ref<string | null>(localStorage.getItem('dashboard_token'))
  const isAuthenticated = computed(() => token.value !== null && token.value.length > 0)

  function login(newToken: string) {
    token.value = newToken
    localStorage.setItem('dashboard_token', newToken)
  }

  function logout() {
    token.value = null
    localStorage.removeItem('dashboard_token')
  }

  function getAuthHeaders(): Record<string, string> {
    if (token.value) {
      return { Authorization: `Bearer ${token.value}` }
    }
    return {}
  }

  return { token, isAuthenticated, login, logout, getAuthHeaders }
})
