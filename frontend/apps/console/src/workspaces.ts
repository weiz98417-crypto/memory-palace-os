import type { Component } from 'vue'
import { ChatDotRound, Collection, Document, Medal, Monitor, Odometer, OfficeBuilding, Promotion, Setting, Stamp, Tickets, View, WarningFilled } from '@element-plus/icons-vue'

export interface ConsoleWorkspace {
  key: string
  label: string
  icon: Component
  path: string
  endpoint: string
  roles: Array<'manager' | 'admin'>
  ownerTicket: 'F13a' | 'F13b' | 'F13c' | 'F13d'
}

export const CONSOLE_WORKSPACES: ConsoleWorkspace[] = [
  { key: 'dashboard', label: '指挥中心', icon: Odometer, path: '/', endpoint: '/scenic/snapshot', roles: ['manager', 'admin'], ownerTicket: 'F13a' },
  { key: 'events', label: '事件处置', icon: WarningFilled, path: '/events', endpoint: '/admin/events?limit=200', roles: ['manager', 'admin'], ownerTicket: 'F13b' },
  { key: 'sessions', label: '消息与会话', icon: ChatDotRound, path: '/sessions', endpoint: '/sessions/?limit=200', roles: ['manager', 'admin'], ownerTicket: 'F13b' },
  { key: 'tasks', label: '任务与审批', icon: Tickets, path: '/tasks', endpoint: '/admin/tasks?limit=200', roles: ['manager', 'admin'], ownerTicket: 'F13b' },
  { key: 'approvals', label: '审批中心', icon: Stamp, path: '/approvals', endpoint: '/admin/approvals?limit=200', roles: ['manager', 'admin'], ownerTicket: 'F13b' },
  { key: 'actions', label: '推送与动作日志', icon: Promotion, path: '/actions', endpoint: '/admin/push_logs?limit=200', roles: ['manager', 'admin'], ownerTicket: 'F13b' },
  { key: 'knowledge', label: '组织记忆', icon: Collection, path: '/knowledge', endpoint: '/admin/knowledge?limit=200', roles: ['manager', 'admin'], ownerTicket: 'F13c' },
  { key: 'experience', label: '专家经验', icon: Medal, path: '/experience', endpoint: '/admin/experience-cards?limit=200', roles: ['manager', 'admin'], ownerTicket: 'F13c' },
  { key: 'watcher', label: '鹰眼巡检', icon: View, path: '/watcher', endpoint: '/admin/watcher/findings?limit=200', roles: ['manager', 'admin'], ownerTicket: 'F13c' },
  { key: 'sops', label: 'SOP 中心', icon: Document, path: '/sops', endpoint: '/admin/sops', roles: ['manager', 'admin'], ownerTicket: 'F13c' },
  { key: 'management', label: '用户与场地', icon: OfficeBuilding, path: '/management', endpoint: '/admin/users', roles: ['admin'], ownerTicket: 'F13d' },
  { key: 'settings', label: '系统设置', icon: Setting, path: '/settings', endpoint: '/admin/settings', roles: ['manager', 'admin'], ownerTicket: 'F13d' },
  { key: 'diagnostics', label: '运维诊断', icon: Monitor, path: '/diagnostics', endpoint: '/admin/diagnostics', roles: ['admin'], ownerTicket: 'F13d' },
]

export function visibleWorkspaces(role: string | undefined | null): ConsoleWorkspace[] {
  const normalized = role === 'admin' ? 'admin' : role === 'manager' ? 'manager' : null
  if (!normalized) return []
  return CONSOLE_WORKSPACES.filter((workspace) => workspace.roles.includes(normalized))
}

export function workspaceByKey(key: string): ConsoleWorkspace | null {
  return CONSOLE_WORKSPACES.find((workspace) => workspace.key === key) || null
}
