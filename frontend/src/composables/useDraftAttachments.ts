/** 输入框草稿附件的生命周期：排队上传、配额判定、预览地址回收、发送后清空。 */

import { computed, ref } from 'vue'
import { toast } from 'vue-sonner'

import { filesApi } from '@/api/files'
import { errorMessage } from '@/lib/http'
import { formatBytes } from '@/lib/format'
import { randomUuid } from '@/lib/ids'
import { useChatStore } from '@/stores/chat'
import type { AttachmentKind, DraftAttachment } from '@/types/api'

function kindOf(file: File): AttachmentKind {
  if (file.type.startsWith('image/')) return 'image'
  if (file.type.startsWith('video/')) return 'video'
  return 'resource'
}

export function useDraftAttachments() {
  const chat = useChatStore()
  const attachments = ref<DraftAttachment[]>([])
  const uploadControllers = new Map<string, AbortController>()

  const uploading = computed(() => attachments.value.some(item => item.status === 'uploading'))
  const hasReady = computed(() => attachments.value.some(item => item.status === 'ready'))

  /** 图片/视频与文档分开配额；返回 null 表示还能加，否则是给用户看的拒收原因。 */
  function quotaRejection(kind: AttachmentKind): string | null {
    if (kind === 'resource') {
      const documents = attachments.value.filter(item => item.kind === 'resource').length
      return documents >= chat.maxResourceFiles ? `最多添加 ${chat.maxResourceFiles} 个文件` : null
    }
    const media = attachments.value.filter(item => item.kind !== 'resource').length
    return media >= chat.maxImageAttachments
      ? `最多添加 ${chat.maxImageAttachments} 个图片或视频`
      : null
  }

  async function uploadOne(file: File): Promise<void> {
    const limit = chat.maxUploadBytes
    if (file.size > limit) {
      toast.error(`${file.name} 超过 ${formatBytes(limit)} 上限`)
      return
    }

    const kind = kindOf(file)
    if (kind === 'resource' && chat.currentModel?.supports_tools === false) {
      toast.error('当前模型未开启工具调用支持，无法使用文件工作区')
      return
    }
    const rejected = quotaRejection(kind)
    if (rejected) {
      toast.error(rejected)
      return
    }

    const localId = randomUuid()
    const draft: DraftAttachment = {
      localId,
      file,
      kind,
      previewUrl: kind === 'resource' ? null : URL.createObjectURL(file),
      status: 'uploading',
      record: null,
      error: null,
      progress: 0,
    }
    const controller = new AbortController()
    uploadControllers.set(localId, controller)
    attachments.value = [...attachments.value, draft]

    const patch = (change: Partial<DraftAttachment>): void => {
      const target = attachments.value.find(item => item.localId === localId)
      if (target) Object.assign(target, change)
    }

    try {
      const record = await filesApi.upload(file, {
        signal: controller.signal,
        onProgress: progress => patch({ progress }),
      })
      patch({ record, status: 'ready', progress: 100 })
    } catch (error) {
      // 用户点了移除会 abort，那种情况条目已经不在了，不必再报错
      if (controller.signal.aborted) return
      patch({ status: 'error', error: errorMessage(error) })
      toast.error(`上传 ${file.name} 失败`, { description: errorMessage(error) })
    } finally {
      uploadControllers.delete(localId)
    }
  }

  async function addFiles(files: File[]): Promise<void> {
    if (chat.busy || chat.editingRun) return
    // 配额按文件类型逐个判定：一次选中很多文件时，能收下的先收下，
    // 剩下的各自拿到"哪一类满了"的准确提示
    for (const file of files) void uploadOne(file)
  }

  function removeAttachment(localId: string): void {
    const target = attachments.value.find(item => item.localId === localId)
    if (!target) return
    uploadControllers.get(localId)?.abort()
    uploadControllers.delete(localId)
    if (target.previewUrl) URL.revokeObjectURL(target.previewUrl)
    if (target.record) {
      // 已经传上去的文件要软删，不然它一直挂在"我的文件"里；删失败不影响本次输入
      void filesApi.remove(target.record.id).catch(error => {
        console.warn(`删除已上传文件 ${target.record?.id} 失败`, error)
      })
    }
    attachments.value = attachments.value.filter(item => item.localId !== localId)
  }

  function clearAttachments(): void {
    for (const controller of uploadControllers.values()) controller.abort()
    uploadControllers.clear()
    for (const item of attachments.value) {
      if (item.previewUrl) URL.revokeObjectURL(item.previewUrl)
    }
    attachments.value = []
  }

  /** 发送时取一份快照；清空由调用方在确认发送成功后做。 */
  function takeAttachments(): DraftAttachment[] {
    return [...attachments.value]
  }

  return {
    attachments,
    uploading,
    hasReady,
    addFiles,
    removeAttachment,
    clearAttachments,
    takeAttachments,
  }
}
