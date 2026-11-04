<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useDebounceFn } from '@vueuse/core'
import { toast } from 'vue-sonner'
import { formatCredits } from '@/lib/format'
import {
  Coins,
  KeyRound,
  Loader2,
  MoreHorizontal,
  RefreshCw,
  ShieldCheck,
  ShieldOff,
  UserCheck,
  UserX,
  UsersRound,
} from '@lucide/vue'

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
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import AdminPager from '@/components/admin/AdminPager.vue'
import TableFrame from '@/components/console/TableFrame.vue'
import { adminApi } from '@/api/admin'
import { usePagedTable } from '@/composables/usePagedTable'
import { formatAdminDate, formatAdminTime } from '@/lib/admin'
import { formatRelativeTime } from '@/lib/format'
import { errorMessage } from '@/lib/http'
import { validateNewPassword } from '@/lib/password'
import { useAuthStore } from '@/stores/auth'
import type { AdminUser } from '@/types/api'

const auth = useAuthStore()
const query = ref('')
const {
  items: users,
  total,
  loading,
  error,
  offset,
  limit,
  rangeLabel,
  load,
  page,
} = usePagedTable<AdminUser>({
  limit: 20,
  fetchPage: params => adminApi.users({ q: query.value.trim() || undefined, ...params }),
})

const pending = ref<{ user: AdminUser; kind: 'role' | 'status' } | null>(null)
const confirmOpen = ref(false)
const saving = ref(false)
const passwordOpen = ref(false)
const passwordTarget = ref<AdminUser | null>(null)
const newPassword = ref('')
const passwordSaving = ref(false)
const passwordError = ref<string | null>(null)

const creditOpen = ref(false)
const creditTarget = ref<AdminUser | null>(null)
const creditDelta = ref<string>('')
const creditNote = ref('')
const creditSaving = ref(false)
const creditError = ref<string | null>(null)

// 不合规就先把「重置」按钮按住；真正的报错仍在提交时展示
const newPasswordProblem = computed(() => validateNewPassword(newPassword.value))

function isSelf(user: AdminUser): boolean {
  return user.id === auth.user?.id
}

function initials(user: AdminUser): string {
  const source = user.display_name || user.email
  return source.slice(0, 1).toUpperCase()
}

/** 启用/停用是管理动作，待验证是注册流程没走完；三者不能混成一个「停用」。 */
function accountState(user: AdminUser): { label: string; dot: string } {
  if (user.is_active) return { label: '启用', dot: 'bg-primary' }
  if (!user.email_verified) return { label: '待验证', dot: 'bg-amber-500' }
  return { label: '停用', dot: 'bg-muted-foreground/40' }
}

const search = useDebounceFn(() => load(true), 300)
watch(query, search)
onMounted(() => load(true))

function askChange(user: AdminUser, kind: 'role' | 'status'): void {
  pending.value = { user, kind }
  confirmOpen.value = true
}

async function confirmChange(): Promise<void> {
  const target = pending.value
  if (!target || saving.value) return
  saving.value = true
  try {
    const updated = await adminApi.updateUser(
      target.user.id,
      target.kind === 'role'
        ? { is_admin: !target.user.is_admin }
        : { is_active: !target.user.is_active },
    )
    users.value = users.value.map(item => (item.id === updated.id ? updated : item))
    toast.success(
      target.kind === 'role'
        ? updated.is_admin ? '已设为管理员' : '已取消管理员'
        : updated.is_active ? '账号已启用' : '账号已停用',
    )
    confirmOpen.value = false
    pending.value = null
  } catch (caught) {
    toast.error('操作失败', { description: errorMessage(caught) })
  } finally {
    saving.value = false
  }
}

function askResetPassword(user: AdminUser): void {
  passwordTarget.value = user
  newPassword.value = ''
  passwordError.value = null
  passwordOpen.value = true
}

async function submitResetPassword(): Promise<void> {
  const target = passwordTarget.value
  if (!target || passwordSaving.value) return
  passwordError.value = null
  // 规则只有一份，和后端写密码的约束同源：这里放行、后端拒绝最难受
  const invalid = validateNewPassword(newPassword.value)
  if (invalid) {
    passwordError.value = invalid
    return
  }
  passwordSaving.value = true
  try {
    await adminApi.resetUserPassword(target.id, newPassword.value)
    toast.success(`已重置 ${target.email} 的密码`, { description: '该用户旧的登录令牌已失效' })
    passwordOpen.value = false
    passwordTarget.value = null
  } catch (caught) {
    passwordError.value = errorMessage(caught)
  } finally {
    passwordSaving.value = false
  }
}

function askAdjustCredits(user: AdminUser): void {
  creditTarget.value = user
  creditDelta.value = ''
  creditNote.value = ''
  creditError.value = null
  creditOpen.value = true
}

async function submitAdjustCredits(): Promise<void> {
  const target = creditTarget.value
  if (!target || creditSaving.value) return
  creditError.value = null
  const delta = Number(creditDelta.value)
  if (!Number.isFinite(delta) || delta === 0) {
    creditError.value = '请输入非零数字：正数充值，负数扣减，支持小数'
    return
  }
  creditSaving.value = true
  try {
    const updated = await adminApi.adjustCredits(target.id, delta, creditNote.value.trim() || undefined)
    users.value = users.value.map(item => (item.id === updated.id ? updated : item))
    toast.success(
      delta > 0
        ? `已为 ${updated.email} 充值 ${formatCredits(delta)} 积分`
        : `已从 ${updated.email} 扣减 ${formatCredits(-delta)} 积分`,
    )
    creditOpen.value = false
    creditTarget.value = null
  } catch (caught) {
    creditError.value = errorMessage(caught)
  } finally {
    creditSaving.value = false
  }
}
</script>

<template>
  <div>
    <TableFrame>
      <template #toolbar>
        <Input
          v-model="query"
          placeholder="搜索邮箱或名称"
          class="h-8 w-[260px] max-w-full text-[13px]"
        />
        <span class="flex-1" />
        <Button variant="outline" class="h-8" :disabled="loading" @click="load()">
          <RefreshCw class="size-3.5" :class="loading ? 'animate-spin' : ''" />
          刷新
        </Button>
      </template>

      <Table class="min-w-[960px] text-[13px]">
        <TableHeader>
          <TableRow>
            <TableHead class="h-9 px-4 text-[11px] font-medium text-muted-foreground">用户</TableHead>
            <TableHead class="h-9 px-4 text-[11px] font-medium text-muted-foreground">邮箱</TableHead>
            <TableHead class="h-9 w-[104px] px-4 text-[11px] font-medium text-muted-foreground">角色</TableHead>
            <TableHead class="h-9 w-[96px] px-4 text-[11px] font-medium text-muted-foreground">状态</TableHead>
            <TableHead class="h-9 w-[88px] px-4 text-right text-[11px] font-medium text-muted-foreground">积分</TableHead>
            <TableHead class="h-9 w-[72px] px-4 text-right text-[11px] font-medium text-muted-foreground">会话</TableHead>
            <TableHead class="h-9 w-[120px] px-4 text-[11px] font-medium text-muted-foreground">最近活跃</TableHead>
            <TableHead class="h-9 w-[128px] px-4 text-[11px] font-medium text-muted-foreground">注册时间</TableHead>
            <TableHead class="h-9 w-[56px] px-4 text-right text-[11px] font-medium text-muted-foreground" />
          </TableRow>
        </TableHeader>
        <TableBody>
          <template v-if="loading && !users.length">
            <TableRow v-for="index in 5" :key="index" class="hover:bg-transparent">
              <TableCell class="px-4 py-2.5">
                <div class="flex items-center gap-3">
                  <span class="size-9 animate-pulse rounded-full bg-muted" />
                  <div class="space-y-2">
                    <div class="h-3 w-32 animate-pulse rounded-full bg-muted" />
                    <div class="h-2.5 w-44 animate-pulse rounded-full bg-muted" />
                  </div>
                </div>
              </TableCell>
              <TableCell class="px-4 py-2.5"><div class="h-3 w-40 animate-pulse rounded-full bg-muted" /></TableCell>
              <TableCell class="px-4 py-2.5"><div class="h-5 w-14 animate-pulse rounded-md bg-muted" /></TableCell>
              <TableCell class="px-4 py-2.5"><div class="h-3 w-10 animate-pulse rounded-full bg-muted" /></TableCell>
              <TableCell class="px-4 py-2.5"><div class="ml-auto h-3 w-10 animate-pulse rounded-full bg-muted" /></TableCell>
              <TableCell class="px-4 py-2.5"><div class="ml-auto h-3 w-6 animate-pulse rounded-full bg-muted" /></TableCell>
              <TableCell class="px-4 py-2.5"><div class="h-3 w-16 animate-pulse rounded-full bg-muted" /></TableCell>
              <TableCell class="px-4 py-2.5"><div class="h-3 w-20 animate-pulse rounded-full bg-muted" /></TableCell>
              <TableCell class="px-4 py-2.5" />
            </TableRow>
          </template>

          <TableRow v-else-if="error" class="hover:bg-transparent">
            <TableCell colspan="9" class="px-4 py-12 text-center">
              <p class="text-sm font-medium">用户加载失败</p>
              <p class="mx-auto mt-1 max-w-[360px] text-sm leading-6 text-muted-foreground">{{ error }}</p>
              <Button variant="outline" class="mt-4 h-9" @click="load()">
                <RefreshCw class="size-4" />
                重试
              </Button>
            </TableCell>
          </TableRow>

          <TableRow v-else-if="!users.length" class="hover:bg-transparent">
            <TableCell colspan="9" class="px-4 py-14 text-center">
              <span class="mx-auto grid size-10 place-items-center rounded-full border border-border text-muted-foreground">
                <UsersRound class="size-4" />
              </span>
              <p class="mt-4 text-sm font-medium">{{ query ? '没有匹配的用户' : '还没有用户' }}</p>
              <p class="mt-1 text-sm text-muted-foreground">
                {{ query ? '换个邮箱或名称试试。' : '注册后的账号会出现在这里。' }}
              </p>
            </TableCell>
          </TableRow>

          <template v-else>
            <TableRow v-for="user in users" :key="user.id">
              <TableCell class="px-4 py-2.5">
                <div class="flex min-w-0 items-center gap-3">
                  <span class="grid size-8 shrink-0 place-items-center rounded-full border border-border bg-background text-[11px] font-medium">
                    {{ initials(user) }}
                  </span>
                  <div class="min-w-0">
                    <div class="flex items-center gap-2">
                      <span class="max-w-[140px] truncate text-[13px] font-medium sm:max-w-[240px]">
                        {{ user.display_name || user.email.split('@')[0] }}
                      </span>
                      <Badge v-if="isSelf(user)" variant="secondary" class="font-normal">
                        当前账号
                      </Badge>
                    </div>
                  </div>
                </div>
              </TableCell>
              <TableCell class="px-4 py-2.5">
                <div class="flex items-center gap-1.5">
                  <p class="max-w-[280px] truncate text-sm text-muted-foreground" :title="user.email">{{ user.email }}</p>
                  <Badge
                    v-if="!user.email_verified"
                    variant="outline"
                    class="shrink-0 text-[10px] text-amber-700 dark:text-amber-400"
                  >
                    未验证
                  </Badge>
                </div>
              </TableCell>
              <TableCell class="px-4 py-2.5">
                <Badge variant="outline" class="gap-1 font-normal">
                  <ShieldCheck v-if="user.is_admin" class="size-3" />
                  {{ user.is_admin ? '管理员' : '成员' }}
                </Badge>
              </TableCell>
              <TableCell class="px-4 py-2.5">
                <span class="inline-flex items-center gap-2 text-sm">
                  <span class="size-2 rounded-full" :class="accountState(user).dot" />
                  {{ accountState(user).label }}
                </span>
              </TableCell>
              <TableCell class="px-4 py-2.5 text-right text-sm tabular-nums">
                <span :class="user.credits_balance <= 0 ? 'text-destructive' : ''">
                  {{ formatCredits(user.credits_balance) }}
                </span>
              </TableCell>
              <TableCell class="px-4 py-2.5 text-right text-sm tabular-nums text-muted-foreground">
                {{ user.session_count }}
              </TableCell>
              <TableCell class="px-4 py-2.5 text-sm text-muted-foreground">
                <span v-if="user.last_active_at" :title="formatAdminTime(user.last_active_at)">
                  {{ formatRelativeTime(user.last_active_at) }}
                </span>
                <span v-else>—</span>
              </TableCell>
              <TableCell class="px-4 py-2.5 text-sm text-muted-foreground">
                <span :title="formatAdminTime(user.created_at)">{{ formatAdminDate(user.created_at) }}</span>
              </TableCell>
              <TableCell class="px-4 py-2.5 text-right">
                <DropdownMenu>
                  <DropdownMenuTrigger as-child>
                    <Button variant="ghost" size="icon-sm" class="size-8 text-muted-foreground" aria-label="用户操作">
                      <MoreHorizontal class="size-4" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end" class="w-[180px]">
                    <!-- 自己那行只有积分：角色/密码/停用都是"不能对自己做"的操作 -->
                    <template v-if="!isSelf(user)">
                      <DropdownMenuItem class="cursor-pointer text-[13px]" @select="askChange(user, 'role')">
                        <ShieldOff v-if="user.is_admin" class="mr-2 size-4" />
                        <ShieldCheck v-else class="mr-2 size-4" />
                        {{ user.is_admin ? '取消管理员' : '设为管理员' }}
                      </DropdownMenuItem>
                      <DropdownMenuItem class="cursor-pointer text-[13px]" @select="askResetPassword(user)">
                        <KeyRound class="mr-2 size-4" />
                        重置密码
                      </DropdownMenuItem>
                      <DropdownMenuSeparator />
                      <DropdownMenuItem
                        class="cursor-pointer text-[13px]"
                        :class="user.is_active ? 'text-destructive focus:text-destructive' : ''"
                        @select="askChange(user, 'status')"
                      >
                        <UserX v-if="user.is_active" class="mr-2 size-4" />
                        <UserCheck v-else class="mr-2 size-4" />
                        {{ user.is_active ? '停用账号' : '启用账号' }}
                      </DropdownMenuItem>
                    </template>
                    <DropdownMenuItem class="cursor-pointer text-[13px]" @select="askAdjustCredits(user)">
                      <Coins class="mr-2 size-4" />
                      调整积分
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </TableCell>
            </TableRow>
          </template>
        </TableBody>
      </Table>

      <template #footer>
        <p class="hidden text-xs text-muted-foreground sm:block">角色与状态变更会写入操作日志</p>
        <div class="ml-auto flex flex-wrap items-center gap-4">
          <p class="text-xs tabular-nums text-muted-foreground">共 {{ total }} 个账号 · {{ rangeLabel }}</p>
          <AdminPager :offset="offset" :limit="limit" :total="total" @page="page" />
        </div>
      </template>
    </TableFrame>

    <AlertDialog v-model:open="confirmOpen">
      <AlertDialogContent class="console-surface max-w-[420px]">
        <AlertDialogHeader>
          <AlertDialogTitle>
            {{ pending?.kind === 'role'
              ? pending?.user.is_admin ? '取消管理员？' : '设为管理员？'
              : pending?.user.is_active ? '停用账号？' : '启用账号？' }}
          </AlertDialogTitle>
          <AlertDialogDescription>
            <template v-if="pending">
              {{ pending.kind === 'role'
                ? pending.user.is_admin
                  ? `${pending.user.email} 将失去平台管理权限。`
                  : `${pending.user.email} 将获得平台管理权限。`
                : pending.user.is_active
                  ? `${pending.user.email} 将无法登录，历史数据会保留。`
                  : pending.user.email_verified
                    ? `${pending.user.email} 将恢复登录。`
                    : `${pending.user.email} 的邮箱尚未验证；启用后该账号无需验证码即可登录。` }}
            </template>
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel>取消</AlertDialogCancel>
          <AlertDialogAction
            :class="(pending?.kind === 'role' && pending?.user.is_admin) || (pending?.kind === 'status' && pending?.user.is_active) ? 'bg-destructive text-white hover:bg-destructive/90' : ''"
            @click="confirmChange"
          >
            <Loader2 v-if="saving" class="mr-1 size-4 animate-spin" />
            确认
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>

    <Dialog v-model:open="passwordOpen">
      <DialogContent class="console-surface max-w-[420px]">
        <DialogHeader>
          <DialogTitle>重置密码</DialogTitle>
          <DialogDescription>
            为 {{ passwordTarget?.email }} 设置新密码。保存后该用户所有已签发令牌立即失效。
          </DialogDescription>
        </DialogHeader>
        <Input
          v-model="newPassword"
          type="password"
          autocomplete="new-password"
          placeholder="至少 8 个字符"
          class="h-9 text-sm"
          @keydown.enter="submitResetPassword"
        />
        <p v-if="passwordError" class="text-sm text-destructive">{{ passwordError }}</p>
        <DialogFooter>
          <Button variant="outline" @click="passwordOpen = false">
            取消
          </Button>
          <Button
            :disabled="passwordSaving || Boolean(newPasswordProblem)"
            @click="submitResetPassword"
          >
            <Loader2 v-if="passwordSaving" class="size-4 animate-spin" />
            重置
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>

    <Dialog v-model:open="creditOpen">
      <DialogContent class="console-surface max-w-[420px]">
        <DialogHeader>
          <DialogTitle>调整积分</DialogTitle>
          <DialogDescription>
            {{ creditTarget?.email }} 当前余额 {{ formatCredits(creditTarget?.credits_balance) }} 积分。
            正数充值、负数扣减，扣减可以把余额压成负数，下次充值自动抵扣；每次调整都会写入积分流水和操作日志。
          </DialogDescription>
        </DialogHeader>
        <div class="space-y-3">
          <Input
            v-model="creditDelta"
            type="number"
            step="0.01"
            placeholder="例如 100、10.5 或 -50"
            class="h-9 text-sm"
            @keydown.enter="submitAdjustCredits"
          />
          <Input
            v-model="creditNote"
            placeholder="备注（可选），例如「内测奖励」"
            class="h-9 text-sm"
          />
          <p v-if="creditError" class="text-sm text-destructive">{{ creditError }}</p>
        </div>
        <DialogFooter>
          <Button variant="outline" @click="creditOpen = false">
            取消
          </Button>
          <Button :disabled="creditSaving" @click="submitAdjustCredits">
            <Loader2 v-if="creditSaving" class="size-4 animate-spin" />
            确认调整
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  </div>
</template>
