import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/utils/api'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const loading = ref(false)
  const error = ref(null)
  const successMessage = ref(null)

  const isAuthenticated = computed(() => !!user.value)
  const isLoading = computed(() => loading.value)

  const userInitials = computed(() => {
    if (!user.value?.full_name) return '??'
    return user.value.full_name
      .split(' ')
      .map(n => n[0])
      .join('')
      .toUpperCase()
      .substring(0, 2)
  })

  const userName = computed(() => user.value?.full_name || user.value?.email || '')

  async function login(email, password) {
    loading.value = true
    error.value = null
    successMessage.value = null
    try {
      await api.login(email, password)
      await fetchUser()
    } catch (err) {
      error.value = err.message || 'Giriş başarısız'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function fetchUser() {
    try {
      const data = await api.getLoggedUser()
      user.value = data
    } catch {
      user.value = null
    }
  }

  async function logout() {
    try {
      await api.logout()
    } finally {
      user.value = null
      error.value = null
      successMessage.value = null
    }
  }

  async function register(email, fullName) {
    loading.value = true
    error.value = null
    successMessage.value = null
    try {
      await api.register(email, fullName)
      successMessage.value = 'Kayıt başarılı! E-postanızı kontrol edin.'
    } catch (err) {
      error.value = err.message || 'Kayıt başarısız'
      throw err
    } finally {
      loading.value = false
    }
  }

  async function forgotPassword(email) {
    loading.value = true
    error.value = null
    successMessage.value = null
    try {
      await api.forgotPassword(email)
      successMessage.value = 'Şifre sıfırlama bağlantısı e-postanıza gönderildi.'
    } catch (err) {
      error.value = err.message || 'İşlem başarısız'
      throw err
    } finally {
      loading.value = false
    }
  }

  return {
    user,
    loading,
    error,
    successMessage,
    isAuthenticated,
    isLoading,
    userInitials,
    userName,
    login,
    fetchUser,
    logout,
    register,
    forgotPassword,
  }
})
