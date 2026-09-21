import { createRouter, createWebHistory } from 'vue-router'
import CommandCenterView from './views/CommandCenterView.vue'
import ActionLogWorkspaceView from './views/ActionLogWorkspaceView.vue'
import KnowledgeWorkspaceView from './views/KnowledgeWorkspaceView.vue'
import ExperienceWorkspaceView from './views/ExperienceWorkspaceView.vue'
import WatcherWorkspaceView from './views/WatcherWorkspaceView.vue'
import SopWorkspaceView from './views/SopWorkspaceView.vue'
import ApprovalWorkspaceView from './views/ApprovalWorkspaceView.vue'
import EventWorkspaceView from './views/EventWorkspaceView.vue'
import SessionWorkspaceView from './views/SessionWorkspaceView.vue'
import TaskWorkspaceView from './views/TaskWorkspaceView.vue'
import WorkspaceView from './views/WorkspaceView.vue'
import { CONSOLE_WORKSPACES } from './workspaces'

const workspaceRoutes = CONSOLE_WORKSPACES
  .filter((workspace) => !['dashboard', 'events', 'sessions', 'tasks', 'approvals', 'actions', 'knowledge', 'experience', 'watcher', 'sops'].includes(workspace.key))
  .map((workspace) => ({
    path: workspace.path,
    component: WorkspaceView,
    props: { workspaceKey: workspace.key },
  }))

export const router = createRouter({
  history: createWebHistory('/admin/'),
  routes: [
    { path: '/', component: CommandCenterView },
    { path: '/command-center', component: CommandCenterView },
    { path: '/events', component: EventWorkspaceView },
    { path: '/sessions', component: SessionWorkspaceView },
    { path: '/tasks', component: TaskWorkspaceView },
    { path: '/approvals', component: ApprovalWorkspaceView },
    { path: '/actions', component: ActionLogWorkspaceView },
    { path: '/knowledge', component: KnowledgeWorkspaceView },
    { path: '/experience', component: ExperienceWorkspaceView },
    { path: '/watcher', component: WatcherWorkspaceView },
    { path: '/sops', component: SopWorkspaceView },
    ...workspaceRoutes,
    { path: '/:pathMatch(.*)*', component: CommandCenterView },
  ],
})
