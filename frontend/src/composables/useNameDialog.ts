/** 「输入名字 → 提交」对话框的状态：侧栏里会话改名、分组新建与改名共用这一套。 */

import { nextTick, ref } from 'vue'
import type { Ref } from 'vue'
import { toast } from 'vue-sonner'

import { errorMessage } from '@/lib/http'

export interface NameDialog<T> {
  open: Ref<boolean>
  value: Ref<string>
  target: Ref<T | null>
  show: (target: T | null, initial: string) => Promise<void>
  confirm: () => Promise<void>
}

/**
 * input 由调用方持有并绑到对话框的输入框上（模板里的 ref 要留在 setup 顶层），
 * 这里只负责打开时聚焦并选中现有名字。submit 抛错时对话框保持打开，
 * 错误文案由 failure 给出、真实原因进描述。
 */
export function useNameDialog<T>(
  failure: string,
  input: Ref<HTMLInputElement | null>,
  submit: (target: T | null, name: string) => Promise<void>,
): NameDialog<T> {
  const open = ref(false)
  const value = ref('')
  const target = ref<T | null>(null) as Ref<T | null>

  async function show(next: T | null, initial: string): Promise<void> {
    target.value = next
    value.value = initial
    open.value = true
    await nextTick()
    input.value?.focus()
    input.value?.select()
  }

  async function confirm(): Promise<void> {
    const name = value.value.trim()
    if (!name) return
    try {
      await submit(target.value, name)
      open.value = false
    } catch (error) {
      toast.error(failure, { description: errorMessage(error) })
    }
  }

  return { open, value, target, show, confirm }
}
