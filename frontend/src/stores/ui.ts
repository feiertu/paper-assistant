import { defineStore } from 'pinia'
import { ref } from 'vue'

export const useUiStore = defineStore('ui', () => {
  const sidebarOpen = ref(false) // default hidden; desktop CSS always shows it
  const showAuthDialog = ref(false)
  const authMode = ref<'login' | 'register'>('login')

  function toggleSidebar() {
    sidebarOpen.value = !sidebarOpen.value
  }

  function openAuth(mode: 'login' | 'register' = 'login') {
    authMode.value = mode
    showAuthDialog.value = true
  }

  function closeAuth() {
    showAuthDialog.value = false
  }

  return {
    sidebarOpen,
    showAuthDialog,
    authMode,
    toggleSidebar,
    openAuth,
    closeAuth,
  }
})
