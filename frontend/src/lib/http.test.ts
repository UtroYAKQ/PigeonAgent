import axios, { AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { TokenPair } from '@/types/api'
import { accessToken, clearTokens, readTokens, writeTokens } from './authStorage'

interface Reply {
  status: number
  data?: unknown
}

interface Call {
  url: string
  authorization: string
  attempt: number
}

const issued: Call[] = []
let replyFor = (_call: Call): Reply => ({ status: 200, data: {} })

axios.defaults.adapter = async (config: InternalAxiosRequestConfig): Promise<AxiosResponse> => {
  const url = String(config.url ?? '')
  const call: Call = {
    url,
    authorization: String((config.headers as Record<string, unknown>).Authorization ?? ''),
    attempt: issued.filter(item => item.url === url).length + 1,
  }
  issued.push(call)

  const { status, data } = replyFor(call)
  const response = { data: data ?? {}, status, statusText: '', headers: {}, config } as AxiosResponse
  if (status >= 400) {
    throw new AxiosError(`HTTP ${status}`, AxiosError.ERR_BAD_REQUEST, config, null, response)
  }
  return response
}

// http.ts 的两个实例都在模块加载时固化 adapter，所以必须等上面装好再 import
const { ApiError, errorMessage, http, refreshAccessToken } = await import('./http')

const tokens: TokenPair = {
  access_token: 'access-1',
  refresh_token: 'refresh-1',
  token_type: 'bearer',
  expires_in: 3600,
}

const authExpired = vi.fn()

const urlsOf = () => issued.map(call => call.url)
const refreshReplies = (access: string): Reply => ({
  status: 200,
  data: { ...tokens, access_token: access },
})

beforeEach(() => {
  issued.length = 0
  replyFor = () => ({ status: 200, data: {} })
  authExpired.mockClear()
  clearTokens()
  writeTokens(tokens)
  window.addEventListener('pigeon:auth-expired', authExpired)
})

afterEach(() => {
  window.removeEventListener('pigeon:auth-expired', authExpired)
})

describe('http 的 401 处理', () => {
  it('401 后刷新一次，再带新 token 重试原请求', async () => {
    replyFor = call => {
      if (call.url === '/auth/refresh') return refreshReplies('access-2')
      if (call.attempt === 1) return { status: 401 }
      return { status: 200, data: { items: [], total: 0 } }
    }

    const response = await http.get('/sessions')

    expect(response.data).toEqual({ items: [], total: 0 })
    expect(urlsOf()).toEqual(['/sessions', '/auth/refresh', '/sessions'])
    expect(issued[2]?.authorization).toBe('Bearer access-2')
    expect(accessToken()).toBe('access-2')
    expect(readTokens()?.refresh).toBe('refresh-1')
    expect(authExpired).not.toHaveBeenCalled()
  })

  it('并发的 401 共用同一次刷新', async () => {
    replyFor = call => {
      if (call.url === '/auth/refresh') return refreshReplies('access-2')
      if (call.attempt === 1) return { status: 401 }
      return { status: 200, data: { ok: true } }
    }

    const [sessions, runs] = await Promise.all([http.get('/sessions'), http.get('/runs')])

    expect(sessions.data).toEqual({ ok: true })
    expect(runs.data).toEqual({ ok: true })
    expect(urlsOf().filter(url => url === '/auth/refresh')).toHaveLength(1)
  })

  it('刷新失败时只广播一次 pigeon:auth-expired', async () => {
    replyFor = call => call.url === '/auth/refresh'
      ? { status: 401, data: { detail: 'refresh 已过期' } }
      : { status: 401, data: { detail: '未登录' } }

    await expect(http.get('/sessions')).rejects.toThrow('HTTP 401')

    // 原请求 + 刷新各只走一趟；广播不能跟着翻倍
    expect(urlsOf()).toEqual(['/sessions', '/auth/refresh'])
    expect(authExpired).toHaveBeenCalledTimes(1)
    expect(accessToken()).toBeNull()
  })

  it('刷新成功但重试仍然 401 时，也只广播一次且不再刷新', async () => {
    replyFor = call => call.url === '/auth/refresh'
      ? refreshReplies('access-2')
      : { status: 401 }

    await expect(http.get('/sessions')).rejects.toThrow('HTTP 401')

    expect(urlsOf()).toEqual(['/sessions', '/auth/refresh', '/sessions'])
    expect(authExpired).toHaveBeenCalledTimes(1)
  })

  it('登录接口自己的 401 原样抛回，不刷新也不广播', async () => {
    replyFor = () => ({ status: 401, data: { detail: '邮箱或密码不正确' } })

    await expect(http.post('/auth/login', { email: 'a@b.c', password: 'x' })).rejects.toThrow('HTTP 401')

    expect(urlsOf()).toEqual(['/auth/login'])
    expect(authExpired).not.toHaveBeenCalled()
    expect(accessToken()).toBe('access-1')
  })

  it('非 401 的错误原样抛回', async () => {
    replyFor = () => ({ status: 500, data: { detail: '服务器内部错误' } })

    await expect(http.get('/sessions')).rejects.toThrow('HTTP 500')

    expect(urlsOf()).toEqual(['/sessions'])
    expect(authExpired).not.toHaveBeenCalled()
  })
})

describe('refreshAccessToken', () => {
  it('本地没有 token 时直接抛 ApiError，不去请求也不广播', async () => {
    clearTokens()

    await expect(refreshAccessToken()).rejects.toBeInstanceOf(ApiError)

    expect(urlsOf()).toEqual([])
    expect(authExpired).not.toHaveBeenCalled()
  })
})

describe('errorMessage', () => {
  function httpError(status: number, detail: unknown): AxiosError {
    const response = { data: { detail }, status, statusText: '', headers: {} }
    return new AxiosError(
      `HTTP ${status}`,
      AxiosError.ERR_BAD_REQUEST,
      undefined,
      undefined,
      response as unknown as AxiosResponse,
    )
  }

  it('取 FastAPI 的 detail 字符串', () => {
    expect(errorMessage(httpError(422, '邮箱格式不对'))).toBe('邮箱格式不对')
  })

  it('校验错误数组取第一条 msg', () => {
    expect(errorMessage(httpError(422, [{ msg: 'Field required' }, { msg: '另一条' }]))).toBe('Field required')
  })

  it('ApiError 保留自己的文案', () => {
    expect(errorMessage(new ApiError('登录已过期，请重新登录', 401))).toBe('登录已过期，请重新登录')
  })

  it('不是 Error 的东西落到固定文案', () => {
    expect(errorMessage('只是一段字符串')).toBe('发生未知错误')
  })
})
