import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { MotionPlugin } from '@vueuse/motion'

import App from './App.vue'
import router from './router'
import { startHighlighter } from './lib/highlighter'
import '@fontsource-variable/noto-sans-sc'
import 'vue-sonner/style.css'
import 'markstream-vue/index.css'
import './assets/main.css'
import './styles/motion.css'

const app = createApp(App)

app.use(createPinia())
app.use(router)
app.use(MotionPlugin)
app.mount('#app')

// 空闲时先把 Shiki 暖起来，首个代码块出现时不用再等引擎和常见语言
if (typeof window.requestIdleCallback === 'function') {
  window.requestIdleCallback(startHighlighter)
} else {
  window.setTimeout(startHighlighter, 300)
}
