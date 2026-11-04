import { createRouter, createWebHistory } from 'vue-router'

import { ERROR_CODES } from '@/lib/errorPages'
import { useAuthStore } from '@/stores/auth'

/**
 * 后台页从 /settings 搬进了 /admin，旧地址一律保留跳转，免得书签和分享出去的链接失效。
 * 值是 /admin 下的目标段名，空串表示直接落 /admin 概览页。
 */
const LEGACY_ADMIN_SECTIONS: Record<string, string> = {
  site: 'site',
  models: 'models',
  deepseek: 'deepseek',
  sandbox: 'sandbox',
  email: 'email',
  files: 'files',
  logging: 'logging',
  'platform-overview': '',
  'platform-users': 'users',
  'platform-sessions': 'sessions',
  'platform-logs': 'logs',
}

const legacyAdminRoutes = Object.entries(LEGACY_ADMIN_SECTIONS).map(([section, target]) => ({
  path: `/settings/${section}`,
  redirect: target ? `/admin/${target}` : '/admin',
}))

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('@/views/AuthView.vue'),
      meta: { guestOnly: true },
    },
    {
      path: '/register',
      name: 'register',
      component: () => import('@/views/AuthView.vue'),
      meta: { guestOnly: true, register: true },
    },
    {
      path: '/',
      redirect: '/chat',
    },
    {
      path: '/chat',
      name: 'new-chat',
      component: () => import('@/views/ChatView.vue'),
    },
    {
      path: '/c/:id',
      name: 'chat',
      component: () => import('@/views/ChatView.vue'),
    },
    {
      // 只读分享页：登录态不是访问前提，链接里的口令就是凭证
      path: '/s/:token',
      name: 'shared-conversation',
      component: () => import('@/views/ShareView.vue'),
      meta: { public: true },
    },
    ...legacyAdminRoutes,
    {
      path: '/settings/:section?',
      name: 'settings',
      component: () => import('@/views/SettingsView.vue'),
    },
    {
      path: '/admin/:section?',
      name: 'admin',
      component: () => import('@/views/AdminView.vue'),
      meta: { requiresAdmin: true },
    },
    ...ERROR_CODES.map(code => ({
      path: `/${code}`,
      name: `error-${code}`,
      component: () => import('@/views/ErrorView.vue'),
      props: { code },
      meta: { public: true },
    })),
    {
      path: '/:pathMatch(.*)*',
      name: 'not-found',
      component: () => import('@/views/ErrorView.vue'),
      props: { code: '404' },
      meta: { public: true },
    },
  ],
})

router.beforeEach(async (to) => {
  if (to.meta.public) return true

  const auth = useAuthStore()
  if (!auth.initialized) {
    await auth.init()
  }

  if (to.meta.guestOnly) {
    // 已登录就不停在登录/注册页；一律回 /chat，不沿用 query 里的旧路径
    return auth.isAuthenticated ? '/chat' : true
  }

  if (!auth.isAuthenticated) {
    return { name: 'login' }
  }

  if (to.meta.requiresAdmin && !auth.user?.is_admin) {
    return { path: '/403' }
  }
  return true
})

export default router
