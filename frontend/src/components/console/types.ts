import type { Component } from 'vue'

export interface ConsoleNavItem {
  key: string
  label: string
  group: string
  icon: Component
  count?: number
}

export interface ConsoleCommandItem {
  key: string
  label: string
  group: string
  icon?: Component
}
