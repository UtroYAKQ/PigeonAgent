<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from "vue";
import {
  Bird,
  Eye,
  EyeOff,
  LoaderCircle,
  MailCheck,
  MessageSquareText,
  Paperclip,
  Workflow,
} from "lucide-vue-next";

import { login, register, resendCode, verify } from "../lib/auth";
import { reportError } from "../lib/toast";

type Mode = "login" | "register" | "verify";

const mode = ref<Mode>("login");
const email = ref("");
const password = ref("");
const displayName = ref("");
const code = ref("");
const showPassword = ref(false);
const busy = ref(false);
const hint = ref("");
const resendIn = ref(0);
const formEl = ref<HTMLFormElement | null>(null);
let resendTimer = 0;

const HEADING = {
  login: { title: "欢迎回来", sub: "登录后接着上次的进度" },
  register: { title: "创建账号", sub: "一分钟就能开始第一轮对话" },
  verify: { title: "输入验证码", sub: "确认这个邮箱属于你" },
} as const;

const heading = computed(() => HEADING[mode.value]);
const codeReady = computed(() => /^\d{6}$/.test(code.value.trim()));

onBeforeUnmount(() => window.clearInterval(resendTimer));

function startResendCountdown(): void {
  resendIn.value = 60;
  if (resendTimer) window.clearInterval(resendTimer);
  resendTimer = window.setInterval(() => {
    resendIn.value -= 1;
    if (resendIn.value <= 0) window.clearInterval(resendTimer);
  }, 1000);
}

async function run(action: () => Promise<void>): Promise<void> {
  if (busy.value) return;
  busy.value = true;
  hint.value = "";
  try {
    await action();
  } catch (cause) {
    reportError(cause);
  } finally {
    busy.value = false;
  }
}

function submit(): void {
  // 浏览器自动填充有时不触发 input 事件，v-model 拿不到值；提交时兜底从 DOM 读一次
  const form = formEl.value;
  if (!email.value) email.value = (form?.querySelector<HTMLInputElement>("[name=email]")?.value ?? "").trim();
  if (!password.value) password.value = form?.querySelector<HTMLInputElement>("[name=password]")?.value ?? "";
  if (!displayName.value) displayName.value = (form?.querySelector<HTMLInputElement>("[name=nickname]")?.value ?? "").trim();

  if (mode.value === "login") {
    void run(async () => {
      await login(email.value.trim(), password.value);
      password.value = "";
    });
    return;
  }
  if (mode.value === "register") {
    void run(async () => {
      const result = await register(email.value.trim(), password.value, displayName.value.trim());
      if (result.verifyRequired) {
        mode.value = "verify";
        hint.value = "验证码已发送到邮箱，请查收";
        startResendCountdown();
      }
    });
    return;
  }
  void run(async () => {
    await verify(email.value.trim(), code.value.trim());
  });
}

function resend(): void {
  if (resendIn.value > 0) return;
  void run(async () => {
    await resendCode(email.value.trim());
    hint.value = "验证码已重新发送";
    startResendCountdown();
  });
}

function switchTo(next: Exclude<Mode, "verify">): void {
  mode.value = next;
  hint.value = "";
}

function backToLogin(): void {
  switchTo("login");
  code.value = "";
}

function onCodeInput(event: Event): void {
  code.value = (event.target as HTMLInputElement).value.replace(/\D/g, "").slice(0, 6);
  if (codeReady.value) submit();
}
</script>

<template>
  <div class="auth-flex">
    <!-- 左侧品牌区：桌面双栏，移动端隐藏 -->
    <aside class="auth-brand">
      <div class="auth-brand-head">
        <span class="auth-logo"><Bird :size="22" :stroke-width="1.7" /></span>
        <p class="auth-title">PigeonAgent</p>
        <p class="auth-sub">属于你、也能替你干活的对话工具</p>
      </div>

      <svg class="auth-deco" viewBox="0 0 320 96" fill="none" aria-hidden="true">
        <path
          d="M8 72C72 24 160 96 232 40 280 4 300 20 314 18"
          stroke="currentColor"
          stroke-width="1.4"
          stroke-dasharray="2 7"
          stroke-linecap="round"
        />
      </svg>

      <ul class="auth-points">
        <li>
          <span class="auth-dot"><Workflow :size="15" :stroke-width="1.7" /></span>
          <div>
            <p class="auth-point-title">会话随取随续</p>
            <p class="auth-point-sub">分支、审批、改问重发，跑一半停下来也不会丢进度</p>
          </div>
        </li>
        <li>
          <span class="auth-dot"><Paperclip :size="15" :stroke-width="1.7" /></span>
          <div>
            <p class="auth-point-title">文件拖进来就能讨论</p>
            <p class="auth-point-sub">上下文以文件形式进出沙箱，产出的文件可一键下载</p>
          </div>
        </li>
        <li>
          <span class="auth-dot"><MessageSquareText :size="15" :stroke-width="1.7" /></span>
          <div>
            <p class="auth-point-title">自己的数据自己看</p>
            <p class="auth-point-sub">会话与模型密钥按账号隔离，密钥加密保存</p>
          </div>
        </li>
      </ul>

      <p class="auth-brand-foot">Minimal &amp; Direct — 只做有用的东西</p>
    </aside>

    <!-- 右侧表单卡片 -->
    <section class="auth-flex auth-panel-wrap">
      <div class="auth-card">
        <div class="auth-brand-sm">
          <span class="auth-logo auth-logo-sm"><Bird :size="17" :stroke-width="1.7" /></span>
          <span class="text-ui font-medium text-ink">PigeonAgent</span>
        </div>

        <div
          v-if="mode !== 'verify'"
          class="auth-tabs"
          role="tablist"
        >
          <button
            type="button"
            :class="['auth-tab', mode === 'login' ? 'auth-tab-active' : '']"
            @click="switchTo('login')"
          >
            登录
          </button>
          <button
            type="button"
            :class="['auth-tab', mode === 'register' ? 'auth-tab-active' : '']"
            @click="switchTo('register')"
          >
            注册
          </button>
        </div>

        <Transition name="auth-page" mode="out-in">
          <div :key="mode" class="auth-lead">
            <p class="auth-lead-title">{{ heading.title }}</p>
            <p class="auth-lead-sub">
              {{ mode === "verify" ? `验证码已发送到 ${email}` : heading.sub }}
            </p>
          </div>
        </Transition>

          <Transition name="auth-page" mode="out-in">
          <form ref="formEl" :key="mode" class="auth-form" @submit.prevent="submit">
            <label v-if="mode !== 'verify'" class="auth-row">
              <span class="field-label">邮箱</span>
              <input
                v-model="email"
                class="auth-input"
                type="email"
                name="email"
                autocomplete="email"
                placeholder="you@example.com"
                required
              />
            </label>

            <label v-if="mode !== 'verify'" class="auth-row">
              <span class="field-label">
                密码
                <span v-if="mode === 'login'" class="text-faint">（忘记密码请联系管理员重置）</span>
              </span>
              <div class="relative">
                <input
                  v-model="password"
                  class="auth-input auth-input-eye"
                  :type="showPassword ? 'text' : 'password'"
                  name="password"
                  :autocomplete="mode === 'register' ? 'new-password' : 'current-password'"
                  placeholder="至少 8 位"
                  :minlength="mode === 'register' ? 8 : undefined"
                  required
                />
                <button
                  type="button"
                  class="auth-eye"
                  :aria-label="showPassword ? '隐藏密码' : '显示密码'"
                  @click="showPassword = !showPassword"
                >
                  <component :is="showPassword ? EyeOff : Eye" :size="15" :stroke-width="1.7" />
                </button>
              </div>
            </label>

            <label v-if="mode === 'register'" class="auth-row">
              <span class="field-label">昵称 <span class="text-faint">（可选）</span></span>
              <input
                v-model="displayName"
                class="auth-input"
                name="nickname"
                autocomplete="nickname"
                maxlength="64"
                placeholder="展示名"
              />
            </label>

            <div v-if="mode === 'verify'" class="auth-row">
              <span class="field-label">6 位验证码</span>
              <input
                class="auth-input font-mono text-center tracking-[0.55em]"
                inputmode="numeric"
                autocomplete="one-time-code"
                placeholder="000000"
                :value="code"
                @input="onCodeInput"
              />
            </div>

            <Transition name="auth-hint">
              <p v-if="hint" class="auth-hint ok">
                <MailCheck :size="14" :stroke-width="1.7" />{{ hint }}
              </p>
            </Transition>

            <button class="auth-submit" :disabled="busy">
              <LoaderCircle v-if="busy" :size="15" class="animate-spin" />
              <span v-if="mode === 'login'">登录</span>
              <span v-else-if="mode === 'register'">创建账号</span>
              <span v-else>验证并进入</span>
            </button>

            <div v-if="mode === 'verify'" class="auth-foot">
              <button type="button" @click="backToLogin">返回登录</button>
              <button type="button" :disabled="resendIn > 0" @click="resend">
                {{ resendIn > 0 ? `${resendIn}s 后可重发` : "重新发送" }}
              </button>
            </div>
            <p v-else-if="mode === 'register'" class="auth-foot auth-foot-one">
              密码至少 8 位，会被 bcrypt 加密保存；模型密钥同样只存密文
            </p>
          </form>
        </Transition>
      </div>

      <p class="auth-legal">登录即视为同意按会话粒度保存你的数据</p>
    </section>
  </div>
</template>

<style scoped>
.auth-flex {
  display: flex;
  flex: 1;
  height: 100%;
  min-height: 0;
}

/* ---------------------------------------------------------------- 左品牌 */

.auth-brand {
  display: flex;
  flex-direction: column;
  width: 42%;
  min-width: 340px;
  padding: 44px 48px;
  border-right: 1px solid var(--hair);
  background: var(--pane);
}

.auth-brand-head {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.auth-logo {
  display: grid;
  place-items: center;
  width: 42px;
  height: 42px;
  border-radius: var(--radius-control);
  background: var(--ink);
  color: var(--canvas);
}

.auth-title {
  margin-top: 12px;
  font-size: var(--text-display);
  font-weight: 550;
  letter-spacing: -0.02em;
  color: var(--ink);
}

.auth-sub {
  font-size: var(--text-ui);
  color: var(--muted);
}

.auth-deco {
  width: 280px;
  margin-top: 28px;
  color: color-mix(in srgb, var(--accent) 45%, transparent);
}

.auth-points {
  list-style: none;
  margin: 20px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 20px;
  max-width: 340px;
}

.auth-dot {
  display: grid;
  place-items: center;
  flex: none;
  width: 34px;
  height: 34px;
  border: 1px solid var(--hair);
  border-radius: var(--radius-control);
  background: var(--canvas);
  color: var(--muted);
}

.auth-points li {
  display: flex;
  gap: 12px;
}

.auth-point-title {
  font-size: var(--text-ui);
  font-weight: 550;
  color: var(--ink);
}

.auth-point-sub {
  margin-top: 2px;
  font-size: var(--text-meta);
  color: var(--faint);
}

.auth-brand-foot {
  margin-top: auto;
  padding-top: 24px;
  font-size: var(--text-micro);
  color: var(--faint);
}

/* ---------------------------------------------------------------- 右侧 */

.auth-panel-wrap {
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.auth-card {
  width: 100%;
  max-width: 356px;
  border: 1px solid var(--hair);
  border-radius: var(--radius-float);
  background: var(--surface);
  padding: 28px 30px;
}

.auth-brand-sm {
  display: none;
  align-items: center;
  gap: 10px;
  margin-bottom: 18px;
}

.auth-logo-sm {
  width: 28px;
  height: 28px;
}

.auth-tabs {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 4px;
  padding: 3px;
  border: 1px solid var(--hair);
  border-radius: var(--radius-control);
  background: var(--inset);
  margin-bottom: 22px;
}

.auth-tab {
  height: 27px;
  border: 1px solid transparent;
  border-radius: calc(var(--radius-control) - 2px);
  background: transparent;
  font-size: var(--text-meta);
  color: var(--faint);
  cursor: pointer;
  transition:
    background-color var(--dur-1) var(--ease-out),
    color var(--dur-1) var(--ease-out),
    border-color var(--dur-1) var(--ease-out);
}

.auth-tab:hover {
  color: var(--ink);
}

.auth-tab-active {
  background: var(--canvas);
  border-color: var(--hair);
  color: var(--ink);
}

.auth-lead {
  margin-bottom: 20px;
}

.auth-lead-title {
  font-size: 22px;
  font-weight: 550;
  letter-spacing: -0.01em;
  color: var(--ink);
}

.auth-lead-sub {
  margin-top: 4px;
  font-size: var(--text-meta);
  color: var(--faint);
  word-break: break-all;
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.auth-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.auth-input {
  width: 100%;
  height: 36px;
  padding: 0 12px;
  border-radius: var(--radius-control);
  border: 1px solid var(--hair);
  background: var(--canvas);
  color: var(--ink);
  font-size: var(--text-ui);
  outline: none;
  transition: border-color var(--dur-1) var(--ease-out);
}

.auth-input::placeholder {
  color: var(--faint);
}

.auth-input:hover {
  border-color: color-mix(in srgb, var(--ink) 18%, var(--hair));
}

.auth-input:focus {
  border-color: color-mix(in srgb, var(--accent) 60%, var(--hair));
}

.auth-input-eye {
  padding-right: 36px;
}

.auth-eye {
  position: absolute;
  right: 4px;
  top: 50%;
  transform: translateY(-50%);
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border: none;
  border-radius: var(--radius-control);
  background: transparent;
  color: var(--faint);
  cursor: pointer;
}

.auth-eye:hover {
  color: var(--ink);
}

.auth-submit {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 38px;
  margin-top: 2px;
  border: 1px solid transparent;
  border-radius: var(--radius-control);
  background: var(--ink);
  color: var(--canvas);
  font-size: var(--text-ui);
  font-weight: 500;
  cursor: pointer;
  transition:
    background-color var(--dur-1) var(--ease-out),
    opacity var(--dur-1) var(--ease-out);
}

.auth-submit:hover:not(:disabled) {
  background: color-mix(in srgb, var(--ink) 86%, var(--canvas));
}

.auth-submit:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.auth-foot {
  display: flex;
  justify-content: space-between;
  font-size: var(--text-micro);
  color: var(--faint);
}

.auth-foot-one {
  justify-content: center;
  text-align: center;
}

.auth-foot button {
  border: none;
  background: none;
  padding: 0;
  font-size: var(--text-micro);
  color: var(--faint);
  cursor: pointer;
  transition: color var(--dur-1) var(--ease-out);
}

.auth-foot button:hover:not(:disabled) {
  color: var(--ink);
}

.auth-foot button:disabled {
  cursor: not-allowed;
}

.auth-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-meta);
}

.auth-hint.ok {
  color: var(--ok);
}

.auth-legal {
  margin-top: 18px;
  font-size: var(--text-micro);
  color: var(--faint);
}

/* ---------------------------------------------------------------- 动效 */

.auth-page-enter-active,
.auth-page-leave-active {
  transition:
    opacity var(--dur-2) var(--ease-out),
    transform var(--dur-2) var(--ease-out);
}

.auth-page-enter-from {
  opacity: 0;
  transform: translateY(6px);
}

.auth-page-leave-to {
  opacity: 0;
  transform: translateY(-6px);
}

.auth-hint-enter-active {
  transition: opacity var(--dur-2) var(--ease-out);
}

.auth-hint-enter-from {
  opacity: 0;
}

@media (max-width: 767px) {
  .auth-brand {
    display: none;
  }

  .auth-brand-sm {
    display: flex;
  }
}
</style>
