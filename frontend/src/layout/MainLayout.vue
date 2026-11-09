<script setup>
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { changePassword } from '@/api/auth'
import { useAuthStore } from '@/stores/auth'
import { PASSWORD_TIP, passwordRule } from '@/utils/password'
import { useIdleLogout } from '@/utils/idle'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()

const menuItems = computed(() => {
  const items = [{ path: '/dashboard', title: '首页', icon: 'HomeFilled' }]
  const engineering = []
  if (auth.hasPerm('project:view')) engineering.push({ path: '/project', title: '工程管理' })
  if (auth.hasPerm('roadrepair:view')) engineering.push({ path: '/roadrepair', title: '路面修复管理' })
  if (engineering.length === 1) {
    items.push({ ...engineering[0], icon: 'OfficeBuilding' })
  } else if (engineering.length > 1) {
    items.push({ title: '工程管理', icon: 'OfficeBuilding', children: engineering })
  }
  if (auth.hasPerm('waterfee:view')) {
    items.push({ path: '/waterfee', title: '特殊群体管理', icon: 'User' })
  }
  const communication = []
  if (auth.hasPerm('phone:view')) communication.push({ path: '/phone', title: '手机管理' })
  if (auth.hasPerm('ipadress:view')) communication.push({ path: '/ipadress', title: 'IP地址管理' })
  if (auth.hasPerm('simcard:view')) communication.push({ path: '/simcard', title: 'SIM卡管理' })
  if (auth.hasPerm('simfee:view')) communication.push({ path: '/simfee', title: '通信费' })
  if (communication.length) {
    items.push({ title: '通信网络', icon: 'Connection', children: communication })
  }
  const vehicle = []
  if (auth.hasPerm('vehicle:view')) {
    vehicle.push({ path: '/vehicle', title: '车辆管理' })
    vehicle.push({ path: '/vehicle/chuxian', title: '车辆出险信息' })
    vehicle.push({ path: '/vehicle/weizhang', title: '车辆违章信息' })
    vehicle.push({ path: '/vehicle/baoxian', title: '车辆保险信息' })
    vehicle.push({ path: '/vehicle/clfeiyong', title: '车辆各类费用表' })
    vehicle.push({ path: '/vehicle/daily', title: '日常用车' })
  }
  if (auth.hasPerm('oilcard:view')) {
    vehicle.push({ path: '/vehicle/oilcard', title: '油卡管理' })
  }
  if (auth.hasPerm('plusoil:view')) {
    vehicle.push({ path: '/vehicle/plusoil', title: '加油明细' })
  }
  if (auth.hasPerm('oiltj:view')) {
    vehicle.push({ path: '/vehicle/oiltj', title: '车辆油量统计' })
  }
  if (auth.hasPerm('repair:view')) {
    vehicle.push({ path: '/repair', title: '车辆维修' })
  }
  if (vehicle.length) {
    items.push({ title: '车辆管理', icon: 'Van', children: vehicle })
  }
  const leak = []
  if (auth.hasPerm('celou:view')) leak.push({ path: '/celou', title: '测漏成果' })
  if (auth.hasPerm('leak:view')) leak.push({ path: '/leak', title: '测漏笔记' })
  if (leak.length) {
    items.push({ title: '测漏管理', icon: 'DataAnalysis', children: leak })
  }
  const contract = []
  if (auth.hasPerm('contract:view')) contract.push({ path: '/contract/register', title: '合同登记' })
  if (auth.hasPerm('contract:collect')) contract.push({ path: '/contract/collect', title: '合同归集' })
  if (contract.length) {
    items.push({ title: '合同管理', icon: 'Document', children: contract })
  }
  // 加班申请对全员开放:页面内各 Tab 由后端下发的权限标记控制显隐
  items.push({ path: '/overtime', title: '加班申请审批', icon: 'Timer' })
  // 维抢修加班:独立模块(工单加班台账/工资汇总/附件),与"加班申请审批"互不相干
  if (auth.hasPerm('jiaban:view')) {
    items.push({ path: '/jiaban', title: '维抢修加班', icon: 'AlarmClock' })
  }
  const jcxt = []
  if (auth.hasPerm('jcxt:view')) jcxt.push({ path: '/jcxt', title: '稽查系统' })
  if (auth.hasPerm('spjicha:view')) jcxt.push({ path: '/spjicha', title: '审批稽查' })
  if (auth.hasPerm('jcdan:view')) jcxt.push({ path: '/jcdan', title: '稽查单' })
  if (auth.hasPerm('jcjl:view')) jcxt.push({ path: '/jcjl', title: '稽查奖励' })
  if (jcxt.length) {
    items.push({ title: '稽查管理', icon: 'Search', children: jcxt })
  }
  // 工单系统:工单信息录入 + 领料 + 材料库,后续工单模块继续挂到这一级菜单下
  const workorder = []
  if (auth.hasPerm('gongdan:view')) workorder.push({ path: '/gongdan', title: '工单信息录入' })
  if (auth.hasPerm('workorder:view')) workorder.push({ path: '/workorder', title: '工单领料' })
  if (auth.hasPerm('lingliao:view')) workorder.push({ path: '/lingliao', title: '领料申请' })
  if (auth.hasPerm('jiesuandan:view')) workorder.push({ path: '/jiesuandan', title: '领料结算' })
  if (auth.hasPerm('jiesuan:view')) workorder.push({ path: '/jiesuan', title: '材料结算单查看' })
  if (auth.hasPerm('material:view')) workorder.push({ path: '/material', title: '工单材料库' })
  if (workorder.length) {
    items.push({ title: '工单系统', icon: 'Box', children: workorder })
  }
  // 年度计划:营业所发起 -> 实施单表 -> 实施汇总 -> 正式计划
  const plan = []
  if (auth.hasPerm('jhyyfaqi:view')) plan.push({ path: '/jhyyfaqi', title: '营业所发起计划' })
  if (auth.hasPerm('jhssdb:view')) plan.push({ path: '/jhssdb', title: '实施单表' })
  if (auth.hasPerm('jhsshz:view')) plan.push({ path: '/jhsshz', title: '实施汇总' })
  if (auth.hasPerm('plan:view')) {
    plan.push({ path: '/plan', title: '正式计划' })
    plan.push({ path: '/plan/dashboard', title: '进度看板' })
  }
  if (plan.length) {
    items.push({ title: '年度计划', icon: 'Calendar', children: plan })
  }
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

// 公用电脑防护:30 分钟无任何操作自动退出
useIdleLogout(() => {
  ElMessage.warning('超过 30 分钟无操作,已自动退出')
  auth.logout()
  router.push('/login')
}, 30)
</script>

<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="logo">售水业务管理系统</div>
      <el-menu
        :default-active="activeMenu"
        router
        unique-opened
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
  /* 一级子项 padding-left = 20px + 1 * 40px = 60px;
     父标题带 24px 图标文字约在 49px,子项文字再向右错开,层级更清楚 */
  --el-menu-level-padding: 40px;
}
/* 展开的子菜单:整块换成比父级(#001529)略亮的蓝黑,一眼能分出层级 */
.menu :deep(.el-menu--inline) {
  background-color: #0b2238;
  padding: 4px 0;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.08),
    inset 0 -1px 0 rgba(0, 0, 0, 0.2);
}
.menu :deep(.el-menu--inline .el-menu-item) {
  color: #b6bfcb;
}
/* 缩进后的层级小圆点 */
.menu :deep(.el-menu--inline .el-menu-item)::before {
  content: '';
  position: absolute;
  left: 46px;
  top: 50%;
  width: 5px;
  height: 5px;
  border-radius: 50%;
  transform: translateY(-50%);
  background: rgba(255, 255, 255, 0.28);
}
.menu :deep(.el-menu--inline .el-menu-item:hover) {
  color: #fff;
  background-color: rgba(255, 255, 255, 0.07);
}
.menu :deep(.el-menu--inline .el-menu-item.is-active) {
  color: #fff;
  background-color: rgba(83, 58, 253, 0.28);
  box-shadow: inset 3px 0 0 #8b7bff;
}
.menu :deep(.el-menu--inline .el-menu-item.is-active)::before {
  background: #a99dff;
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
