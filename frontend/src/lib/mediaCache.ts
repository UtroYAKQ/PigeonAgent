import { filesApi } from '@/api/files'

/**
 * 历史会话里的图片按内容持久缓存。
 *
 * 直链每次签名都会变，浏览器缓存命中不了；生产又是 http 环境，CacheStorage
 * 不可用，所以用 IndexedDB 按 file_id 存 Blob。文件记录指向的字节不可变，
 * file_id 可以直接当缓存键。读取失败一律回落到网络，不影响图片展示。
 */
const DB_NAME = 'pigeon-media'
const DB_VERSION = 1
const STORE = 'images'
const MEMORY_LIMIT = 16
const MAX_ENTRIES = 80
const MAX_IMAGE_BYTES = 12 * 1024 * 1024

interface StoredImage {
  fileId: string
  blob: Blob
  savedAt: number
}

const memory = new Map<string, Promise<Blob>>()
let databasePromise: Promise<IDBDatabase | null> | null = null

function openDatabase(): Promise<IDBDatabase | null> {
  if (databasePromise) return databasePromise
  databasePromise = new Promise((resolve) => {
    if (typeof indexedDB === 'undefined') {
      resolve(null)
      return
    }
    const request = indexedDB.open(DB_NAME, DB_VERSION)
    request.onupgradeneeded = () => {
      const db = request.result
      if (db.objectStoreNames.contains(STORE)) return
      const store = db.createObjectStore(STORE, { keyPath: 'fileId' })
      store.createIndex('savedAt', 'savedAt')
    }
    request.onsuccess = () => resolve(request.result)
    request.onerror = () => {
      console.warn('图片缓存不可用，后续直接走网络', request.error)
      resolve(null)
    }
    request.onblocked = () => resolve(null)
  })
  return databasePromise
}

function readStored(db: IDBDatabase, fileId: string): Promise<Blob | null> {
  return new Promise((resolve) => {
    const transaction = db.transaction(STORE, 'readonly')
    const request = transaction.objectStore(STORE).get(fileId)
    request.onsuccess = () => {
      const row = request.result as StoredImage | undefined
      resolve(row?.blob instanceof Blob ? row.blob : null)
    }
    request.onerror = () => resolve(null)
  })
}

function transactionDone(transaction: IDBTransaction): Promise<void> {
  return new Promise((resolve) => {
    transaction.oncomplete = () => resolve()
    transaction.onerror = () => resolve()
    transaction.onabort = () => resolve()
  })
}

async function trim(db: IDBDatabase): Promise<void> {
  const transaction = db.transaction(STORE, 'readwrite')
  const store = transaction.objectStore(STORE)
  const countRequest = store.count()
  countRequest.onsuccess = () => {
    const overflow = countRequest.result - MAX_ENTRIES
    if (overflow <= 0) return
    let remaining = overflow
    const cursorRequest = store.index('savedAt').openCursor()
    cursorRequest.onsuccess = () => {
      const cursor = cursorRequest.result
      if (!cursor || remaining <= 0) return
      cursor.delete()
      remaining -= 1
      cursor.continue()
    }
  }
  await transactionDone(transaction)
}

async function writeStored(fileId: string, blob: Blob): Promise<void> {
  if (blob.size === 0 || blob.size > MAX_IMAGE_BYTES) return
  const db = await openDatabase()
  if (!db) return
  const transaction = db.transaction(STORE, 'readwrite')
  const row: StoredImage = { fileId, blob, savedAt: Date.now() }
  try {
    transaction.objectStore(STORE).put(row)
  } catch (error) {
    // 配额不足或浏览器禁用了持久化：缓存只是优化，写不进去不影响本次展示
    console.warn('写入图片缓存失败', error)
    return
  }
  await transactionDone(transaction)
  void trim(db)
}

function remember(fileId: string, task: Promise<Blob>): Promise<Blob> {
  memory.set(fileId, task)
  while (memory.size > MEMORY_LIMIT) {
    const oldest = memory.keys().next().value
    if (oldest === undefined) break
    memory.delete(oldest)
  }
  return task
}

export function loadCachedImage(fileId: string): Promise<Blob> {
  const pending = memory.get(fileId)
  if (pending) return pending

  const task = (async () => {
    const db = await openDatabase()
    const cached = db ? await readStored(db, fileId) : null
    if (cached) return cached
    const blob = await filesApi.content(fileId)
    void writeStored(fileId, blob)
    return blob
  })()
  task.catch(() => memory.delete(fileId))
  return remember(fileId, task)
}
