import { adminApi } from '@/api/admin'
import { filesApi } from '@/api/files'

export function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = name
  anchor.rel = 'noopener'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export async function downloadFile(fileId: string, name: string, admin = false): Promise<void> {
  const blob = admin ? await adminApi.fileContent(fileId) : await filesApi.content(fileId)
  saveBlob(blob, name)
}