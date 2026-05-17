import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'explorer',
      component: () => import('../views/ExplorerView.vue'),
    },
    {
      path: '/node/:peerId',
      name: 'node-detail',
      component: () => import('../views/NodeDetailView.vue'),
      props: true,
    },
    {
      path: '/node/:peerId/history',
      name: 'node-history',
      component: () => import('../views/NodeHistoryView.vue'),
      props: true,
    },
    {
      path: '/epochs',
      name: 'epochs',
      component: () => import('../views/EpochTimelineView.vue'),
    },
    {
      path: '/epochs/:epoch',
      name: 'epoch-detail',
      component: () => import('../views/EpochTimelineView.vue'),
      props: true,
    },
    {
      path: '/audit-log',
      name: 'audit-log',
      component: () => import('../views/AuditLogView.vue'),
    },
    {
      path: '/admin',
      name: 'admin',
      component: () => import('../views/AdminView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/LoginView.vue'),
    },
  ],
})

router.beforeEach((to, _from, next) => {
  if (to.meta.requiresAuth) {
    const auth = useAuthStore()
    if (!auth.isAuthenticated) {
      next({ name: 'login' })
      return
    }
  }
  next()
})

export default router
