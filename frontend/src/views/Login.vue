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
    <div v-for="n in 5" :key="n" class="bubble" :class="'b' + n"></div>

    <div class="login-card">
      <h2 class="title">售水业务管理系统</h2>
      <p class="subtitle">WATER SUPPLY MANAGEMENT SYSTEM</p>
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
        <div class="row-between">
          <el-checkbox v-model="rememberName">记住用户名</el-checkbox>
          <span class="hint">忘记密码请联系管理员重置</span>
        </div>
        <el-form-item>
          <el-button type="primary" class="login-btn" :loading="loading" @click="submit">
            登 录
          </el-button>
        </el-form-item>
      </el-form>
    </div>

    <div class="wave wave1"></div>
    <div class="wave wave2"></div>
  </div>
</template>

<style scoped>
.login-page {
  position: relative;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: linear-gradient(160deg, #2b7fc9 0%, #14507f 45%, #0a2d4d 100%);
}

/* 装饰气泡 */
.bubble {
  position: absolute;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.12);
  animation: bob 9s ease-in-out infinite alternate;
}
.b1 { width: 180px; height: 180px; top: 12%; left: 8%; }
.b2 { width: 260px; height: 260px; top: 6%; right: 12%; animation-delay: -3s; }
.b3 { width: 90px; height: 90px; bottom: 30%; left: 16%; animation-delay: -5s; }
.b4 { width: 56px; height: 56px; top: 32%; right: 32%; animation-delay: -7s; }
.b5 { width: 140px; height: 140px; bottom: 34%; right: 7%; animation-delay: -2s; }
@keyframes bob {
  from { transform: translateY(0); }
  to { transform: translateY(-26px); }
}

/* 卡片 */
.login-card {
  position: relative;
  z-index: 2;
  width: 420px;
  max-width: 92vw;
  background: #fff;
  border-radius: 14px;
  box-shadow: 0 24px 60px rgba(4, 32, 58, 0.45);
  padding: 42px 40px 30px;
  animation: cardIn 0.6s ease-out;
}
@keyframes cardIn {
  from { opacity: 0; transform: translateY(24px); }
  to { opacity: 1; transform: none; }
}
.title {
  margin: 0 0 4px;
  text-align: center;
  font-size: 24px;
  font-weight: 700;
  letter-spacing: 1px;
  color: #123c63;
}
.subtitle {
  margin: 0 0 28px;
  text-align: center;
  font-size: 12px;
  letter-spacing: 4px;
  color: #9aa7b5;
}
.row-between {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 18px;
}
.hint {
  font-size: 12px;
  color: #b0b8c4;
}
:deep(.el-input__wrapper) {
  border-radius: 8px;
}
:deep(.el-button--primary) {
  width: 100%;
  height: 44px;
  border: none;
  border-radius: 8px;
  font-size: 16px;
  letter-spacing: 8px;
  background: linear-gradient(135deg, #2b7fc9, #14507f);
  transition: filter 0.2s;
}
:deep(.el-button--primary:hover) {
  filter: brightness(1.1);
}

/* 底部水面波纹 */
.wave {
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 140px;
  background-repeat: repeat-x;
  background-size: 720px 140px;
  pointer-events: none;
}
.wave1 {
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 720 140' preserveAspectRatio='none'%3E%3Cpath d='M0,80 C120,120 240,40 360,70 C480,100 600,50 720,80 L720,140 L0,140 Z' fill='rgba(255,255,255,0.08)'/%3E%3C/svg%3E");
  animation: waveMove 22s linear infinite;
}
.wave2 {
  height: 110px;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 720 110' preserveAspectRatio='none'%3E%3Cpath d='M0,60 C140,95 280,30 420,58 C540,82 640,44 720,60 L720,110 L0,110 Z' fill='rgba(255,255,255,0.15)'/%3E%3C/svg%3E");
  animation: waveMove 13s linear infinite;
}
@keyframes waveMove {
  to { background-position-x: -720px; }
}

/* 手机端适配 */
@media (max-width: 480px) {
  .login-card {
    padding: 30px 24px 22px;
    border-radius: 12px;
  }
  .title {
    font-size: 20px;
  }
  .subtitle {
    font-size: 10px;
    letter-spacing: 2px;
    margin-bottom: 20px;
  }
  :deep(.el-input__wrapper) {
    padding: 2px 12px;
  }
  :deep(.el-input__inner) {
    font-size: 16px; /* ≥16px,避免 iOS 聚焦自动放大 */
  }
  :deep(.el-button--primary) {
    height: 42px;
    font-size: 15px;
    letter-spacing: 6px;
  }
}
</style>
