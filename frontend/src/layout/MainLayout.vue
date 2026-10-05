<script setup>
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { changePassword } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import { PASSWORD_TIP, passwordRule } from '@/utils/password'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const menuItems = computed(() => {
  const items = [{ path: '/dashboard', title: '首页', icon: 'HomeFilled' }]
  const system = []
  if (auth.hasPerm('system:user:manage')) system.push({ path: '/system/users', title: '用户管理' })
  if (auth.hasPerm('system:dept:manage')) system.push({ path: '/system/depts', title: '部门管理' })
  if (auth.hasPerm('system:role:manage')) system.push({ path: '/system/roles', title: '角色权限' })
  if (system.length) {
    items.push({ title: '系统管理', icon: 'Setting', children: system })
  }
  return items
})

const activeMenu = computed(() => route.path)

const pwdDialog = ref(false)
const pwdFormRef = ref()
const pwdForm = reactive({ old_password: '', new_password: '', confirm: '' })
const pwdRules = {
  old_password: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    passwordRule,
  ],
  confirm: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (rule, value, callback) =>
        value === pwdForm.new_password ? callback() : callback(new Error('两次输入不一致')),
      trigger: 'blur',
    },
  ],
}

function openPwdDialog() {
  Object.assign(pwdForm, { old_password: '', new_password: '', confirm: '' })
  pwdDialog.value = true
}

async function submitPassword() {
  await pwdFormRef.value.validate()
  await changePassword({ old_password: pwdForm.old_password, new_password: pwdForm.new_password })
  ElMessage.success('密码修改成功,请重新登录')
  pwdDialog.value = false
  doLogout()
}

function doLogout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="logo">水司业务管理系统</div>
      <el-menu
        :default-active="activeMenu"
        router
        background-color="#001529"
        text-color="#c8c9cc"
        active-text-color="#ffffff"
        class="menu"
      >
        <template v-for="item in menuItems" :key="item.title">
          <el-sub-menu v-if="item.children" :index="item.title">
            <template #title>
              <el-icon><component :is="item.icon" /></el-icon>
              {{ item.title }}
            </template>
            <el-menu-item v-for="child in item.children" :key="child.path" :index="child.path">
              {{ child.title }}
            </el-menu-item>
          </el-sub-menu>
          <el-menu-item v-else :index="item.path">
            <el-icon><component :is="item.icon" /></el-icon>
            {{ item.title }}
          </el-menu-item>
        </template>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="header-title">{{ route.meta.title || '' }}</div>
        <el-dropdown>
          <span class="user-name">
            {{ auth.user?.real_name || auth.user?.username }}
            <el-icon><ArrowDown /></el-icon>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="openPwdDialog">修改密码</el-dropdown-item>
              <el-dropdown-item divided @click="doLogout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>

  <el-dialog v-model="pwdDialog" title="修改密码" width="420px">
    <el-alert type="info" show-icon :closable="false" :title="PASSWORD_TIP" class="pwd-tip" />
    <el-form ref="pwdFormRef" :model="pwdForm" :rules="pwdRules" label-width="90px">
      <el-form-item label="原密码" prop="old_password">
        <el-input v-model="pwdForm.old_password" type="password" show-password />
      </el-form-item>
      <el-form-item label="新密码" prop="new_password">
        <el-input v-model="pwdForm.new_password" type="password" show-password />
      </el-form-item>
      <el-form-item label="确认新密码" prop="confirm">
        <el-input v-model="pwdForm.confirm" type="password" show-password />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="pwdDialog = false">取消</el-button>
      <el-button type="primary" @click="submitPassword">确定</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.pwd-tip {
  margin-bottom: 16px;
}
.layout {
  height: 100%;
}
.aside {
  background-color: #001529;
}
.logo {
  height: 60px;
  line-height: 60px;
  text-align: center;
  color: #fff;
  font-size: 16px;
  font-weight: 600;
  border-bottom: 1px solid rgba(255, 255, 255, 0.1);
}
.menu {
  border-right: none;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #e8e8e8;
}
.header-title {
  font-size: 16px;
  font-weight: 600;
}
.user-name {
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #333;
}
.main {
  background: #f0f2f5;
  padding: 16px;
}
</style>
