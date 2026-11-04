import { computed, ref, shallowRef } from 'vue'

import { errorMessage } from '@/lib/http'

/** 后端分页列表的共同形状 */
export interface PagedResult<T> {
  items: T[]
  total: number
}

export interface PagedTableOptions<T> {
  /**
   * 取一页数据。分页参数由这里给；筛选条件由调用方在自己的闭包里读，
   * 于是筛选项变化只要重新 load(true)，不必把筛选逻辑搬进 composable。
   */
  fetchPage: (params: { limit: number; offset: number }) => Promise<PagedResult<T>>
  limit: number
}

/**
 * 管理台分页表格的公共样板：取数、加载中、错误、翻页、当前区间。
 * 只收敛这几件重复的事——搜索防抖、筛选联动、首屏加载时机仍由面板决定。
 */
export function usePagedTable<T>(options: PagedTableOptions<T>) {
  const { fetchPage, limit } = options

  // 面板总是整页替换数据，不做行内修改，所以列表用 shallowRef
  const items = shallowRef<T[]>([])
  const total = ref(0)
  // 初始为 true：挂载到首个响应之间显示骨架，而不是先闪一下空状态
  const loading = ref(true)
  const error = ref<string | null>(null)
  const offset = ref(0)
  const loaded = ref(false)

  const rangeLabel = computed(() =>
    total.value ? `${offset.value + 1}–${Math.min(offset.value + limit, total.value)}` : '0',
  )

  async function load(reset = false): Promise<void> {
    if (reset) offset.value = 0
    loading.value = true
    error.value = null
    try {
      const data = await fetchPage({ limit, offset: offset.value })
      items.value = data.items
      total.value = data.total
      loaded.value = true
      // 删完最后一页会停在一张空表上：退一页，而不是让用户以为没有数据
      if (!data.items.length && offset.value > 0) {
        offset.value = Math.max(0, offset.value - limit)
        await load()
      }
    } catch (caught) {
      error.value = errorMessage(caught)
    } finally {
      loading.value = false
    }
  }

  function page(direction: -1 | 1): void {
    offset.value = Math.max(0, offset.value + direction * limit)
    void load()
  }

  return { items, total, loading, error, loaded, offset, limit, rangeLabel, load, page }
}
