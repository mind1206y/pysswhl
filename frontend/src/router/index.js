import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import MainLayout from '@/layout/MainLayout.vue'
import Login from '@/views/Login.vue'
import ChangePassword from '@/views/ChangePassword.vue'
import Dashboard from '@/views/Dashboard.vue'
import DeptManage from '@/views/system/DeptManage.vue'
import UserManage from '@/views/system/UserManage.vue'
import RoleManage from '@/views/system/RoleManage.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: Login, meta: { title: '登录' } },
    { path: '/change-password', component: ChangePassword, meta: { title: '修改初始密码' } },
    {
      path: '/',
      component: MainLayout,
      redirect: '/dashboard',
      children: [
        { path: 'dashboard', component: Dashboard, meta: { title: '首页' } },
        {
          path: 'system/users',
          component: UserManage,
          meta: { title: '用户管理', perm: 'system:user:manage' },
        },
        {
          path: 'system/depts',
          component: DeptManage,
          meta: { title: '部门管理', perm: 'system:dept:manage' },
        },
        {
          path: 'system/roles',
          component: RoleManage,
          meta: { title: '角色权限', perm: 'system:role:manage' },
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (to.path === '/login') {
    return true
  }
  if (!auth.token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  try {
    await auth.loadUser()
  } catch {
    auth.logout()
    return '/login'
  }
  // 使用初始密码登录的用户,先强制修改密码
  if (auth.user?.must_change_password && to.path !== '/change-password') {
    return '/change-password'
  }
  if (to.path === '/change-password' && !auth.user?.must_change_password) {
    return '/dashboard'
  }
  if (to.meta.perm && !auth.hasPerm(to.meta.perm)) {
    return '/dashboard'
  }
  return true
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} - 水司业务管理系统` : '水司业务管理系统'
})

export default router
