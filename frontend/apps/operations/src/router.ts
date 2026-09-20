import { createRouter, createWebHistory } from 'vue-router'
import EvaluationOperationsView from './views/EvaluationOperationsView.vue'
import ScenicOperationsView from './views/ScenicOperationsView.vue'

export const router = createRouter({
  history: createWebHistory('/operations/'),
  routes: [
    { path: '/', redirect: '/scenic' },
    { path: '/scenic', component: ScenicOperationsView },
    { path: '/evaluation', component: EvaluationOperationsView },
    { path: '/:pathMatch(.*)*', redirect: '/scenic' },
  ],
})
