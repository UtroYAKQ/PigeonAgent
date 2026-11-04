import axios, { AxiosError, type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'

import type { TokenPair } from '@/types/api'
import { accessToken, clearTokens, readTokens, writeTokens } from './authStorage'

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || '/api/v1').replace(/\/$/, '')

export class ApiError extends Error {
  status: number
  payload: unknown

  constructor(message: string, status: number, payload?: unknown) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.payload = payload
  }
}

/** 两个实例共用同一份配置：rawHttp 只少了拦截器，用于刷新时不再触发刷新。 */
const clientConfig = {
  baseURL: API_BASE_URL,
  timeout: 30_000,
}

const rawHttp = axios.create(clientConfig)

export const http: AxiosInstance = axios.create(clientConfig)

let refreshPromise: Promise<string> | null = null

function expireSession(): void {
  clearTokens()
  window.dispatchEvent(new CustomEvent('pigeon:auth-expired'))
}

async function exchangeRefreshToken(): Promise<string> {
  const tokens = readTokens()
  if (!tokens) throw new ApiError('登录已过期，请重新登录', 401)

  try {
    const { data } = await rawHttp.post<TokenPair>('/auth/refresh', {
      refresh_token: tokens.refresh,
    })
    writeTokens(data)
    return data.access_token
  } catch (error) {
    expireSession()
    throw error
  }
}

export function refreshAccessToken(): Promise<string> {
  if (!refreshPromise) {
    refreshPromise = exchangeRefreshToken().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = accessToken()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

http.interceptors.response.use(
  response => response,
  async (error: AxiosError) => {
    const config = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined
    const isAuthCall = /\/auth\/(login|register|verify|refresh|resend)/.test(config?.url ?? '')

    // 登录页自己的 401（密码错）不归这里管，原样抛回去让表单显示
    if (error.response?.status !== 401 || isAuthCall) return Promise.reject(error)

    // expireSession 是 pigeon:auth-expired 的唯一出口：refresh 失败时它已经在
    // exchangeRefreshToken 里派发过，这里再派发一次会把 auth 的监听器打两遍。
    if (!config || config._retried) {
      expireSession()
      return Promise.reject(error)
    }

    config._retried = true
    try {
      const token = await refreshAccessToken()
      config.headers.Authorization = `Bearer ${token}`
      return await http(config)
    } catch {
      return Promise.reject(error)
    }
  },
)

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message
  if (error instanceof AxiosError) {
    const data = error.response?.data as { detail?: unknown } | undefined
    if (typeof data?.detail === 'string') return data.detail
    if (Array.isArray(data?.detail)) {
      const first = data.detail[0] as { msg?: string } | undefined
      if (first?.msg) return first.msg
    }
    if (error.code === 'ECONNABORTED') return '请求超时，请稍后重试'
    if (!error.response) return '网络连接失败，请检查后端服务'
    return error.message
  }
  if (error instanceof Error) return error.message
  return '发生未知错误'
}

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error
  if (error instanceof AxiosError) {
    return new ApiError(errorMessage(error), error.response?.status ?? 0, error.response?.data)
  }
  return new ApiError(errorMessage(error), 0)
}
