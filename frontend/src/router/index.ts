import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/qa',
    },
    {
      path: '/qa',
      name: 'qa',
      component: () => import('@/components/pages/QAPage.vue'),
      meta: { title: '智能问答' },
    },
    {
      path: '/agent',
      name: 'agent',
      component: () => import('@/components/pages/AgentPage.vue'),
      meta: { title: '智能分析' },
    },
    {
      path: '/library',
      name: 'library',
      component: () => import('@/components/pages/LibraryPage.vue'),
      meta: { title: '论文库' },
    },
    {
      path: '/summary',
      name: 'summary',
      component: () => import('@/components/pages/SummaryPage.vue'),
      meta: { title: '摘要 & 综述' },
    },
    {
      path: '/citations',
      name: 'citations',
      component: () => import('@/components/pages/CitationsPage.vue'),
      meta: { title: '引用关系' },
    },
    {
      path: '/data',
      name: 'data',
      component: () => import('@/components/pages/DataPage.vue'),
      meta: { title: '数据管理' },
    },
    {
      path: '/system',
      name: 'system',
      component: () => import('@/components/pages/SystemPage.vue'),
      meta: { title: '系统设置' },
    },
    {
      path: '/help',
      name: 'help',
      component: () => import('@/components/pages/HelpPage.vue'),
      meta: { title: '帮助' },
    },
  ],
})

router.afterEach((to) => {
  document.title = `${to.meta.title || 'Paper Assistant'} — Paper Assistant`
})

export default router
