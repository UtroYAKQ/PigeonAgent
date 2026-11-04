<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  Home,
  LayoutDashboard,
  LogOut,
  Settings,
  UserRound,
  X,
} from '@lucide/vue'

import BrandMark from '@/components/brand/BrandMark.vue'
import UserAvatar from '@/components/user/UserAvatar.vue'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { ConsoleNavItem } from '@/components/console/types'
import { useAuthStore } from '@/stores/auth'

const props = withDefaults(
  defineProps<{
    title: string
    area: 'settings' | 'admin'
    groups: string[]
    items: ConsoleNavItem[]
    active: string
    mobile?: boolean
  }>(),
  { mobile: false },
)

const emit = defineEmits<{
  select: [key: string]
  back: []
  close: []
}>()

const auth = useAuthStore()
const router = useRouter()
const navRef = ref<HTMLElement | null>(null)

const grouped = computed(() =>
  props.groups
    .map(group => ({
      group,
      items: props.items.filter(item => item.group === group),
    }))
    .filter(group => group.items.length > 0),
)

watch(
  () => [props.active, props.mobile] as const,
  async () => {
    await nextTick()
    navRef.value
      ?.querySelector<HTMLElement>(`[data-console-key="${props.active}"]`)
      ?.scrollIntoView({ block: 'nearest' })
  },
  { immediate: true },
)

function select(key: string): void {
  emit('select', key)
  if (props.mobile) emit('close')
}

function closeIfMobile(): void {
  if (props.mobile) emit('close')
}

function goWorkspace(): void {
  emit('back')
  closeIfMobile()
}

function goSettings(): void {
  if (props.area === 'settings') return
  void router.push({ name: 'settings' })
  closeIfMobile()
}

function goAdmin(): void {
  if (props.area === 'admin') return
  void router.push({ name: 'admin' })
  closeIfMobile()
}

function logout(): void {
  auth.logout()
  void router.replace('/login')
  closeIfMobile()
}
</script>

<template>
  <div class="flex h-full flex-col bg-sidebar text-sidebar-foreground">
    <div class="flex h-14 shrink-0 items-center gap-1 px-3">
      <div class="flex min-w-0 flex-1 items-center gap-2.5 px-1 py-1">
        <BrandMark size="sm" />
        <span class="min-w-0 flex-1">
          <span class="block truncate text-[13.5px] font-semibold leading-4">PigeonAgent</span>
          <span class="block truncate text-[11.5px] leading-4 text-muted-foreground">{{ title }}</span>
        </span>
      </div>
      <button
        v-if="mobile"
        type="button"
        class="grid size-8 shrink-0 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground"
        aria-label="关闭导航"
        @click="emit('close')"
      >
        <X class="size-4" />
      </button>
    </div>

    <nav ref="navRef" class="scrollbar-none min-h-0 flex-1 overflow-y-auto px-2.5 pb-4">
      <template v-for="group in grouped" :key="group.group">
        <p class="px-2.5 pb-1 pt-3 text-[11.5px] font-medium text-muted-foreground">
          {{ group.group }}
        </p>
        <div class="space-y-0.5">
          <button
            v-for="item in group.items"
            :key="item.key"
            type="button"
            :data-console-key="item.key"
            class="flex h-9 w-full items-center gap-2.5 rounded-md border px-2.5 text-[13.5px] transition-colors"
            :class="active === item.key
              ? 'border-sidebar-border bg-background font-medium text-sidebar-foreground'
              : 'border-transparent text-muted-foreground hover:bg-sidebar-accent/60 hover:text-sidebar-foreground'"
            :aria-current="active === item.key ? 'page' : undefined"
            @click="select(item.key)"
          >
            <component :is="item.icon" class="size-[17px] shrink-0" :stroke-width="1.8" />
            <span class="min-w-0 flex-1 truncate text-left">{{ item.label }}</span>
            <span v-if="item.count" class="text-[11px] tabular-nums text-muted-foreground">{{ item.count }}</span>
          </button>
        </div>
      </template>
    </nav>

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
          <DropdownMenuSeparator />
          <DropdownMenuItem class="cursor-pointer text-[13px]" @select="goWorkspace">
            <Home class="mr-2 size-4" />
            返回工作区
          </DropdownMenuItem>
          <DropdownMenuItem v-if="area !== 'settings'" class="cursor-pointer text-[13px]" @select="goSettings">
            <Settings class="mr-2 size-4" />
            设置
          </DropdownMenuItem>
          <DropdownMenuItem
            v-if="auth.user?.is_admin && area !== 'admin'"
            class="cursor-pointer text-[13px]"
            @select="goAdmin"
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
  </div>
</template>
