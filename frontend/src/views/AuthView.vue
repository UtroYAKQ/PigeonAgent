<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Eye, EyeOff, Loader2 } from '@lucide/vue'

import WaveScene from '@/components/brand/WaveScene.vue'
import SignalField from '@/components/brand/SignalField.vue'
import PixelWordmark from '@/components/brand/PixelWordmark.vue'
import BrandMark from '@/components/brand/BrandMark.vue'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { isValidEmail } from '@/lib/email'
import { errorMessage, toApiError } from '@/lib/http'
import { validateNewPassword } from '@/lib/password'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const ui = useUiStore()

const mode = ref<'login' | 'register'>(route.meta.register ? 'register' : 'login')
const step = ref<'form' | 'verify'>('form')
const loading = ref(false)
const error = ref<string | null>(null)
const notice = ref<string | null>(null)
const showPassword = ref(false)
const resendIn = ref(0)
let timer: ReturnType<typeof setInterval> | null = null

const form = reactive({
  displayName: '',
  email: '',
  password: '',
  confirm: '',
})

const code = ref('')

const title = computed(() => {
  if (step.value === 'verify') return '查收验证码'
  return mode.value === 'login' ? '欢迎回来' : '创建账户'
})

const subtitle = computed(() => {
  if (step.value === 'verify') return `验证码已发送至 ${auth.pendingEmail || form.email}`
  return mode.value === 'login'
    ? '登录后继续你的工作。'
    : '填好邮箱和密码，开始第一条航线。'
})

function switchMode(next: 'login' | 'register'): void {
  if (loading.value) return
  mode.value = next
  step.value = 'form'
  error.value = null
  notice.value = null
  form.password = ''
  form.confirm = ''
  code.value = ''
  void router.replace({ name: next === 'login' ? 'login' : 'register' })
}

function redirectAfterLogin(): void {
  // 每次登录成功都收起工作区侧栏；用登录态/令牌判断即可，不需要“首次登录”标记。
  ui.collapseSidebar()
  void router.replace('/chat')
}

function startResendCountdown(): void {
  resendIn.value = 60
  if (timer) clearInterval(timer)
  timer = setInterval(() => {
    resendIn.value = Math.max(0, resendIn.value - 1)
    if (resendIn.value <= 0 && timer) {
      clearInterval(timer)
      timer = null
    }
  }, 1000)
}

async function submitForm(): Promise<void> {
  if (loading.value) return
  error.value = null
  notice.value = null

  if (!form.email.trim()) {
    error.value = '请输入邮箱'
    return
  }
  if (!isValidEmail(form.email)) {
    error.value = '请输入有效的邮箱地址'
    return
  }
  if (!form.password) {
    error.value = '请输入密码'
    return
  }
  // 只有注册这条写密码的路径才做强度校验；
  // 登录按后端 PasswordInput 的口径只要求非空，历史账号不该被前端挡住。
  if (mode.value === 'register') {
    const invalid = validateNewPassword(form.password)
    if (invalid) {
      error.value = invalid
      return
    }
    if (form.password !== form.confirm) {
      error.value = '两次输入的密码不一致'
      return
    }
  }

  loading.value = true
  try {
    if (mode.value === 'login') {
      await auth.login(form.email, form.password)
      redirectAfterLogin()
    } else {
      const result = await auth.register(form.email, form.password, form.displayName)
      if (result.verification_required) {
        step.value = 'verify'
        startResendCountdown()
      } else {
        redirectAfterLogin()
      }
    }
  } catch (err) {
    const apiError = toApiError(err)
    if (apiError.status === 409 && mode.value === 'login') {
      // 登录撞上未验证账号：后端已重发验证码，把人直接送去填码
      auth.setPendingEmail(form.email)
      step.value = 'verify'
      notice.value = apiError.message || '该邮箱尚未验证，验证码已重新发送'
      startResendCountdown()
      return
    }
    if (apiError.status === 409) {
      error.value = '该邮箱已注册，请直接登录'
      return
    }
    error.value = errorMessage(err)
  } finally {
    // 登录成功后马上要切到工作区：保持加载态到卸载，别让按钮先弹回“登录”
    if (!auth.isAuthenticated) loading.value = false
  }
}

async function submitCode(): Promise<void> {
  if (loading.value) return
  if (!/^\d{6}$/.test(code.value)) {
    error.value = '请输入 6 位数字验证码'
    return
  }
  error.value = null
  notice.value = null
  loading.value = true
  try {
    await auth.verify(code.value)
    redirectAfterLogin()
  } catch (err) {
    error.value = errorMessage(err)
  } finally {
    // 登录成功后马上要切到工作区：保持加载态到卸载，别让按钮先弹回“登录”
    if (!auth.isAuthenticated) loading.value = false
  }
}

async function resend(): Promise<void> {
  if (resendIn.value > 0) return
  error.value = null
  notice.value = null
  try {
    await auth.resend()
    notice.value = '验证码已重新发送，请查收邮箱'
    startResendCountdown()
  } catch (err) {
    error.value = errorMessage(err)
  }
}

watch(
  () => route.meta.register,
  value => {
    mode.value = value ? 'register' : 'login'
    step.value = 'form'
    error.value = null
  },
)

onMounted(() => {
  if (auth.pendingEmail) {
    form.email = auth.pendingEmail
    step.value = 'verify'
    startResendCountdown()
  }
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<template>
  <div class="console-surface relative grid min-h-dvh bg-background text-foreground min-[1280px]:grid-cols-[minmax(0,7fr)_minmax(0,3fr)]">
    <!-- 波浪区域：整页画布绘制，网格 + 字样都在区域内部，右栏在波浪之外 -->
    <WaveScene class="absolute inset-0 hidden min-[1280px]:block" />

    <aside class="relative hidden min-[1280px]:flex min-[1280px]:min-h-dvh min-[1280px]:flex-col min-[1280px]:px-14 min-[1280px]:pb-12 min-[1280px]:pt-9">
      <SignalField />

      <div class="relative z-10 flex items-center gap-2.5 text-sm font-semibold">
        <BrandMark size="sm" />
        <span>PigeonAgent</span>
      </div>

      <div class="relative z-10 my-auto flex justify-center py-14 min-[1280px]:py-10">
        <PixelWordmark class="h-[clamp(60px,12vh,116px)] w-full max-w-[680px]" />
      </div>
    </aside>

    <div class="relative flex flex-col px-6 py-10 sm:px-10 min-[1280px]:min-h-dvh min-[1280px]:py-8 min-[1280px]:pl-16 xl:pl-24">
      <main class="fade-in m-auto w-full max-w-[330px]">
        <header>
          <h1 class="font-title text-[30px] leading-tight sm:text-[32px]">{{ title }}</h1>
          <p class="mt-2 text-[13.5px] leading-6 text-muted-foreground">{{ subtitle }}</p>
        </header>

        <form v-if="step === 'form'" class="mt-8 grid gap-5" @submit.prevent="submitForm">
          <div v-if="mode === 'register'" class="grid gap-2">
            <Label for="display-name" class="text-[13px] font-medium">称呼</Label>
            <Input
              id="display-name"
              v-model="form.displayName"
              autocomplete="nickname"
              placeholder="可选"
              class="h-10 text-[13.5px]"
            />
          </div>

          <div class="grid gap-2">
            <Label for="email" class="text-[13px] font-medium">邮箱</Label>
            <Input
              id="email"
              v-model="form.email"
              type="email"
              autocomplete="email"
              placeholder="you@example.com"
              class="h-10 text-[13.5px]"
            />
          </div>

          <div class="grid gap-2">
            <Label for="password" class="text-[13px] font-medium">密码</Label>
            <div class="relative">
              <Input
                id="password"
                v-model="form.password"
                :type="showPassword ? 'text' : 'password'"
                :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
                placeholder="至少 8 个字符"
                class="h-10 pr-10 text-[13.5px]"
              />
              <button
                type="button"
                class="absolute inset-y-0 right-0 grid w-10 place-items-center text-muted-foreground transition-colors hover:text-foreground"
                :aria-label="showPassword ? '隐藏密码' : '显示密码'"
                @click="showPassword = !showPassword"
              >
                <EyeOff v-if="showPassword" class="size-4" />
                <Eye v-else class="size-4" />
              </button>
            </div>
          </div>

          <div v-if="mode === 'register'" class="grid gap-2">
            <Label for="confirm" class="text-[13px] font-medium">确认密码</Label>
            <Input
              id="confirm"
              v-model="form.confirm"
              type="password"
              autocomplete="new-password"
              placeholder="再次输入密码"
              class="h-10 text-[13.5px]"
            />
          </div>

          <p
            v-if="error"
            role="alert"
            class="rounded-md border border-destructive/20 bg-destructive/5 px-3 py-2 text-[12.5px] leading-5 text-destructive"
          >
            {{ error }}
          </p>

          <Button type="submit" class="h-10 w-full" :disabled="loading">
            <Loader2 v-if="loading" class="size-4 animate-spin" />
            <span>{{ mode === 'login' ? '登录' : '创建账户' }}</span>
          </Button>
        </form>

        <form v-else class="mt-8 grid gap-5" @submit.prevent="submitCode">
          <p
            v-if="notice"
            class="rounded-md border border-border bg-surface px-3 py-2 text-[12.5px] leading-5 text-muted-foreground"
          >
            {{ notice }}
          </p>

          <div class="grid gap-2">
            <Label for="code" class="text-[13px] font-medium">验证码</Label>
            <Input
              id="code"
              v-model="code"
              inputmode="numeric"
              autocomplete="one-time-code"
              maxlength="6"
              placeholder="000000"
              class="h-11 text-center font-mono text-lg tracking-[0.4em]"
            />
          </div>

          <p
            v-if="error"
            role="alert"
            class="rounded-md border border-destructive/20 bg-destructive/5 px-3 py-2 text-[12.5px] leading-5 text-destructive"
          >
            {{ error }}
          </p>

          <Button type="submit" class="h-10 w-full" :disabled="loading">
            <Loader2 v-if="loading" class="size-4 animate-spin" />
            <span>验证并登录</span>
          </Button>

          <div class="flex items-center justify-between text-[13px]">
            <button
              type="button"
              class="inline-flex items-center gap-1.5 text-muted-foreground transition-colors hover:text-foreground"
              @click="step = 'form'"
            >
              <ArrowLeft class="size-4" />
              返回
            </button>
            <button
              type="button"
              class="text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
              :disabled="resendIn > 0"
              @click="resend"
            >
              {{ resendIn > 0 ? `${resendIn}s 后可重新发送` : '重新发送' }}
            </button>
          </div>
        </form>

        <p v-if="step === 'form'" class="mt-7 text-[13px] text-muted-foreground">
          <template v-if="mode === 'login'">
            还没有账户？
            <button
              type="button"
              class="font-medium text-foreground underline-offset-4 hover:underline"
              @click="switchMode('register')"
            >
              创建一个
            </button>
          </template>
          <template v-else>
            已经有账户？
            <button
              type="button"
              class="font-medium text-foreground underline-offset-4 hover:underline"
              @click="switchMode('login')"
            >
              直接登录
            </button>
          </template>
        </p>

        <p
          v-if="mode === 'register' && step === 'form'"
          class="mt-4 text-[11.5px] leading-5 text-muted-foreground"
        >
          继续即表示你同意以负责任的方式使用本服务。
        </p>
      </main>
    </div>
  </div>
</template>

