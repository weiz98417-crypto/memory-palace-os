import { createRouter, createWebHistory } from 'vue-router'
import EvaluationOperationsView from './views/EvaluationOperationsView.vue'
import HomeView from './views/HomeView.vue'
import ScenicOperationsView from './views/ScenicOperationsView.vue'

export const router = createRouter({
  history: createWebHistory('/operations/'),
  routes: [
    { path: '/', component: HomeView },
    { path: '/scenic', component: ScenicOperationsView },
    { path: '/evaluation', component: EvaluationOperationsView },
    { path: '/:pathMatch(.*)*', component: HomeView },
  ],
})