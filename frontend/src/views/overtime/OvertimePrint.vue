<template>
  <div class="ot-print" v-loading="loading">
    <div class="no-print">
      <el-button size="small" @click="load">刷新</el-button>
      <el-button size="small" type="primary" @click="doPrint">打印</el-button>
      <el-button size="small" @click="doClose">关闭</el-button>
    </div>
    <div v-if="error" style="color: #d9534f; text-align: center; padding: 40px">{{ error }}</div>
    <template v-else-if="data.apply">
      <h1>加班审批单</h1>
      <table class="info">
        <tbody>
          <tr>
            <td class="label">编号</td><td>{{ a.apply_no }}</td>
            <td class="label">月份</td><td>{{ a.apply_month }}</td>
            <td class="label">类型</td><td>{{ a.work_type }}{{ isComp ? '(补休)' : '' }}</td>
          </tr>
          <tr>
            <td class="label">部门</td><td>{{ a.deptName }}</td>
            <td class="label">申请人</td><td>{{ a.applyUserName }}</td>
            <td class="label">日期</td><td>{{ (a.apply_date || '').slice(0, 10) }}</td>
          </tr>
          <tr>
            <td class="label">操作时间</td><td>{{ a.create_time }}</td>
            <td class="label">状态</td><td>{{ statusText[a.status] || a.status }}</td>
            <td class="label">{{ totalLabel }}</td><td>{{ totalValue }}</td>
          </tr>
          <tr><td class="label">备注</td><td colspan="5">{{ a.remark || '' }}</td></tr>
        </tbody>
      </table>

      <h3>加班人员汇总</h3>
      <table class="data">
        <thead><tr><th v-for="h in detailHeaders" :key="h">{{ h }}</th></tr></thead>
        <tbody>
          <tr v-for="(d, i) in data.details" :key="i">
            <td class="col-name">{{ d.personnelName }}</td>
            <td>{{ d.employeeNo }}</td>
            <td>{{ d.accounting_month }}</td>
            <template v-if="isTS">
              <td>130</td><td>{{ d.total_multiplier }}</td><td>{{ Math.round(d.total_amount || 0) }}</td>
            </template>
            <template v-else-if="isComp">
              <td>{{ Number(d.rawHours || 0).toFixed(2) }}</td>
              <td>{{ Number(d.total_hours || 0).toFixed(2) }}</td>
              <td>{{ Number(d.rawHours || 0).toFixed(2) }}</td>
            </template>
            <template v-else>
              <td>{{ d.daily_wage }}</td>
              <td>{{ Number(d.rawHours || 0).toFixed(2) }}</td>
              <td>{{ Number(d.total_hours || 0).toFixed(2) }}</td>
              <td>{{ d.days }}</td>
              <td>{{ Math.round(d.total_amount || 0) }}</td>
            </template>
          </tr>
          <tr style="background: #f0f0f0; font-weight: bold">
            <td :colspan="isTS ? 5 : (isComp ? 5 : 7)">合计</td>
            <td>{{ isTS ? Math.round(sumAmount) : (isComp ? sumRaw.toFixed(2) : Math.round(sumAmount)) }}</td>
          </tr>
        </tbody>
      </table>

      <h3>加班时段明细</h3>
      <table class="data">
        <thead><tr><th v-for="h in timeHeaders" :key="h">{{ h }}</th></tr></thead>
        <tbody>
          <tr v-for="(e, i) in data.timeEntries" :key="i">
            <td class="col-name">{{ e.personnelName }}</td>
            <td class="col-date">{{ e.work_date }} {{ weekLabel(e.work_date) }}</td>
            <td>{{ (e.start_time || '').slice(11, 16) }}</td>
            <td>{{ (e.is_full_day || e.shift_type) && e.shift_type === '晚班' ? '次日 ' : '' }}{{ (e.end_time || '').slice(11, 16) }}</td>
            <td>{{ Number(e.raw_hours || 0).toFixed(2) }}</td>
            <td>{{ e.multiplier || 1.5 }}</td>
            <td v-if="isTS">130</td>
            <td v-if="isTS">{{ Math.round(e.overtime_amount || 0) }}</td>
            <td v-else-if="isComp">{{ Number(e.raw_hours || 0).toFixed(2) }}</td>
            <td v-else>{{ Number(e.total_hours || 0).toFixed(2) }}</td>
            <td class="col-reason">{{ e.reason }}</td>
            <template v-if="isWqx"><td>{{ e.work_order_no }}</td><td>{{ e.address }}</td></template>
          </tr>
        </tbody>
      </table>

      <div class="sign-section">
        <h3>签字栏</h3>
        <table class="data"><thead><tr>
          <th style="width: 14%">制单人</th><th style="width: 14%">复核</th>
          <th style="width: 38%">{{ a.leaderLabel || '领导' }}</th><th>HR核销</th>
        </tr></thead>
        <tbody><tr><td class="sig"></td><td class="sig"></td><td class="sig"></td><td class="sig"></td></tr></tbody></table>
      </div>

      <div v-if="data.approvals?.length">
        <h3>审批记录</h3>
        <table class="data">
          <thead><tr><th v-for="h in ['审批步骤', '审批层级', '审批人', '审批状态', '审批意见', '审批时间']" :key="h">{{ h }}</th></tr></thead>
          <tbody>
            <tr v-for="(ap, i) in data.approvals" :key="i">
              <td>{{ ap.step }}</td><td>{{ ap.levelName }}</td><td>{{ ap.approverName }}</td>
              <td :style="{ color: approvalColor[ap.status] }">{{ approvalText[ap.status] || ap.status }}</td>
              <td>{{ ap.comment }}</td><td>{{ ap.approve_time }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import * as api from '@/api/overtime'
import './overtime.css'

const loading = ref(false)
const error = ref('')
const data = ref({})
const a = computed(() => data.value.apply || {})
const isTS = computed(() => a.value.work_type === '特水开关阀门')
const isComp = computed(() => a.value.settle_type === '补休')
const isWqx = computed(() => a.value.work_type === '维抢修加班')
const statusText = {
  draft: '草稿', submitted: '已提交', grouped: '已汇总', pending: '审批中',
  approved: '已通过', rejected: '已驳回', skipped: '已跳过', printed: '已打印', verified: '已核销',
}
const approvalText = { pending: '待审批', approved: '已通过', rejected: '已驳回', skipped: '已跳过' }
const approvalColor = { approved: '#3c763d', rejected: '#a94442', pending: '#8a6d3b', skipped: '#999' }
const totalLabel = computed(() => isTS.value ? '总金额' : (isComp.value ? '补休时长' : '总时长'))
const totalValue = computed(() => isTS.value
  ? `${Math.round(a.value.total_amount || 0)}元`
  : `${Number(a.value.total_hours || 0).toFixed(2)}h`)
const detailHeaders = computed(() => isTS.value
  ? ['姓名', '工号', '核算月份', '基数(元/天)', '汇总倍数', '加班金额(元)']
  : isComp.value
    ? ['姓名', '工号', '核算月份', '原始时长(h)', '折算时长(h)', '补休时长(h)']
    : ['姓名', '工号', '核算月份', '日工资', '原始时长(h)', '折算时长(h)', '加班天数', '加班金额(元)'])
const timeHeaders = computed(() => {
  const base = isTS.value
    ? ['姓名', '日期', '开始', '结束', '原时长', '倍数', '基数(元)', '金额(元)', '事由']
    : isComp.value
      ? ['姓名', '日期', '开始', '结束', '原时长', '倍数', '补休(h)', '事由']
      : ['姓名', '日期', '开始', '结束', '原时长', '倍数', '折算(h)', '事由']
  return isWqx.value ? [...base, '工单号', '地址'] : base
})
const sumRaw = computed(() => (data.value.details || []).reduce((s, d) => s + Number(d.rawHours || 0), 0))
const sumAmount = computed(() => (data.value.details || []).reduce((s, d) => s + Number(d.total_amount || 0), 0))
function weekLabel(d) {
  if (!d) return ''
  const dt = new Date(String(d).replace(/-/g, '/'))
  return '(周' + '日一二三四五六'[dt.getDay()] + ')'
}
function doPrint() { window.print() }
function doClose() { window.close() }
async function load() {
  const id = new URLSearchParams(location.search).get('id')
  if (!id) { error.value = '缺少申请单 id'; return }
  loading.value = true
  try {
    const r = await api.getPrintData(Number(id))
    if (!r.success) { error.value = r.msg || '无法加载打印数据'; return }
    data.value = r
    error.value = ''
    document.title = `加班审批单-${r.apply.apply_no}-${(r.apply.apply_date || '').slice(0, 10)}`
  } finally { loading.value = false }
}
onMounted(load)
</script>
