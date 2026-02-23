import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

// Layout
import AppLayout from '@/components/layout/AppLayout.vue'

// Views (lazy-loaded)
const LoginView = () => import('@/views/auth/LoginView.vue')
const DashboardView = () => import('@/views/DashboardView.vue')
const ProductAddView = () => import('@/views/ProductAddView.vue')
const DocTypeListView = () => import('@/views/DocTypeListView.vue')

const routes = [
  // Auth (no layout)
  {
    path: '/login',
    name: 'Login',
    component: LoginView,
    meta: { guest: true },
  },

  // App routes (with layout)
  {
    path: '/',
    component: AppLayout,
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        redirect: '/dashboard',
      },
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: DashboardView,
        meta: { title: 'Genel Bakış', breadcrumb: 'Genel Bakış' },
      },
      {
        path: 'app/product-add',
        name: 'ProductAdd',
        component: ProductAddView,
        meta: { title: 'Yeni Ürün Ekle', breadcrumb: 'Yeni Ürün Ekle' },
      },
      // Generic DocType List
      {
        path: 'app/:doctype',
        name: 'DocTypeList',
        component: DocTypeListView,
        meta: { title: 'Liste', breadcrumb: 'Liste' },
      },
      // Generic DocType Form (detail view)
      {
        path: 'app/:doctype/:name',
        name: 'DocTypeForm',
        component: () => import('@/views/DocTypeFormView.vue'),
        meta: { title: 'Detay', breadcrumb: 'Detay' },
      },
      // Report views
      {
        path: 'app/report/:report',
        name: 'ReportView',
        component: DocTypeListView, // Reuse list view for now
        meta: { title: 'Rapor', breadcrumb: 'Rapor' },
      },
      // Messaging
      {
        path: 'messaging/:tab?',
        name: 'Messaging',
        component: DashboardView, // Placeholder
        meta: { title: 'Mesajlar', breadcrumb: 'Mesajlar' },
      },
    ],
  },

  // Catch-all
  {
    path: '/:pathMatch(.*)*',
    redirect: '/login',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// Navigation guard - Headless modda daima auth zorunlu
router.beforeEach(async (to, from, next) => {
  const auth = useAuthStore()

  // Try to fetch user if not loaded yet
  if (!auth.isAuthenticated && !to.meta.guest) {
    try {
      await auth.fetchUser()
    } catch {
      // Not logged in - ignore
    }
  }

  // Redirect to login if not authenticated (applies in both DEV and PROD)
  if (!to.meta.guest && !auth.isAuthenticated) {
    return next({ path: '/login', query: { redirect: to.fullPath } })
  }

  // Redirect away from login if already authenticated
  if (to.meta.guest && auth.isAuthenticated) {
    return next('/dashboard')
  }

  next()
})

export default router
