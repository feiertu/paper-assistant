import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface Toast {
  id: number
  type: 'success' | 'error' | 'warning' | 'info'
  message: string
}

let nextId = 0

export const useToastStore = defineStore('toast', () => {
  const toasts = ref<Toast[]>([])

  function add(type: Toast['type'], message: string, duration = 4000) {
    const id = nextId++
    toasts.value.push({ id, type, message })
    if (duration > 0) {
      setTimeout(() => remove(id), duration)
    }
  }

  function remove(id: number) {
    toasts.value = toasts.value.filter(t => t.id !== id)
  }

  function success(msg: string) { add('success', msg) }
  function error(msg: string) { add('error', msg, 6000) }
  function warning(msg: string) { add('warning', msg) }
  function info(msg: string) { add('info', msg) }

  return { toasts, add, remove, success, error, warning, info }
})
