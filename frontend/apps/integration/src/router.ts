import { createRouter, createWebHistory } from 'vue-router'
import IntegrationView from './views/IntegrationView.vue'

export const router = createRouter({
  history: createWebHistory('/simulator/wecom/'),
  routes: [
    { path: '/', component: IntegrationView },
    { path: '/:pathMatch(.*)*', component: IntegrationView },
  ],
})