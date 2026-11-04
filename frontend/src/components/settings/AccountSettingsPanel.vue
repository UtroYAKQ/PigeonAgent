<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { toast } from 'vue-sonner'
import { Camera, Loader2, LogOut, MonitorOff } from '@lucide/vue'

import { filesApi } from '@/api/files'
import ConsoleSection from '@/components/console/ConsoleSection.vue'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import UserAvatar from '@/components/user/UserAvatar.vue'
import { errorMessage } from '@/lib/http'
import { validateNewPassword } from '@/lib/password'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()

const displayName = ref(auth.user?.display_name ?? '')
const saving = ref(false)
const saveError = ref<string | null>(null)
const avatarInput = ref<HTMLInputElement | null>(null)
const uploadingAvatar = ref(false)

const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')

const profileDirty = computed(
  () => displayName.value.trim() !== (auth.user?.display_name ?? ''),
)
const passwordDirty = computed(
  () => Boolean(currentPassword.value || newPassword.value || confirmPassword.value),
)
const hasChanges = computed(() => profileDirty.value || passwordDirty.value)

watch(
  () => auth.user?.display_name,
  value => {
    displayName.value = value ?? ''
  },
)

function pickAvatar(): void {
  avatarInput.value?.click()
}

async function onAvatarChange(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  if (!file.type.startsWith('image/')) {
    saveError.value = '头像必须是图片文件'
    return
  }
  if (file.size > 5 * 1024 * 1024) {
    saveError.value = '头像不能超过 5 MB'
    return
  }
  uploadingAvatar.value = true
  saveError.value = null
  try {
    const record = await filesApi.upload(file)
    await auth.updateProfile({ avatar_file_id: record.id })
    toast.success('头像已更新')
  } catch (error) {
    saveError.value = errorMessage(error)
  } finally {
    uploadingAvatar.value = false
  }
}

async function removeAvatar(): Promise<void> {
  if (!auth.user?.avatar_file_id || uploadingAvatar.value) return
  uploadingAvatar.value = true
  saveError.value = null
  try {
    await auth.updateProfile({ avatar_file_id: null })
    toast.success('头像已移除')
  } catch (error) {
    saveError.value = errorMessage(error)
  } finally {
    uploadingAvatar.value = false
  }
}

async function saveAll(): Promise<void> {
  if (saving.value) return
  saveError.value = null

  if (passwordDirty.value) {
    if (!currentPassword.value) {
      saveError.value = '请输入当前密码'
      return
    }
    // 校验规则和注册、管理员重置共用同一份，口径跟后端写密码的约束一致
    const invalid = validateNewPassword(newPassword.value)
    if (invalid) {
      saveError.value = invalid
      return
    }
    if (newPassword.value !== confirmPassword.value) {
      saveError.value = '两次输入的新密码不一致'
      return
    }
  }
  if (!hasChanges.value) return

  saving.value = true
  try {
    if (profileDirty.value) {
      await auth.updateProfile({ display_name: displayName.value.trim() || null })
    }
    if (passwordDirty.value) {
      await auth.changePassword(currentPassword.value, newPassword.value)
      currentPassword.value = ''
      newPassword.value = ''
      confirmPassword.value = ''
    }
    toast.success('设置已保存')
  } catch (error) {
    saveError.value = errorMessage(error)
  } finally {
    saving.value = false
  }
}

function logout(): void {
  auth.logout()
  void router.replace({ name: 'login' })
}

const signingOutAll = ref(false)
const confirmSignOutAll = ref(false)

async function signOutEverywhere(): Promise<void> {
  // 这一条会连当前设备一起掉线，所以第一次点击只要求确认
  if (!confirmSignOutAll.value) {
    confirmSignOutAll.value = true
    return
  }
  if (signingOutAll.value) return
  signingOutAll.value = true
  try {
    await auth.signOutEverywhere()
    void router.replace({ name: 'login' })
  } catch (error) {
    toast.error('登出所有设备失败', { description: errorMessage(error) })
    confirmSignOutAll.value = false
  } finally {
    signingOutAll.value = false
  }
}
</script>

<template>
  <div class="space-y-8 pt-3">
    <ConsoleSection title="个人资料" description="这些信息会显示在侧栏账户区域。">
      <div class="space-y-5">
        <div class="flex items-center gap-4">
          <button
            type="button"
            class="group relative size-12 shrink-0 overflow-hidden rounded-full border border-border"
            aria-label="更换头像"
            :disabled="uploadingAvatar"
            @click="pickAvatar"
          >
            <UserAvatar size="lg" shape="circle" class="border-0" />
            <span class="absolute inset-0 grid place-items-center bg-black/45 text-white opacity-0 transition-opacity group-hover:opacity-100">
              <Loader2 v-if="uploadingAvatar" class="size-4 animate-spin" />
              <Camera v-else class="size-4" />
            </span>
          </button>
          <input
            ref="avatarInput"
            type="file"
            accept="image/*"
            class="hidden"
            @change="onAvatarChange"
          >
          <div class="min-w-0 flex-1">
            <p class="truncate text-sm font-medium">{{ auth.displayName }}</p>
            <p class="truncate text-sm text-muted-foreground">{{ auth.user?.email }}</p>
            <div class="mt-2 flex flex-wrap items-center gap-2">
              <Button
                variant="outline"
                size="xs"
                :disabled="uploadingAvatar"
                @click="pickAvatar"
              >
                <Camera class="size-3" />
                更换头像
              </Button>
              <Button
                v-if="auth.user?.avatar_file_id"
                variant="ghost"
                size="xs"
                class="text-muted-foreground"
                :disabled="uploadingAvatar"
                @click="removeAvatar"
              >
                移除
              </Button>
            </div>
          </div>
          <Badge variant="outline">{{ auth.user?.is_admin ? '管理员' : '成员' }}</Badge>
        </div>

        <div class="grid gap-2">
          <label for="display-name" class="text-sm font-medium">显示名称</label>
          <Input
            id="display-name"
            v-model="displayName"
            maxlength="64"
            placeholder="你的名字"
            class="h-9 max-w-[420px] text-sm"
          />
          <p class="text-sm leading-6 text-muted-foreground">
            会显示在侧栏账户区域；留空则使用邮箱前缀。
          </p>
        </div>

        <div class="grid gap-2">
          <label class="text-sm font-medium">登录邮箱</label>
          <Input
            :model-value="auth.user?.email ?? ''"
            disabled
            class="h-9 max-w-[420px] bg-muted/50 text-sm text-muted-foreground"
          />
          <p class="text-sm leading-6 text-muted-foreground">登录凭据，暂不支持在这里修改。</p>
        </div>
      </div>
    </ConsoleSection>

    <ConsoleSection title="修改密码" description="更新后当前账号的旧登录令牌会失效。">
      <div class="space-y-4">
        <div class="grid gap-4 sm:grid-cols-3">
          <label class="grid gap-2">
            <span class="text-sm font-medium">当前密码</span>
            <Input
              v-model="currentPassword"
              type="password"
              autocomplete="current-password"
              class="h-9 text-sm"
            />
          </label>
          <label class="grid gap-2">
            <span class="text-sm font-medium">新密码</span>
            <Input
              v-model="newPassword"
              type="password"
              autocomplete="new-password"
              placeholder="至少 8 个字符"
              class="h-9 text-sm"
            />
          </label>
          <label class="grid gap-2">
            <span class="text-sm font-medium">确认新密码</span>
            <Input
              v-model="confirmPassword"
              type="password"
              autocomplete="new-password"
              class="h-9 text-sm"
            />
          </label>
        </div>
      </div>
    </ConsoleSection>

    <div class="flex flex-wrap items-center gap-3">
      <Button
        class="h-9"
        :disabled="!hasChanges || saving"
        @click="saveAll"
      >
        <Loader2 v-if="saving" class="size-3.5 animate-spin" />
        保存
      </Button>
      <p v-if="saveError" class="min-w-0 text-sm leading-6 text-destructive">{{ saveError }}</p>
    </div>

    <ConsoleSection title="登录状态" description="退出后需要重新输入邮箱和密码。">
      <div class="flex flex-wrap items-center justify-between gap-4">
        <div class="min-w-0">
          <p class="text-sm font-medium">当前设备已登录</p>
          <p class="mt-1 text-sm text-muted-foreground">如果需要切换账号，请先退出当前登录。</p>
        </div>
        <Button variant="outline" class="h-9 shrink-0" @click="logout">
          <LogOut class="size-4" />
          退出登录
        </Button>
      </div>

      <div class="mt-4 flex flex-wrap items-center justify-between gap-4 border-t border-border pt-4">
        <div class="min-w-0">
          <p class="text-sm font-medium">登出所有设备</p>
          <p class="mt-1 text-sm leading-6 text-muted-foreground">
            作废这个账号已签发的全部登录令牌，这台设备也一样掉线。怀疑口令泄露时用这一条。
          </p>
        </div>
        <Button
          :variant="confirmSignOutAll ? 'default' : 'outline'"
          class="h-9 shrink-0"
          :disabled="signingOutAll"
          @click="signOutEverywhere"
        >
          <Loader2 v-if="signingOutAll" class="size-4 animate-spin" />
          <MonitorOff v-else class="size-4" />
          {{ confirmSignOutAll ? '确认登出所有设备' : '登出所有设备' }}
        </Button>
      </div>
    </ConsoleSection>
  </div>
</template>
