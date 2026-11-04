<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import {
  Coins,
  Folder,
  FolderOpen,
  FolderPlus,
  LayoutDashboard,
  LogOut,
  MoreHorizontal,
  Search,
  Settings,
  SquarePen,
  UserRound,
  X,
} from '@lucide/vue'

import BrandMark from '@/components/brand/BrandMark.vue'
import UserAvatar from '@/components/user/UserAvatar.vue'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { TooltipHint } from '@/components/ui/tooltip'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { errorMessage } from '@/lib/http'
import { formatCredits } from '@/lib/format'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import { useUiStore } from '@/stores/ui'
import { useNameDialog } from '@/composables/useNameDialog'
import type { ChatSession, SessionGroup } from '@/types/api'
import SessionRow from './SessionRow.vue'

withDefaults(defineProps<{ mobile?: boolean }>(), { mobile: false })
const emit = defineEmits<{ navigate: [] }>()

const auth = useAuthStore()
const chat = useChatStore()
const ui = useUiStore()
const router = useRouter()
const route = useRoute()

const search = ref('')
const searchOpen = computed(() => ui.sessionSearchOpen)
const searchInput = ref<HTMLInputElement | null>(null)
const groupsOpen = ref<Record<number, boolean>>({})

const renameInput = ref<HTMLInputElement | null>(null)
const renameDialog = useNameDialog<ChatSession>('重命名失败', renameInput, async (session, name) => {
  if (session) await chat.renameSession(session, name)
})
const renameOpen = renameDialog.open
const renameValue = renameDialog.value

const deleteOpen = ref(false)
const deleteTarget = ref<ChatSession | null>(null)

const groupInput = ref<HTMLInputElement | null>(null)
const groupDialog = useNameDialog<SessionGroup>('保存分组失败', groupInput, async (group, name) => {
  if (group) await chat.renameGroup(group, name)
  else await chat.createGroup(name)
})
const groupOpen = groupDialog.open
const groupEditing = groupDialog.target
const groupName = groupDialog.value

const deleteGroupOpen = ref(false)
const deleteGroupTarget = ref<SessionGroup | null>(null)

const showGrouped = computed(() => !search.value.trim())

const sessionsByGroup = computed(() => {
  const map = new Map<number, ChatSession[]>()
  for (const group of chat.groups) map.set(group.id, [])
  const ungrouped: ChatSession[] = []
  for (const session of chat.sessions) {
    if (session.group_id != null && map.has(session.group_id)) {
      map.get(session.group_id)!.push(session)
    } else {
      ungrouped.push(session)
    }
  }
  return { map, ungrouped }
})

let searchTimer: number | null = null
watch(searchOpen, async (open, wasOpen) => {
  if (open) {
    await nextTick()
    searchInput.value?.focus()
    return
  }
  if (wasOpen) {
    search.value = ''
    void chat.searchSessions('')
  }
}, { immediate: true })

watch(search, (value) => {
  if (!searchOpen.value) return
  if (searchTimer !== null) window.clearTimeout(searchTimer)
  searchTimer = window.setTimeout(() => {
    searchTimer = null
    void chat.searchSessions(value).catch((error) => {
      toast.error('搜索对话失败', { description: errorMessage(error) })
    })
  }, 250)
})

onBeforeUnmount(() => {
  if (searchTimer !== null) window.clearTimeout(searchTimer)
})

function isActive(id: string): boolean {
  return route.params.id === id
}

function goNew(): void {
  closeSearch()
  void router.push('/chat')
  ui.closeMobileSidebar()
  emit('navigate')
}

function openSession(session: ChatSession): void {
  closeSearch()
  if (!isActive(session.id)) void router.push(`/c/${session.id}`)
  ui.closeMobileSidebar()
  emit('navigate')
}

function openSettings(): void {
  closeSearch()
  ui.closeMobileSidebar()
  emit('navigate')
  void router.push({ name: 'settings', query: { from: route.fullPath } })
}

function openAdmin(): void {
  closeSearch()
  ui.closeMobileSidebar()
  emit('navigate')
  void router.push({ name: 'admin' })
}

function closeSearch(): void {
  ui.closeSessionSearch()
}

function closeMobileNav(): void {
  ui.closeSessionSearch()
  ui.closeMobileSidebar()
}

function isGroupOpen(id: number): boolean {
  return groupsOpen.value[id] !== false
}

function toggleGroup(id: number): void {
  groupsOpen.value = { ...groupsOpen.value, [id]: !isGroupOpen(id) }
}

function openRename(session: ChatSession): void {
  void renameDialog.show(session, session.title || '新对话')
}

const submitRename = renameDialog.confirm

function askDelete(session: ChatSession): void {
  deleteTarget.value = session
  deleteOpen.value = true
}

async function confirmDelete(): Promise<void> {
  if (!deleteTarget.value) return
  const id = deleteTarget.value.id
  const wasCurrent = route.params.id === id
  try {
    await chat.deleteSession(deleteTarget.value)
    deleteOpen.value = false
    toast.success('对话已删除')
    if (wasCurrent) await router.push('/chat')
  } catch (error) {
    toast.error('删除失败', { description: errorMessage(error) })
  }
}

function openGroupDialog(group?: SessionGroup): void {
  void groupDialog.show(group ?? null, group?.name ?? '')
}

const submitGroup = groupDialog.confirm

function askDeleteGroup(group: SessionGroup): void {
  deleteGroupTarget.value = group
  deleteGroupOpen.value = true
}

async function confirmDeleteGroup(): Promise<void> {
  if (!deleteGroupTarget.value) return
  try {
    await chat.deleteGroup(deleteGroupTarget.value)
    deleteGroupOpen.value = false
  } catch (error) {
    toast.error('删除分组失败', { description: errorMessage(error) })
  }
}

function logout(): void {
  chat.resetCurrent()
  auth.logout()
  void router.replace('/login')
}
</script>

<template>
  <aside class="flex h-full w-full flex-col bg-sidebar text-sidebar-foreground">
    <div class="flex h-14 shrink-0 items-center gap-1 px-3">
      <div class="flex min-w-0 flex-1 items-center gap-2.5 px-1 py-1">
        <BrandMark size="sm" />
        <span class="min-w-0 flex-1">
          <span class="block truncate text-[13.5px] font-semibold leading-4">PigeonAgent</span>
          <span class="block truncate text-[11.5px] leading-4 text-muted-foreground">工作区</span>
        </span>
      </div>
      <button
        type="button"
        class="grid size-8 shrink-0 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground"
        :class="searchOpen ? 'bg-sidebar-accent text-sidebar-foreground' : ''"
        aria-label="搜索对话"
        @click="ui.toggleSessionSearch()"
      >
        <Search class="size-4" :stroke-width="1.8" />
      </button>
      <button
        v-if="mobile"
        type="button"
        class="grid size-8 shrink-0 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground"
        aria-label="关闭侧边栏"
        @click="closeMobileNav"
      >
        <X class="size-4" />
      </button>
    </div>

    <Transition name="search-reveal">
      <div v-if="searchOpen" class="px-2.5 pb-2">
        <label class="flex h-8 items-center gap-2 rounded-md border border-sidebar-border bg-background px-2.5 text-muted-foreground transition-colors focus-within:border-foreground/25">
          <Search class="size-3.5 shrink-0" />
          <input
            ref="searchInput"
            v-model="search"
            type="text"
            placeholder="搜索对话"
            class="h-full w-full border-0 bg-transparent text-[13px] text-sidebar-foreground outline-none placeholder:text-muted-foreground/80"
            @keydown.esc="closeSearch"
          >
          <button
            v-if="search"
            type="button"
            class="grid size-4 place-items-center rounded-full text-muted-foreground hover:text-foreground"
            aria-label="清空搜索"
            @click="search = ''"
          >
            <X class="size-3" />
          </button>
        </label>
      </div>
    </Transition>

    <div class="scrollbar-none flex min-h-0 flex-1 flex-col overflow-y-auto px-2.5 pb-3">
      <div class="pb-2">
        <button
          type="button"
          class="flex h-9 w-full items-center gap-2.5 rounded-md border border-transparent px-2.5 text-[13.5px] font-medium text-sidebar-foreground transition-colors hover:bg-sidebar-accent/60"
          @click="goNew"
        >
          <SquarePen class="size-[17px]" :stroke-width="1.8" />
          新对话
        </button>
      </div>
      <div v-if="showGrouped" class="sidebar-label justify-between">
        <span>分组</span>
        <TooltipHint text="新建分组">
          <button
            type="button"
            class="grid size-5 place-items-center rounded text-muted-foreground/70 transition-colors hover:bg-sidebar-accent hover:text-foreground"
            aria-label="新建分组"
            @click="openGroupDialog()"
          >
            <FolderPlus class="size-3.5" />
          </button>
        </TooltipHint>
      </div>

      <template v-if="showGrouped">
        <p v-if="!chat.groups.length" class="px-2.5 pb-1 pt-1 text-[11.5px] text-muted-foreground/60">还没有分组</p>
        <div v-for="group in chat.groups" :key="group.id" class="mb-1">
          <div class="group/grouphead flex h-9 items-center rounded-md pr-1 hover:bg-sidebar-accent/45">
            <button
              type="button"
              class="flex h-full min-w-0 flex-1 items-center gap-2 pl-2 text-left text-[13.5px] font-medium text-sidebar-foreground"
              @click="toggleGroup(group.id)"
            >
              <FolderOpen
                v-if="isGroupOpen(group.id)"
                class="size-4 shrink-0 text-muted-foreground"
                :stroke-width="1.8"
              />
              <Folder v-else class="size-4 shrink-0 text-muted-foreground" :stroke-width="1.8" />
              <span class="truncate">{{ group.name }}</span>
              <span class="text-[11px] font-normal text-muted-foreground/70">{{ group.session_count }}</span>
            </button>
            <DropdownMenu>
              <DropdownMenuTrigger as-child>
                <button
                  type="button"
                  class="grid size-6 place-items-center rounded-md text-muted-foreground opacity-100 transition-opacity hover:bg-sidebar-accent sm:opacity-0 sm:group-hover/grouphead:opacity-100 sm:focus-visible:opacity-100"
                  aria-label="分组操作"
                >
                  <MoreHorizontal class="size-3.5" />
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" class="w-[160px] rounded-xl p-1.5">
                <DropdownMenuItem class="cursor-pointer rounded-lg text-[13px]" @select="openGroupDialog(group)">
                  重命名分组
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem class="cursor-pointer rounded-lg text-[13px] text-destructive focus:text-destructive" @select="askDeleteGroup(group)">
                  删除分组
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          <div v-show="isGroupOpen(group.id)" class="mt-0.5 space-y-0.5">
            <p
              v-if="group.session_count === 0"
              class="py-1.5 pl-6 text-[11.5px] text-muted-foreground/60"
            >
              暂无对话
            </p>
            <SessionRow
              v-for="session in sessionsByGroup.map.get(group.id)"
              :key="session.id"
              :session="session"
              :active="isActive(session.id)"
              indented
              @open="openSession"
              @rename="openRename"
              @delete="askDelete"
            />
          </div>
        </div>

        <div v-if="sessionsByGroup.ungrouped.length">
          <div class="sidebar-label">最近</div>
          <div class="space-y-0.5">
            <SessionRow
              v-for="session in sessionsByGroup.ungrouped"
              :key="session.id"
              :session="session"
              :active="isActive(session.id)"
              @open="openSession"
              @rename="openRename"
              @delete="askDelete"
            />
          </div>
        </div>
        <div v-if="chat.sessionsHasMore" class="px-0.5 py-1">
          <button
            type="button"
            class="h-8 w-full rounded-md text-[12px] text-muted-foreground transition-colors hover:bg-sidebar-accent/60 hover:text-foreground disabled:opacity-50"
            :disabled="chat.loadingMoreSessions"
            @click="chat.loadMoreSessions()"
          >
            {{ chat.loadingMoreSessions ? '加载中…' : '加载更多对话' }}
          </button>
        </div>
      </template>

      <template v-else>
        <div class="sidebar-label gap-2">
          搜索结果
          <span class="text-[12px] font-normal text-muted-foreground/60">{{ chat.searchResults.length }}</span>
        </div>
        <div v-if="chat.searchResults.length" class="space-y-0.5">
          <SessionRow
            v-for="session in chat.searchResults"
            :key="session.id"
            :session="session"
            :active="isActive(session.id)"
            @open="openSession"
            @rename="openRename"
            @delete="askDelete"
          />
        </div>
        <p v-else class="px-3 py-6 text-center text-[12.5px] text-muted-foreground">
          {{ chat.searching ? '搜索中…' : '没有匹配的对话' }}
        </p>
      </template>
    </div>

    <div class="border-t border-sidebar-border/80 p-2.5">
      <DropdownMenu>
        <DropdownMenuTrigger as-child>
          <button
            type="button"
            class="flex w-full items-center gap-2.5 rounded-md px-1.5 py-1.5 text-left transition-colors hover:bg-sidebar-accent/60"
            aria-label="账户菜单"
          >
            <UserAvatar size="sm" />
            <span class="min-w-0 flex-1">
              <span class="block truncate text-[13px] font-medium leading-4">{{ auth.displayName }}</span>
              <span class="block truncate text-[11.5px] leading-4 text-muted-foreground">{{ auth.user?.email }}</span>
            </span>
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" side="top" class="w-[232px]">
          <DropdownMenuItem class="cursor-default text-[13px]">
            <UserRound class="mr-2 size-4" />
            {{ auth.user?.is_admin ? '管理员账户' : '个人账户' }}
          </DropdownMenuItem>
          <DropdownMenuItem class="cursor-default text-[13px]" title="按 token 用量折算，详见设置页的用量统计">
            <Coins class="mr-2 size-4" />
            <span class="flex-1">积分余额</span>
            <span class="ml-auto font-mono text-[12.5px] tabular-nums">
              {{ formatCredits(auth.user?.credits_balance) }}
            </span>
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem class="cursor-pointer text-[13px]" @select="openSettings">
            <Settings class="mr-2 size-4" />
            设置
          </DropdownMenuItem>
          <DropdownMenuItem
            v-if="auth.user?.is_admin"
            class="cursor-pointer text-[13px]"
            @select="openAdmin"
          >
            <LayoutDashboard class="mr-2 size-4" />
            管理后台
          </DropdownMenuItem>
          <DropdownMenuSeparator />
          <DropdownMenuItem class="cursor-pointer text-[13px]" @select="logout">
            <LogOut class="mr-2 size-4" />
            退出登录
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>

    <Dialog v-model:open="renameOpen">
      <DialogContent class="max-w-[400px] rounded-2xl">
        <DialogHeader>
          <DialogTitle class="text-[17px] font-semibold tracking-[-0.02em]">重命名对话</DialogTitle>
          <DialogDescription class="text-[13px] text-muted-foreground">
            一个清晰的名字，方便之后找回。
          </DialogDescription>
        </DialogHeader>
        <input
          ref="renameInput"
          v-model="renameValue"
          maxlength="200"
          aria-label="对话标题"
          class="h-10 w-full rounded-lg border border-input bg-background px-3 text-[14px] outline-none transition-colors placeholder:text-muted-foreground/70 focus:border-foreground/25"
          @keydown.enter="submitRename"
        >
        <DialogFooter>
          <Button variant="outline" class="rounded-full shadow-none" @click="renameOpen = false">取消</Button>
          <Button class="rounded-full shadow-none" @click="submitRename">保存</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="groupOpen">
      <DialogContent class="max-w-[400px] rounded-2xl">
        <DialogHeader>
          <DialogTitle class="text-[17px] font-semibold tracking-[-0.02em]">
            {{ groupEditing ? '重命名分组' : '新建分组' }}
          </DialogTitle>
          <DialogDescription class="text-[13px] text-muted-foreground">
            把同一分组的对话整理在一起。
          </DialogDescription>
        </DialogHeader>
        <input
          ref="groupInput"
          v-model="groupName"
          maxlength="60"
          aria-label="分组名称"
          placeholder="例如：产品设计"
          class="h-10 w-full rounded-lg border border-input bg-background px-3 text-[14px] outline-none transition-colors placeholder:text-muted-foreground/70 focus:border-foreground/25"
          @keydown.enter="submitGroup"
        >
        <DialogFooter>
          <Button variant="outline" class="rounded-full shadow-none" @click="groupOpen = false">取消</Button>
          <Button class="rounded-full shadow-none" :disabled="!groupName.trim()" @click="submitGroup">保存</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <AlertDialog v-model:open="deleteOpen">
      <AlertDialogContent class="max-w-[420px] rounded-2xl">
        <AlertDialogHeader>
          <AlertDialogTitle class="text-[17px] font-semibold tracking-[-0.02em]">删除对话？</AlertDialogTitle>
          <AlertDialogDescription class="text-[13.5px] leading-6 text-muted-foreground">
            “{{ deleteTarget?.title || '未命名对话' }}”及其所有消息将被永久删除，无法恢复。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel class="rounded-full">取消</AlertDialogCancel>
          <AlertDialogAction class="rounded-full bg-destructive text-white hover:bg-destructive/90" @click="confirmDelete">
            删除
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>

    <AlertDialog v-model:open="deleteGroupOpen">
      <AlertDialogContent class="max-w-[420px] rounded-2xl">
        <AlertDialogHeader>
          <AlertDialogTitle class="text-[17px] font-semibold tracking-[-0.02em]">删除分组？</AlertDialogTitle>
          <AlertDialogDescription class="text-[13.5px] leading-6 text-muted-foreground">
            “{{ deleteGroupTarget?.name }}”中的对话会移到最近，不会被删除。
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel class="rounded-full">取消</AlertDialogCancel>
          <AlertDialogAction class="rounded-full bg-destructive text-white hover:bg-destructive/90" @click="confirmDeleteGroup">
            删除分组
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  </aside>
</template>

<style scoped>
/* 侧栏分节标题：分组、日期段、搜索结果共用一处，改字号只动这里 */
.sidebar-label {
  display: flex;
  align-items: center;
  flex: none;
  height: 2rem;
  padding-inline: 10px;
  color: color-mix(in srgb, var(--muted-foreground) 82%, var(--foreground));
  font-size: 12.5px;
  font-weight: 500;
  letter-spacing: 0.02em;
}
</style>
