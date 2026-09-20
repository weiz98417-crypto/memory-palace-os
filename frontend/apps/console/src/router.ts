import { createRouter, createWebHistory } from 'vue-router'
import CommandCenterView from './views/CommandCenterView.vue'
import WorkspaceView from './views/WorkspaceView.vue'
import { CONSOLE_WORKSPACES } from './workspaces'

const workspaceRoutes = CONSOLE_WORKSPACES
  .filter((workspace) => workspace.key !== 'dashboard')
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
    ...workspaceRoutes,
    { path: '/:pathMatch(.*)*', component: CommandCenterView },
  ],
})
