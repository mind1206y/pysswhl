import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import MainLayout from '@/layout/MainLayout.vue'
import Login from '@/views/Login.vue'
import ChangePassword from '@/views/ChangePassword.vue'
import Dashboard from '@/views/Dashboard.vue'
import DeptManage from '@/views/system/DeptManage.vue'
import UserManage from '@/views/system/UserManage.vue'
import RoleManage from '@/views/system/RoleManage.vue'
import ProjectManage from '@/views/project/ProjectManage.vue'
import WaterFeeManage from '@/views/waterfee/WaterFeeManage.vue'
import PhoneManage from '@/views/phone/PhoneManage.vue'
import IpAddressManage from '@/views/ipadress/IpAddressManage.vue'
import VehicleManage from '@/views/vehicle/VehicleManage.vue'
import ChuxianView from '@/views/vehicle/ChuxianView.vue'
import WeizhangView from '@/views/vehicle/WeizhangView.vue'
import ClFeiyongManage from '@/views/vehicle/ClFeiyongManage.vue'
import BaoxianView from '@/views/vehicle/BaoxianView.vue'
import VehicleDaily from '@/views/vehicle/VehicleDaily.vue'
import OilCardManage from '@/views/vehicle/OilCardManage.vue'
import PlusOilManage from '@/views/vehicle/PlusOilManage.vue'
import OilTj from '@/views/vehicle/OilTj.vue'
import RepairManage from '@/views/repair/RepairManage.vue'
import SimCardManage from '@/views/simcard/SimCardManage.vue'
import SimFeeManage from '@/views/simfee/SimFeeManage.vue'
import CelouTb from '@/views/celou/CelouTb.vue'
import LeakNotes from '@/views/leak/LeakNotes.vue'
import ContractRegister from '@/views/contract/ContractRegister.vue'
import ContractCollect from '@/views/contract/ContractCollect.vue'
import OvertimeApply from '@/views/overtime/OvertimeApply.vue'
import OvertimePrint from '@/views/overtime/OvertimePrint.vue'
import PhonePrint from '@/views/phone/PhonePrint.vue'
import JcxtManage from '@/views/jcxt/JcxtManage.vue'
import SpjichaManage from '@/views/jcxt/SpjichaManage.vue'
import JcdanManage from '@/views/jcxt/JcdanManage.vue'
import JcJlManage from '@/views/jcxt/JcJlManage.vue'
import MaterialManage from '@/views/material/MaterialManage.vue'
import WorkOrderManage from '@/views/workorder/WorkOrderManage.vue'
import LingliaoManage from '@/views/lingliao/LingliaoManage.vue'
import JiesuanDanManage from '@/views/jiesuandan/JiesuanDanManage.vue'
import JiesuanPrint from '@/views/jiesuandan/JiesuanPrint.vue'
import JiesuanView from '@/views/jiesuan/JiesuanView.vue'
import GongdanManage from '@/views/gongdan/GongdanManage.vue'
import RoadRepairManage from '@/views/roadrepair/RoadRepairManage.vue'
import JiabanManage from '@/views/jiaban/JiabanManage.vue'
import OfficialPlan from '@/views/plan/OfficialPlan.vue'
import PlanDashboard from '@/views/plan/PlanDashboard.vue'
import PlanTodo from '@/views/plan/PlanTodo.vue'
import PlanSummary from '@/views/plan/PlanSummary.vue'
import PlanApply from '@/views/plan/PlanApply.vue'

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
          path: 'project',
          component: ProjectManage,
          meta: { title: '工程管理', perm: 'project:view' },
        },
        {
          path: 'roadrepair',
          component: RoadRepairManage,
          meta: { title: '路面修复管理', perm: 'roadrepair:view' },
        },
        {
          path: 'waterfee',
          component: WaterFeeManage,
          meta: { title: '特殊群体管理', perm: 'waterfee:view' },
        },
        {
          path: 'phone',
          component: PhoneManage,
          meta: { title: '手机管理', perm: 'phone:view' },
        },
        {
          path: 'ipadress',
          component: IpAddressManage,
          meta: { title: 'IP地址管理', perm: 'ipadress:view' },
        },
        {
          path: 'vehicle',
          component: VehicleManage,
          meta: { title: '车辆管理', perm: 'vehicle:view' },
        },
        {
          path: 'vehicle/chuxian',
          component: ChuxianView,
          meta: { title: '车辆出险信息', perm: 'vehicle:view' },
        },
        {
          path: 'vehicle/weizhang',
          component: WeizhangView,
          meta: { title: '车辆违章信息', perm: 'vehicle:view' },
        },
        {
          path: 'vehicle/clfeiyong',
          component: ClFeiyongManage,
          meta: { title: '车辆各类费用表', perm: 'vehicle:view' },
        },
        {
          path: 'vehicle/baoxian',
          component: BaoxianView,
          meta: { title: '车辆保险信息', perm: 'baoxian:view' },
        },
        {
          path: 'vehicle/daily',
          component: VehicleDaily,
          meta: { title: '日常用车', perm: 'vehicle:view' },
        },
        {
          path: 'vehicle/oilcard',
          component: OilCardManage,
          meta: { title: '油卡管理', perm: 'oilcard:view' },
        },
        {
          path: 'vehicle/plusoil',
          component: PlusOilManage,
          meta: { title: '加油明细', perm: 'plusoil:view' },
        },
        {
          path: 'vehicle/oiltj',
          component: OilTj,
          meta: { title: '车辆油量统计', perm: 'oiltj:view' },
        },
        {
          path: 'repair',
          component: RepairManage,
          meta: { title: '车辆维修', perm: 'repair:view' },
        },
        {
          path: 'simcard',
          component: SimCardManage,
          meta: { title: 'SIM卡管理', perm: 'simcard:view' },
        },
        {
          path: 'simfee',
          component: SimFeeManage,
          meta: { title: '通信费', perm: 'simfee:view' },
        },
        {
          path: 'celou',
          component: CelouTb,
          meta: { title: '测漏成果', perm: 'celou:view' },
        },
        {
          path: 'leak',
          component: LeakNotes,
          meta: { title: '测漏笔记', perm: 'leak:view' },
        },
        {
          path: 'contract/register',
          component: ContractRegister,
          meta: { title: '合同登记', perm: 'contract:view' },
        },
        {
          path: 'contract/collect',
          component: ContractCollect,
          meta: { title: '合同归集', perm: 'contract:collect' },
        },
        {
          // 加班申请:菜单对全员开放(旧系统"我的加班"人人可用),各 Tab 由 /dicts 下发的
          // perms 精细控制,因此这里不设 meta.perm。
          path: 'overtime',
          component: OvertimeApply,
          meta: { title: '加班申请审批' },
        },
        {
          path: 'jcxt',
          component: JcxtManage,
          meta: { title: '稽查系统', perm: 'jcxt:view' },
        },
        {
          path: 'spjicha',
          component: SpjichaManage,
          meta: { title: '审批稽查', perm: 'spjicha:view' },
        },
        {
          path: 'jcdan',
          component: JcdanManage,
          meta: { title: '稽查单', perm: 'jcdan:view' },
        },
        {
          path: 'jcjl',
          component: JcJlManage,
          meta: { title: '稽查奖励', perm: 'jcjl:view' },
        },
        {
          path: 'gongdan',
          component: GongdanManage,
          meta: { title: '工单信息录入', perm: 'gongdan:view' },
        },
        {
          path: 'material',
          component: MaterialManage,
          meta: { title: '工单材料库', perm: 'material:view' },
        },
        {
          path: 'workorder',
          component: WorkOrderManage,
          meta: { title: '工单领料', perm: 'workorder:view' },
        },
        {
          path: 'lingliao',
          component: LingliaoManage,
          meta: { title: '领料申请', perm: 'lingliao:view' },
        },
        {
          path: 'jiesuandan',
          component: JiesuanDanManage,
          meta: { title: '领料结算', perm: 'jiesuandan:view' },
        },
        {
          path: 'jiaban',
          component: JiabanManage,
          meta: { title: '维抢修加班', perm: 'jiaban:view' },
        },
        {
          path: 'jhyyfaqi',
          component: PlanApply,
          meta: { title: '营业所发起计划', perm: 'jhyyfaqi:view' },
        },
        {
          path: 'jhssdb',
          component: PlanTodo,
          meta: { title: '实施单表', perm: 'jhssdb:view' },
        },
        {
          path: 'jhsshz',
          component: PlanSummary,
          meta: { title: '实施汇总', perm: 'jhsshz:view' },
        },
        {
          path: 'plan',
          component: OfficialPlan,
          meta: { title: '正式计划', perm: 'plan:view' },
        },
        {
          path: 'plan/dashboard',
          component: PlanDashboard,
          meta: { title: '进度看板', perm: 'plan:view' },
        },
        {
          path: 'jiesuan',
          component: JiesuanView,
          meta: { title: '材料结算单查看', perm: 'jiesuan:view' },
        },
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
    // 打印页独立窗口打开(不套 MainLayout),通过 localStorage 里的 token 走同一套鉴权
    { path: '/overtime/print', component: OvertimePrint, meta: { title: '加班审批单' } },
    { path: '/phone/print', component: PhonePrint, meta: { title: '手机签收单' } },
    { path: '/jiesuandan/print', component: JiesuanPrint, meta: { title: '采购申请单/验收单' } },
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
  document.title = to.meta.title ? `${to.meta.title} - 售水业务管理系统` : '售水业务管理系统'
})

export default router
