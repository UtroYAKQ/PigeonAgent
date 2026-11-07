/* file 领域类型。 */

import type { UUID } from './common'

export interface FileRecord {
  id: UUID
  name: string
  size: number
  content_type: string | null
  sha256: string
}

/** 短时效对象存储媒体直链。 */
export interface FileLink {
  url: string
  expires_at: string
}

export type AttachmentKind = 'image' | 'video' | 'resource'

export interface DraftAttachment {
  localId: string
  file: File
  kind: AttachmentKind
  previewUrl: string | null
  status: 'uploading' | 'ready' | 'error'
  record: FileRecord | null
  error: string | null
  progress: number
}
