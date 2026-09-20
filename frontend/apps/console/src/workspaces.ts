export interface ConsoleWorkspace {
  key: string
  label: string
  icon: string
  path: string
  endpoint: string
  roles: Array<'manager' | 'admin'>
  ownerTicket: 'F13a' | 'F13b' | 'F13c' | 'F13d'
}

export const CONSOLE_WORKSPACES: ConsoleWorkspace[] = [
  { key: 'dashboard', label: '指挥中心', icon: '总', path: '/', endpoint: '/scenic/snapshot', roles: ['manager', 'admin'], ownerTicket: 'F13a' },
  { key: 'events', label: '事件处置', icon: '事', path: '/events', endpoint: '/admin/events?limit=200', roles: ['manager', 'admin'], ownerTicket: 'F13b' },
  { key: 'sessions', label: '消息与会话', icon: '会', path: '/sessions', endpoint: '/sessions/?limit=200', roles: ['manager', 'admin'], ownerTicket: 'F13b' },
  { key: 'tasks', label: '任务与审批', icon: '任', path: '/tasks', endpoint: '/admin/tasks?limit=200', roles: ['manager', 'admin'], ownerTicket: 'F13b' },
  { key: 'approvals', label: '审批中心', icon: '审', path: '/approvals', endpoint: '/admin/approvals?limit=200', roles: ['manager', 'admin'], ownerTicket: 'F13b' },
  { key: 'actions', label: '推送与动作日志', icon: '动', path: '/actions', endpoint: '/admin/push_logs?limit=200', roles: ['manager', 'admin'], ownerTicket: 'F13b' },
  { key: 'knowledge', label: '组织记忆', icon: '知', path: '/knowledge', endpoint: '/admin/knowledge?limit=200', roles: ['manager', 'admin'], ownerTicket: 'F13c' },
  { key: 'experience', label: '专家经验', icon: '经', path: '/experience', endpoint: '/admin/experience-cards?limit=200', roles: ['manager', 'admin'], ownerTicket: 'F13c' },
  { key: 'watcher', label: '鹰眼巡检', icon: '巡', path: '/watcher', endpoint: '/admin/watcher/findings?limit=200', roles: ['manager', 'admin'], ownerTicket: 'F13c' },
  { key: 'sops', label: 'SOP 中心', icon: 'S', path: '/sops', endpoint: '/admin/sops', roles: ['manager', 'admin'], ownerTicket: 'F13c' },
  { key: 'management', label: '用户与场地', icon: '管', path: '/management', endpoint: '/admin/users', roles: ['admin'], ownerTicket: 'F13d' },
  { key: 'settings', label: '系统设置', icon: '设', path: '/settings', endpoint: '/admin/settings', roles: ['manager', 'admin'], ownerTicket: 'F13d' },
  { key: 'diagnostics', label: '运维诊断', icon: '诊', path: '/diagnostics', endpoint: '/admin/diagnostics', roles: ['admin'], ownerTicket: 'F13d' },
]

export function visibleWorkspaces(role: string | undefined | null): ConsoleWorkspace[] {
  const normalized = role === 'admin' ? 'admin' : role === 'manager' ? 'manager' : null
  if (!normalized) return []
  return CONSOLE_WORKSPACES.filter((workspace) => workspace.roles.includes(normalized))
}

export function workspaceByKey(key: string): ConsoleWorkspace | null {
  return CONSOLE_WORKSPACES.find((workspace) => workspace.key === key) || null
}
