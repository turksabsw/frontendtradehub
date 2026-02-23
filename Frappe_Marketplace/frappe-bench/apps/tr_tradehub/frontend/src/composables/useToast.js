import { ref } from 'vue'

const toasts = ref([])
let toastId = 0

export function useToast() {
  function show(message, type = 'info') {
    const id = ++toastId
    const icons = {
      success: 'fas fa-check-circle text-emerald-500',
      error: 'fas fa-times-circle text-red-500',
      info: 'fas fa-info-circle text-violet-500',
    }
    toasts.value.push({ id, message, type, icon: icons[type] || icons.info })

    setTimeout(() => {
      remove(id)
    }, 3500)
  }

  function remove(id) {
    const idx = toasts.value.findIndex(t => t.id === id)
    if (idx !== -1) {
      toasts.value[idx].removing = true
      setTimeout(() => {
        toasts.value = toasts.value.filter(t => t.id !== id)
      }, 300)
    }
  }

  function success(message) { show(message, 'success') }
  function error(message) { show(message, 'error') }
  function info(message) { show(message, 'info') }

  return { toasts, show, remove, success, error, info }
}
