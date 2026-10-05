<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const formRef = ref()
const loading = ref(false)
// 记住用户名:只记住用户名,密码不落盘
const savedUsername = localStorage.getItem('remembered_username') || ''
const rememberName = ref(!!savedUsername)
const form = reactive({ username: savedUsername, password: '' })
const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function submit() {
  await formRef.value.validate()
  if (rememberName.value) {
    localStorage.setItem('remembered_username', form.username)
  } else {
    localStorage.removeItem('remembered_username')
  }
  loading.value = true
  try {
    await auth.login(form)
    // 用初始密码登录的用户,先跳去修改密码
    router.push(auth.user?.must_change_password ? '/change-password' : route.query.redirect || '/')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <el-card class="login-card">
      <h2 class="title">水司业务管理系统</h2>
      <el-form ref="formRef" :model="form" :rules="rules" size="large" @keyup.enter="submit">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名">
            <template #prefix><el-icon><User /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="密码">
            <template #prefix><el-icon><Lock /></el-icon></template>
          </el-input>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="rememberName">记住用户名</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" class="login-btn" :loading="loading" @click="submit">
            登 录
          </el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<style scoped>
.login-page {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1f6fb2 0%, #0b2e4f 100%);
}
.login-card {
  width: 380px;
  padding: 10px 10px 0;
}
.title {
  text-align: center;
  margin: 10px 0 24px;
  color: #303133;
}
.login-btn {
  width: 100%;
}
</style>
