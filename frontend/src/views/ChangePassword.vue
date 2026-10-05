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
    <el-card class="pwd-card">
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
    </el-card>
  </div>
</template>

<style scoped>
.pwd-page {
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #1f6fb2 0%, #0b2e4f 100%);
}
.pwd-card {
  width: 420px;
  padding: 10px 10px 0;
}
.title {
  text-align: center;
  margin: 10px 0 20px;
  color: #303133;
}
.tip {
  margin-bottom: 20px;
}
.btn {
  width: 100%;
}
</style>
