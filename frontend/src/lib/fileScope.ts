import type { InjectionKey } from 'vue'

export interface FilePreviewTarget {
  fileId: string
  name: string
  mediaType?: string | null
  size?: number | null
}

export interface FileScope {
  admin: boolean
  preview?: (target: FilePreviewTarget) => void
}

export const FILE_SCOPE_KEY: InjectionKey<FileScope> = Symbol('file-scope')
