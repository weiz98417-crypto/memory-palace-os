import { createRouter, createWebHistory } from 'vue-router'
import CommandCenterView from './views/CommandCenterView.vue'
import EventWorkspaceView from './views/EventWorkspaceView.vue'
import SessionWorkspaceView from './views/SessionWorkspaceView.vue'
import WorkspaceView from './views/WorkspaceView.vue'
import { CONSOLE_WORKSPACES } from './workspaces'

const workspaceRoutes = CONSOLE_WORKSPACES
  .filter((workspace) => !['dashboard', 'events', 'sessions'].includes(workspace.key))
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
    ...workspaceRoutes,
    { path: '/:pathMatch(.*)*', component: CommandCenterView },
  ],
})
