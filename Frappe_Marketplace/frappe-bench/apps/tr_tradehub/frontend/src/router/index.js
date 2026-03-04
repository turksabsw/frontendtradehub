import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

// Layout — YENİ KONUM
import AppLayout from '@/layouts/AppLayout.vue'

// Views (lazy-loaded) — YENİ KONUMLAR
const LoginView = () => import('@/views/auth/LoginView.vue')
const DashboardView = () => import('@/views/dashboard/DashboardView.vue')
const ProductAddView = () => import('@/views/products/ProductAddView.vue')
const DocTypeListView = () => import('@/views/doctype/DocTypeListView.vue')

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: LoginView,
    meta: { guest: true },
  },
  {
    path: '/',
    component: AppLayout,
    meta: { requiresAuth: true },
    children: [
      { path: '', redirect: '/dashboard' },
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
      {
        path: 'app/:doctype',
        name: 'DocTypeList',
        component: DocTypeListView,
        meta: { title: 'Liste', breadcrumb: 'Liste' },
      },
      {
        path: 'app/:doctype/:name',
        name: 'DocTypeForm',
        component: () => import('@/views/doctype/DocTypeFormView.vue'),
        meta: { title: 'Detay', breadcrumb: 'Detay' },
      },
      {
        path: 'app/report/:report',
        name: 'ReportView',
        component: DocTypeListView,
        meta: { title: 'Rapor', breadcrumb: 'Rapor' },
      },
      {
        path: 'messaging/:tab?',
        name: 'Messaging',
        component: DashboardView,
        meta: { title: 'Mesajlar', breadcrumb: 'Mesajlar' },
      },
    ],
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/login',
  },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach(async (to, from, next) => {
  const auth = useAuthStore()
  if (!auth.isAuthenticated && !to.meta.guest) {
    try { await auth.fetchUser() } catch { }
  }
  if (!to.meta.guest && !auth.isAuthenticated) {
    return next({ path: '/login', query: { redirect: to.fullPath } })
  }
  if (to.meta.guest && auth.isAuthenticated) {
    return next('/dashboard')
  }
  next()
})

export default router
