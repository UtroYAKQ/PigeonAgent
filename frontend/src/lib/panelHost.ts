import type { InjectionKey } from 'vue'

/** 只有聊天页渲染了右侧预览面板；分享/后台没有宿主，预览入口不该出现。 */
export const PANEL_HOST_KEY: InjectionKey<boolean> = Symbol('panel-host')