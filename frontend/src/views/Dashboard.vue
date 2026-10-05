<script setup>
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
</script>

<template>
  <el-card>
    <h2>欢迎使用,{{ auth.user?.real_name || auth.user?.username }}</h2>
    <p style="color: #909399">
      系统骨架已就绪。后续业务模块(如抄表、车辆管理、工程管理等)可以在此基础上逐个开发:
      在后端添加 models 和 routes,在前端添加页面和菜单即可。
    </p>
  </el-card>
</template>
