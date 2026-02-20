import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { frappe } from '@/utils/api'
import router from '@/router'

export const useAuthStore = defineStore('auth', () => {

  // State
  const user = ref(null)
  const userInfo = ref(null)
  const isLoading = ref(false)
  const isInitialized = ref(false)
  const error = ref(null)
  const successMessage = ref(null)
  const returnUrl = ref(null)

  // Computed
  const isAuthenticated = computed(
    () => !!user.value && user.value !== 'Guest'
  )
  const fullName = computed(
    () => userInfo.value?.full_name || ''
  )
  const userImage = computed(
    () => userInfo.value?.user_image || null
  )

  // ── Login ──────────────────────────────
  async function login(username, password) {
    isLoading.value = true
    error.value = null
    successMessage.value = null

    try {
      await frappe.login(username, password)
      await fetchCurrentUser()

      const redirect = returnUrl.value || '/'
      returnUrl.value = null
      router.push(redirect)
    } catch (err) {
      const msg = err.response?.data?.message
      if (msg === 'Invalid login credentials') {
        error.value = 'E-posta veya şifre hatalı.'
      } else if (msg?.includes('Too many login attempts')) {
        error.value = 'Çok fazla başarısız deneme. Lütfen biraz bekleyin.'
      } else if (msg?.includes('User disabled or missing')) {
        error.value = 'Bu hesap devre dışı bırakılmış.'
      } else {
        error.value = msg || 'Giriş yapılamadı. Tekrar deneyin.'
      }
      user.value = null
      throw err
    } finally {
      isLoading.value = false
    }
  }

  // ── Register ───────────────────────────
  async function register(email, fullNameInput) {
    isLoading.value = true
    error.value = null
    successMessage.value = null

    try {
      const res = await frappe.register(email, fullNameInput)
      const data = res.data

      // Frappe sign_up yanıtını kontrol et
      // [0] = 1 (başarılı) veya 0 (başarısız)
      // [1] = mesaj
      if (data.message && Array.isArray(data.message)) {
        if (data.message[0] === 1) {
          successMessage.value = 'Kayıt başarılı! E-postanıza gönderilen bağlantıyla şifrenizi oluşturun.'
        } else if (data.message[0] === 0) {
          error.value = data.message[1] || 'Kayıt yapılamadı.'
        } else {
          successMessage.value = data.message[1] || 'İşlem tamamlandı.'
        }
      } else {
        successMessage.value = 'Kayıt başarılı! E-postanızı kontrol edin.'
      }

      return data
    } catch (err) {
      const msg = err.response?.data?.message || err.response?.data?.exc_type
      if (msg?.includes('already registered') || msg?.includes('already exists')) {
        error.value = 'Bu e-posta adresi zaten kayıtlı.'
      } else if (msg?.includes('Not allowed')) {
        error.value = 'Kayıt şu anda kapalıdır.'
      } else {
        error.value = msg || 'Kayıt yapılamadı. Tekrar deneyin.'
      }
      throw err
    } finally {
      isLoading.value = false
    }
  }

  // ── Forgot Password ───────────────────
  async function forgotPassword(email) {
    isLoading.value = true
    error.value = null
    successMessage.value = null

    try {
      await frappe.forgotPassword(email)
      successMessage.value = 'Şifre sıfırlama bağlantısı e-postanıza gönderildi.'
    } catch (err) {
      const msg = err.response?.data?.message
      if (msg?.includes('not found') || msg?.includes('does not exist')) {
        error.value = 'Bu e-posta adresiyle kayıtlı bir hesap bulunamadı.'
      } else {
        // Güvenlik: Kullanıcı olsun ya da olmasın aynı mesajı göster
        successMessage.value = 'Eğer bu e-posta kayıtlıysa, şifre sıfırlama bağlantısı gönderildi.'
      }
    } finally {
      isLoading.value = false
    }
  }

  // ── Logout ─────────────────────────────
  async function logout() {
    try {
      await frappe.logout()
    } catch { /* sessiz */ }
    user.value = null
    userInfo.value = null
    router.push({ name: 'Login' })
  }

  // ── Fetch Current User ─────────────────
  async function fetchCurrentUser() {
    const res = await frappe.getLoggedUser()
    const currentUser = res.data.message

    if (currentUser && currentUser !== 'Guest') {
      user.value = currentUser
      try {
        const doc = await frappe.getDoc('User', currentUser)
        userInfo.value = doc.data.data
      } catch { /* detay çekilemezse sorun değil */ }
    } else {
      user.value = null
      userInfo.value = null
    }
  }

  // ── Init Auth (uygulama açılışında) ────
  async function initAuth() {
    if (isInitialized.value) return
    isLoading.value = true
    try {
      await fetchCurrentUser()
    } catch {
      user.value = null
      userInfo.value = null
    } finally {
      isInitialized.value = true
      isLoading.value = false
    }
  }

  // ── Session Expiry Handler ─────────────
  function handleSessionExpiry() {
    user.value = null
    userInfo.value = null
    const currentRoute = router.currentRoute.value
    if (currentRoute.name !== 'Login') {
      returnUrl.value = currentRoute.fullPath
      router.push({ name: 'Login', query: { expired: '1' } })
    }
  }

  // ── Clear Messages ─────────────────────
  function clearMessages() {
    error.value = null
    successMessage.value = null
  }

  return {
    user, userInfo, isLoading, isInitialized,
    error, successMessage, returnUrl,
    isAuthenticated, fullName, userImage,
    login, register, forgotPassword, logout,
    initAuth, handleSessionExpiry, clearMessages,
  }
})
