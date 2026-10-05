<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { changePassword } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import { PASSWORD_TIP, passwordRule } from '@/utils/password'

const router = useRouter()
const auth = useAuthStore()

const formRef = ref()
const loading = ref(false)
const form = reactive({ old_password: '', new_password: '', confirm: '' })
const rules = {
  old_password: [{ required: true, message: '请输入原密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    passwordRule,
  ],
  confirm: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (rule, value, callback) =>
        value === form.new_password ? callback() : callback(new Error('两次输入不一致')),
      trigger: 'blur',
    },
  ],
}

async function submit() {
  await formRef.value.validate()
  loading.value = true
  try {
    await changePassword({ old_password: form.old_password, new_password: form.new_password })
    await auth.refreshUser()
    ElMessage.success('密码修改成功')
    router.push('/')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="pwd-page">
    <div class="wave wave1"></div>
    <div class="wave wave2"></div>
    <div class="pwd-card">
      <h2 class="title">修改初始密码</h2>
      <el-alert
        type="warning"
        show-icon
        :closable="false"
        title="您正在使用初始密码,请先设置新密码"
        :description="'新密码' + PASSWORD_TIP + '。'"
        class="tip"
      />
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px" @keyup.enter="submit">
        <el-form-item label="原密码" prop="old_password">
          <el-input v-model="form.old_password" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码" prop="new_password">
          <el-input v-model="form.new_password" type="password" show-password :placeholder="PASSWORD_TIP" />
        </el-form-item>
        <el-form-item label="确认新密码" prop="confirm">
          <el-input v-model="form.confirm" type="password" show-password placeholder="请再次输入新密码" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" class="btn" :loading="loading" @click="submit">确认修改</el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<style scoped>
.pwd-page {
  position: relative;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: linear-gradient(160deg, #2b7fc9 0%, #14507f 45%, #0a2d4d 100%);
}
.pwd-card {
  position: relative;
  z-index: 2;
  width: 440px;
  max-width: 92vw;
  background: #fff;
  border-radius: 14px;
  box-shadow: 0 24px 60px rgba(4, 32, 58, 0.45);
  padding: 36px 36px 22px;
  animation: cardIn 0.6s ease-out;
}
@keyframes cardIn {
  from { opacity: 0; transform: translateY(24px); }
  to { opacity: 1; transform: none; }
}
.title {
  margin: 0 0 18px;
  text-align: center;
  font-size: 24px;
  font-weight: 700;
  letter-spacing: 1px;
  color: #123c63;
}
.tip {
  margin-bottom: 20px;
}
.btn {
  width: 100%;
  height: 44px;
  border: none;
  border-radius: 8px;
  font-size: 16px;
  letter-spacing: 6px;
  background: linear-gradient(135deg, #2b7fc9, #14507f);
}
:deep(.el-button--primary:hover) {
  filter: brightness(1.1);
}
:deep(.el-input__wrapper) {
  border-radius: 8px;
}
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
  .pwd-card {
    width: 92vw;
    padding: 28px 22px 18px;
    border-radius: 12px;
  }
  .title {
    font-size: 20px;
  }
  :deep(.el-input__inner) {
    font-size: 16px; /* ≥16px,避免 iOS 聚焦自动放大 */
  }
  .btn {
    height: 42px;
    font-size: 15px;
    letter-spacing: 6px;
  }
}
</style>
