import { createRouter, createWebHistory } from 'vue-router'
import CommandCenterView from './views/CommandCenterView.vue'

export const router = createRouter({
  history: createWebHistory('/admin/'),
  routes: [
    { path: '/', component: CommandCenterView },
    { path: '/command-center', component: CommandCenterView },
    { path: '/:pathMatch(.*)*', component: CommandCenterView },
  ],
})