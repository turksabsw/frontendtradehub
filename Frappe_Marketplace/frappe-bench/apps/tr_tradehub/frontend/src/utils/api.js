import axios from 'axios'

const api = axios.create({
  baseURL: '',
  withCredentials: true,
  headers: {
    'Accept': 'application/json',
    'Content-Type': 'application/json',
  },
})

// CSRF token interceptor
api.interceptors.request.use((config) => {
  if (['post', 'put', 'delete', 'patch'].includes(config.method)) {
    const csrfToken = window.csrf_token
    if (csrfToken) {
      config.headers['X-Frappe-CSRF-Token'] = csrfToken
    }
  }
  return config
})

// 401/403 interceptor
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const status = error.response?.status
    if (status === 401 || status === 403) {
      const { useAuthStore } = await import('@/stores/auth')
      const auth = useAuthStore()
      auth.handleSessionExpiry()
    }
    return Promise.reject(error)
  }
)

export const frappe = {
  // Auth
  login(usr, pwd) {
    return api.post('/api/method/login', { usr, pwd })
  },
  logout() {
    return api.get('/api/method/logout')
  },
  getLoggedUser() {
    return api.get('/api/method/frappe.auth.get_logged_user')
  },

  // Şifremi Unuttum — Frappe'nin yerleşik reset_password metodu
  forgotPassword(email) {
    return api.post('/api/method/frappe.core.doctype.user.user.reset_password', {
      user: email
    })
  },

  // Kayıt — Frappe'nin yerleşik sign_up metodu
  register(email, fullName, redirectTo) {
    return api.post('/api/method/frappe.core.doctype.user.user.sign_up', {
      email: email,
      full_name: fullName,
      redirect_to: redirectTo || '/'
    })
  },

  // Genel API
  call(method, params = {}) {
    return api.post(`/api/method/${method}`, params)
  },
  getDoc(doctype, name) {
    return api.get(`/api/resource/${doctype}/${name}`)
  },
  getList(doctype, params = {}) {
    return api.get(`/api/resource/${doctype}`, { params })
  },
  createDoc(doctype, data) {
    return api.post(`/api/resource/${doctype}`, data)
  },
  updateDoc(doctype, name, data) {
    return api.put(`/api/resource/${doctype}/${name}`, data)
  },
  deleteDoc(doctype, name) {
    return api.delete(`/api/resource/${doctype}/${name}`)
  },
}

export default api
