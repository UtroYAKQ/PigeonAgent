import type { Component } from 'vue'
import {
  Box,
  Boxes,
  Coins,
  File,
  Globe2,
  Image,
  LayoutDashboard,
  Mail,
  MessagesSquare,
  ScrollText,
  Search,
  SlidersHorizontal,
  UsersRound,
} from '@lucide/vue'

import AuditLogPanel from '@/components/admin/AuditLogPanel.vue'
import ConfigSettingsPanel from '@/components/admin/ConfigSettingsPanel.vue'
import ImageModelManagerPanel from '@/components/admin/ImageModelManagerPanel.vue'
import ModelManagerPanel from '@/components/admin/ModelManagerPanel.vue'
import PlatformOverviewPanel from '@/components/admin/PlatformOverviewPanel.vue'
import SessionManagementPanel from '@/components/admin/SessionManagementPanel.vue'
import UsagePanel from '@/components/admin/UsagePanel.vue'
import UserManagementPanel from '@/components/admin/UserManagementPanel.vue'
import type { AdminConfigCategory } from '@/components/admin/config'

export type AdminSectionKey =
  | 'overview'
  | 'users'
  | 'sessions'
  | 'usage'
  | 'logs'
  | 'site'
  | 'models'
  | 'image-models'
  | 'features'
  | 'deepseek'
  | 'sandbox'
  | 'email'
  | 'files'
  | 'logging'

export type AdminSectionGroup = '平台运营' | '平台配置'

export interface AdminSection {
  key: AdminSectionKey
  group: AdminSectionGroup
  label: string
  title: string
  description: string
  icon: Component
  panel: Component
  panelProps?: { category: AdminConfigCategory }
}

export const ADMIN_SECTIONS: AdminSection[] = [
  {
    key: 'overview',
    group: '平台运营',
    label: '概览',
    title: '平台概览',
    description: '用户、会话与运行状态，以及最近的管理操作。',
    icon: LayoutDashboard,
    panel: PlatformOverviewPanel,
  },
  {
    key: 'users',
    group: '平台运营',
    label: '用户管理',
    title: '用户管理',
    description: '查看平台账号，调整成员角色与启用状态。',
    icon: UsersRound,
    panel: UserManagementPanel,
  },
  {
    key: 'sessions',
    group: '平台运营',
    label: '会话管理',
    title: '会话管理',
    description: '查看全平台会话，归档或恢复历史对话。',
    icon: MessagesSquare,
    panel: SessionManagementPanel,
  },
  {
    key: 'usage',
    group: '平台运营',
    label: '用量与积分',
    title: '用量与积分',
    description: '每轮对话的 token 用量与扣分，以及充值、出图等全部积分流水。',
    icon: Coins,
    panel: UsagePanel,
  },
  {
    key: 'logs',
    group: '平台运营',
    label: '操作日志',
    title: '操作日志',
    description: '所有用户 HTTP 操作与管理员变更，包含请求参数和返回结果；敏感值已脱敏。',
    icon: ScrollText,
    panel: AuditLogPanel,
  },
  {
    key: 'site',
    group: '平台配置',
    label: '站点',
    title: '站点信息',
    description: '站点名称、简介和 Logo 会通过公开接口下发给登录页与工作区。',
    icon: Globe2,
    panel: ConfigSettingsPanel,
    panelProps: { category: 'site' },
  },
  {
    key: 'models',
    group: '平台配置',
    label: '模型管理',
    title: '模型管理',
    description: '模型对所有成员共享。只有勾选的思考挡位会出现在输入框旁边。',
    icon: Boxes,
    panel: ModelManagerPanel,
  },
  {
    key: 'image-models',
    group: '平台配置',
    label: '图片模型',
    title: '图片模型',
    description: '对话里生成图片时使用的模型。配置后助手会自动获得出图能力，未配置则不显示该工具。',
    icon: Image,
    panel: ImageModelManagerPanel,
  },
  {
    key: 'features',
    group: '平台配置',
    label: '功能开关',
    title: '功能开关',
    description: '平台级总闸。关闭后即使凭证或模型已配置，也不会把对应工具下发给模型。',
    icon: SlidersHorizontal,
    panel: ConfigSettingsPanel,
    panelProps: { category: 'features' },
  },
  {
    key: 'deepseek',
    group: '平台配置',
    label: '联网搜索',
    title: '联网搜索',
    description: 'DeepSeek Search & Fetch 凭证。配置后，输入框的联网开关即可使用。',
    icon: Search,
    panel: ConfigSettingsPanel,
    panelProps: { category: 'deepseek' },
  },
  {
    key: 'sandbox',
    group: '平台配置',
    label: '沙箱',
    title: '沙箱',
    description: 'e2b 兼容沙箱的连接信息与回收策略；未配置时使用本地临时工作区。',
    icon: Box,
    panel: ConfigSettingsPanel,
    panelProps: { category: 'sandbox' },
  },
  {
    key: 'email',
    group: '平台配置',
    label: '邮箱',
    title: '邮箱',
    description: 'SMTP 发件与注册验证码设置。密钥类字段会加密后写入数据库。',
    icon: Mail,
    panel: ConfigSettingsPanel,
    panelProps: { category: 'email' },
  },
  {
    key: 'files',
    group: '平台配置',
    label: '文件',
    title: '文件',
    description: '单文件大小上限，服务端直传与预签名上传共用这条限制。',
    icon: File,
    panel: ConfigSettingsPanel,
    panelProps: { category: 'files' },
  },
  {
    key: 'logging',
    group: '平台配置',
    label: '日志',
    title: '操作日志配置',
    description: '异步队列、采集范围、体积上限和保留期；修改后立即生效。',
    icon: ScrollText,
    panel: ConfigSettingsPanel,
    panelProps: { category: 'logging' },
  },
]

export const ADMIN_GROUP_ORDER: AdminSectionGroup[] = ['平台运营', '平台配置']
