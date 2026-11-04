import type { TokenPair } from '@/types/api'

const ACCESS_KEY = 'pigeon.access_token'
const REFRESH_KEY = 'pigeon.refresh_token'

export interface StoredTokens {
  access: string
  refresh: string
}

export function readTokens(): StoredTokens | null {
  const access = localStorage.getItem(ACCESS_KEY)
  const refresh = localStorage.getItem(REFRESH_KEY)
  if (!access || !refresh) return null
  return { access, refresh }
}

export function writeTokens(pair: TokenPair): void {
  localStorage.setItem(ACCESS_KEY, pair.access_token)
  localStorage.setItem(REFRESH_KEY, pair.refresh_token)
}

export function clearTokens(): void {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

export function accessToken(): string | null {
  return localStorage.getItem(ACCESS_KEY)
}
