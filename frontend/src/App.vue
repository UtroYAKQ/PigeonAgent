<script setup lang="ts">
import { onMounted, watch } from 'vue'
import type { RouteLocationNormalizedLoaded } from 'vue-router'
import { RouterView, useRoute, useRouter } from 'vue-router'
import { Toaster } from 'vue-sonner'

import { TooltipProvider } from '@/components/ui/tooltip'
import { useAuthStore } from '@/stores/auth'
import { useUiStore } from '@/stores/ui'

const auth = useAuthStore()
const ui = useUiStore()
const router = useRouter()
const route = useRoute()
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches

onMounted(() => {
  void auth.init()
})

watch(
  () => auth.isAuthenticated,
  (authenticated) => {
    // 被踢回登录页时不记住当前路径：换账号登录就会把人送进上个账号的会话
    if (!authenticated && !route.meta.guestOnly && !route.meta.public) {
      void router.replace({ name: 'login' })
    }
  },
)

// 同一界面的不同路由共用一个 key，避免切换时整页卸载重建
function viewKey(viewRoute: RouteLocationNormalizedLoaded): string {
  if (viewRoute.name === 'login' || viewRoute.name === 'register') return 'auth'
  if (viewRoute.name === 'new-chat' || viewRoute.name === 'chat') return 'chat'
  return viewRoute.matched[0]?.path ?? viewRoute.path
}

</script>

<template>
  <!-- 触摸/鼠标点击带来的焦点不弹提示，否则手机打开抽屉时第一个可聚焦的标签会闪一下标题 -->
  <TooltipProvider :ignore-non-keyboard-focus="true">
    <RouterView v-slot="{ Component, route: viewRoute }">
      <Transition
        name="page-flight"
        mode="out-in"
        :duration="reduceMotion ? 0 : { enter: 240, leave: 160 }"
      >
        <component
          :is="Component"
          :key="viewKey(viewRoute)"
        />
      </Transition>
    </RouterView>
  </TooltipProvider>
  <Toaster
    position="top-center"
    :duration="3200"
    :theme="ui.isDark ? 'dark' : 'light'"
    :toast-options="{
      style: {
        background: 'var(--popover)',
        color: 'var(--popover-foreground)',
        border: '1px solid var(--border)',
        boxShadow: 'none',
        fontFamily: 'var(--font-sans)',
        fontSize: '13.5px',
        borderRadius: '10px',
      },
    }"
  />
</template>
