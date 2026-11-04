import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { authApi } from '@/api/auth'
import { clearTokens, readTokens, writeTokens } from '@/lib/authStorage'
import { toApiError } from '@/lib/http'
import type { RegisterResult, TokenPair, User, UserPreferences } from '@/types/api'

type AuthStatus = 'idle' | 'loading' | 'authenticated' | 'guest'

export const useAuthStore = defineStore('auth', () => {
  const user = ref<User | null>(null)
  const status = ref<AuthStatus>('idle')
  const initialized = ref(false)
  const pendingEmail = ref('')
  let preferenceQueue: Promise<unknown> = Promise.resolve()
  let preferenceVersion = 0

  const isAuthenticated = computed(() => status.value === 'authenticated' && Boolean(user.value))
  const displayName = computed(() => user.value?.display_name || user.value?.email.split('@')[0] || '我')

  async function completeLogin(tokens: TokenPair): Promise<User> {
    writeTokens(tokens)
    const me = await authApi.me()
    user.value = me
    status.value = 'authenticated'
    return me
  }

  async function init(): Promise<void> {
    if (initialized.value) return
    const tokens = readTokens()
    if (!tokens) {
      status.value = 'guest'
      initialized.value = true
      return
    }
    status.value = 'loading'
    try {
      user.value = await authApi.me()
      status.value = 'authenticated'
      initialized.value = true
    } catch (caught) {
      user.value = null
      status.value = 'guest'
      const statusCode = toApiError(caught).status
      if (statusCode === 401 || statusCode === 403) {
        // token 确实作废了：清掉并认下这个结果，别再让守卫反复重试
        clearTokens()
        initialized.value = true
      }
      // 其它失败（断网、服务正在重启）保留 token 也不置 initialized：
      // 下一次路由导航会自动再试，用户不至于被一次抖动踢回登录页
    }
  }

  async function login(email: string, password: string): Promise<void> {
    status.value = 'loading'
    try {
      const tokens = await authApi.login(email.trim(), password)
      await completeLogin(tokens)
    } catch (err) {
      status.value = 'guest'
      throw err
    }
  }

  async function register(email: string, password: string, displayName?: string): Promise<RegisterResult> {
    const result = await authApi.register(email.trim(), password, displayName)
    if (result.verification_required) {
      pendingEmail.value = email.trim()
    } else if (result.tokens) {
      await completeLogin(result.tokens)
    }
    return result
  }

  function setPendingEmail(email: string): void {
    pendingEmail.value = email.trim()
  }

  async function verify(code: string): Promise<void> {
    const tokens = await authApi.verify(pendingEmail.value, code)
    await completeLogin(tokens)
    pendingEmail.value = ''
  }

  async function resend(): Promise<void> {
    await authApi.resend(pendingEmail.value)
  }

  async function updateProfile(patch: {
    display_name?: string | null
    avatar_file_id?: string | null
  }): Promise<User> {
    const updated = await authApi.updateProfile(patch)
    user.value = updated
    return updated
  }

  function updatePreferences(patch: Partial<UserPreferences>): Promise<User> {
    const current = user.value
    if (!current) return Promise.reject(new Error('未登录'))

    user.value = {
      ...current,
      preferences: { ...current.preferences, ...patch },
    }

    const version = ++preferenceVersion
    const request = preferenceQueue.then(() => authApi.updatePreferences(patch))
    preferenceQueue = request.then(() => undefined, () => undefined)
    return request.then(updated => {
      if (version === preferenceVersion && user.value?.id === updated.id) {
        user.value = { ...user.value, preferences: updated.preferences }
      }
      return updated
    })
  }

  async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
    const tokens = await authApi.changePassword(currentPassword, newPassword)
    writeTokens(tokens)
  }

  function logout(): void {
    clearTokens()
    user.value = null
    status.value = 'guest'
  }

  async function signOutEverywhere(): Promise<void> {
    // 先让服务端作废已签发的令牌，再清本地：这台设备也会一起掉线
    await authApi.signOutEverywhere()
    logout()
  }

  window.addEventListener('pigeon:auth-expired', logout)

  return {
    user,
    status,
    initialized,
    pendingEmail,
    isAuthenticated,
    displayName,
    init,
    login,
    register,
    setPendingEmail,
    verify,
    resend,
    updateProfile,
    updatePreferences,
    changePassword,
    logout,
    signOutEverywhere,
  }
})
