import { describe, expect, it } from 'vitest'
import { CONSOLE_WORKSPACES, visibleWorkspaces, workspaceByKey } from './workspaces'

describe('console workspace registry', () => {
  it('keeps all legacy workspaces with stable distinct routes', () => {
    expect(CONSOLE_WORKSPACES).toHaveLength(13)
    expect(new Set(CONSOLE_WORKSPACES.map((item) => item.path)).size).toBe(13)
    expect(workspaceByKey('approvals')?.endpoint).toBe('/admin/approvals?limit=200')
  })

  it('hides admin-only workspaces from managers', () => {
    expect(visibleWorkspaces('manager').map((item) => item.key)).not.toContain('management')
    expect(visibleWorkspaces('manager').map((item) => item.key)).not.toContain('diagnostics')
    expect(visibleWorkspaces('admin')).toHaveLength(13)
    expect(visibleWorkspaces('operator')).toEqual([])
  })
})
