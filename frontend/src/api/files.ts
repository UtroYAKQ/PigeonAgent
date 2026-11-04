import type { FileLink, FileRecord } from '@/types/api'
import { http } from '@/lib/http'

export const filesApi = {
  async upload(
    file: File,
    options: { onProgress?: (percent: number) => void; signal?: AbortSignal } = {},
  ): Promise<FileRecord> {
    const form = new FormData()
    form.append('file', file)
    const { data } = await http.post<FileRecord>('/files', form, {
      signal: options.signal,
      timeout: 120_000,
      onUploadProgress: (event) => {
        if (!event.total) return
        options.onProgress?.(Math.round((event.loaded / event.total) * 100))
      },
    })
    return data
  },

  async content(fileId: string, signal?: AbortSignal): Promise<Blob> {
    const { data } = await http.get<Blob>(`/files/${fileId}/content`, {
      responseType: 'blob',
      signal,
      timeout: 60_000,
    })
    return data
  },

  /** 短时效对象存储直链：给 <img>/<video> 用，浏览器直接取字节，不再经过应用转发。 */
  async link(fileId: string, signal?: AbortSignal): Promise<FileLink> {
    const { data } = await http.get<FileLink>(`/files/${fileId}/link`, { signal, timeout: 10_000 })
    return data
  },

  async remove(fileId: string): Promise<void> {
    await http.delete(`/files/${fileId}`)
  },
}
