<script setup lang="ts">
import { LogOut } from "lucide-vue-next";
import { computed } from "vue";

import type { UserRead } from "../../types";

const props = defineProps<{ user: UserRead | null }>();

const emit = defineEmits<{
  (event: "logout"): void;
}>();

const displayName = computed(
  () => props.user?.display_name?.trim() || props.user?.email.split("@")[0] || "未登录",
);
const initial = computed(() => displayName.value.charAt(0).toUpperCase());
const roleLabel = computed(() => (props.user?.is_admin ? "管理员" : "成员"));
const joinedAt = computed(() => {
  const raw = props.user?.created_at;
  const date = raw ? new Date(raw) : null;
  return date && !Number.isNaN(date.getTime())
    ? date.toLocaleDateString("zh-CN", { year: "numeric", month: "long", day: "numeric" })
    : "—";
});
</script>

<template>
  <div class="h-full overflow-y-auto px-5 py-5">
    <div class="flex max-w-xl items-center gap-3.5">
      <span
        class="grid size-12 shrink-0 place-items-center rounded-full border border-hair bg-canvas text-body font-medium text-muted"
      >
        {{ initial }}
      </span>
      <div class="min-w-0">
        <p class="truncate text-body font-medium text-ink">{{ displayName }}</p>
        <p class="truncate text-meta text-faint">{{ user?.email }}</p>
      </div>
      <button class="btn btn-danger ml-auto shrink-0 border" @click="emit('logout')">
        <LogOut :size="13" :stroke-width="1.7" />
        退出登录
      </button>
    </div>

    <dl class="mt-7 max-w-xl border-t border-hair text-ui">
      <div class="flex items-baseline gap-4 border-b border-hair py-3">
        <dt class="w-20 shrink-0 text-meta text-faint">昵称</dt>
        <dd class="min-w-0 flex-1 truncate text-ink">{{ user?.display_name || "未设置" }}</dd>
      </div>
      <div class="flex items-baseline gap-4 border-b border-hair py-3">
        <dt class="w-20 shrink-0 text-meta text-faint">账号角色</dt>
        <dd class="min-w-0 flex-1 text-ink">{{ roleLabel }}</dd>
      </div>
      <div class="flex items-baseline gap-4 border-b border-hair py-3">
        <dt class="w-20 shrink-0 text-meta text-faint">加入时间</dt>
        <dd class="min-w-0 flex-1 text-ink">{{ joinedAt }}</dd>
      </div>
    </dl>

    <p class="mt-5 max-w-xl text-meta leading-5 text-faint">
      会话、分组与模型密钥按账号隔离；模型密钥只以密文形式保存在服务端。
    </p>
  </div>
</template>
