import { createRouter, createWebHistory } from 'vue-router'
import FieldTaskView from './views/FieldTaskView.vue'

export const router = createRouter({
  history: createWebHistory('/assistant/'),
  routes: [
    { path: '/', component: FieldTaskView },
    { path: '/:pathMatch(.*)*', component: FieldTaskView },
  ],
})