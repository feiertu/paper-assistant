import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<string | null>(localStorage.getItem('pa_user'))
  const ownerId = ref<string>(localStorage.getItem('pa_owner_id') || generateId())

  function generateId(): string {
    const id = crypto.randomUUID?.() || Math.random().toString(36).substring(2)
    return id
  }

  const isLoggedIn = computed(() => user.value !== null)

  // Persist ownerId for session continuity
  function persistOwnerId() {
    localStorage.setItem('pa_owner_id', ownerId.value)
    // Also set cookie for backend recognition
    const d = new Date()
    d.setTime(d.getTime() + 30 * 86400000) // 30 days
    document.cookie = `paper_session=${ownerId.value};path=/;expires=${d.toUTCString()}`
  }

  function login(username: string) {
    user.value = username
    localStorage.setItem('pa_user', username)
    persistOwnerId()
  }

  function logout() {
    user.value = null
    localStorage.removeItem('pa_user')
  }

  // Initialize
  persistOwnerId()

  return {
    user,
    ownerId,
    isLoggedIn,
    login,
    logout,
  }
})
