<template>
  <div>
    <el-card class="filter-card" shadow="never">
      <div class="filter-row">
        <div class="filter-group">
          <label>月份：</label>
          <el-select v-model="filters.month" size="small" style="width: 110px" @change="onFilterChange">
            <el-option label="全部" value="" />
            <el-option v-for="m in ot.months.value" :key="m" :label="m" :value="m" />
          </el-select>
        </div>
        <div class="filter-group">
          <label>部门：</label>
          <el-tree-select v-model="filters.dept" :data="ot.deptTreeData.value" node-key="value"
                          :props="{ label: 'label', children: 'children' }" check-strictly clearable
                          size="small" style="width: 280px" @change="onFilterChange" />
        </div>
        <div class="filter-group">
          <label>类型：</label>
          <el-select v-model="filters.workType" size="small" style="width: 130px" @change="onFilterChange">
            <el-option label="全部" value="all" />
            <el-option v-for="w in ot.workTypes.value" :key="w" :label="w" :value="w" />
          </el-select>
        </div>
        <div class="filter-group">
          <el-select v-model="filters.maxDepth" size="small" style="width: 120px" @change="onFilterChange">
            <el-option label="全部下级" value="" />
            <el-option label="本级" value="0" />
            <el-option v-for="i in 5" :key="i" :label="`本级+${i}`" :value="String(i)" />
          </el-select>
        </div>
      </div>
    </el-card>
    <div class="toolbar">
      <el-button size="small" type="primary" @click="search">搜索</el-button>
      <el-button size="small" @click="clearFilter">重置</el-button>
      <el-button size="small" type="primary" plain @click="batchVerify">批量核销</el-button>
    </div>
    <div class="table-card">
      <el-table :data="rows" border size="small" v-loading="loading" height="540"
                @selection-change="(v) => (selected = v)">
        <el-table-column type="selection" width="42" />
        <el-table-column label="状态" width="84" align="center">
          <template #default="{ row }"><span :class="ot.tagClass(row.status)">{{ ot.tagText(row.status) }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="215" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <span class="grid-link" @click="ot.openPrint(row.id)">查看</span>
              <template v-if="row.status === 'printed'">
                <span v-if="row.settle_type === '补休'" class="grid-action" style="background: #ff9800" @click="openComp(row)">登记补休</span>
                <span v-else class="grid-action" @click="verifyOne(row)">核销</span>
                <span class="grid-danger" @click="revert(row)">退回草稿</span>
              </template>
              <span v-else-if="row.status === 'verified'" class="grid-action-subtle" @click="unverify(row)">反核销</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="apply_no" label="编号" width="120" />
        <el-table-column prop="apply_month" label="月份" width="76" />
        <el-table-column prop="work_type" label="加班类型" width="118" />
        <el-table-column prop="settle_type" label="结算" width="68" />
        <el-table-column prop="applyUserName" label="制单人" width="88" />
        <el-table-column prop="deptName" label="部门" min-width="190" show-overflow-tooltip />
        <el-table-column prop="total_hours" label="总时长(h)" width="95" />
        <el-table-column label="原始时长(h)" width="100">
          <template #default="{ row }">{{ Number(row.raw_hours || 0).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column prop="days" label="折合天数" width="88" />
        <el-table-column label="金额(元)" width="100" align="right">
          <template #default="{ row }">{{ row.settle_type === '补休' ? '—' : Math.round(row.total_amount || 0) }}</template>
        </el-table-column>
        <el-table-column prop="verifyUserName" label="核销人" width="88" />
        <el-table-column prop="verify_time" label="核销时间" width="140" />
        <el-table-column prop="create_time" label="操作时间" width="140" />
      </el-table>
      <div class="pager">
        <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
                       :page-sizes="[50, 100, 200]" layout="total, sizes, prev, pager, next, jumper"
                       @current-change="load" @size-change="search" />
      </div>
    </div>

    <!-- 登记补休 -->
    <el-dialog v-model="compVisible" title="登记补休" width="500px" class="ot-dialog" append-to-body>
      <el-form label-width="100px" size="small">
        <el-form-item label="人员" required>
          <el-select v-model="comp.personnelId" style="width: 220px" @change="loadBalance">
            <el-option v-for="p in compPersonnel" :key="p.personnel_id" :label="p.personnelName" :value="p.personnel_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="日期" required>
          <el-date-picker v-model="comp.leaveDate" type="date" value-format="YYYY-MM-DD" style="width: 180px" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="comp.leaveType" style="width: 140px" @change="onLeaveTypeChange">
            <el-option label="全天" value="全天" />
            <el-option label="半天" value="半天" />
            <el-option label="自定义" value="自定义" />
          </el-select>
        </el-form-item>
        <el-form-item label="起止时间" v-if="comp.leaveType === '自定义'">
          <el-input v-model="comp.start" style="width: 90px" maxlength="4" placeholder="0830" @input="updateHours" />
          <span style="margin: 0 6px">至</span>
          <el-input v-model="comp.end" style="width: 90px" maxlength="4" placeholder="1730" @input="updateHours" />
        </el-form-item>
        <el-form-item label="本次时长">
          <span style="color: #ff9800; font-weight: bold; font-size: 16px">{{ Number(comp.hours).toFixed(2) }}</span> 小时
        </el-form-item>
        <el-form-item label="可用余额">
          <span style="color: #533afd; font-weight: bold; font-size: 16px">{{ Number(comp.balance).toFixed(2) }}</span> 小时
        </el-form-item>
        <el-form-item label="事由"><el-input v-model="comp.reason" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="compVisible = false">取消</el-button>
        <el-button type="primary" @click="saveComp">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { inject, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as api from '@/api/overtime'

const ot = inject('ot')
// ★ 三处统一引用 ot.currentMonth:下拉初值 / 表格首查参数 / 重置值,避免旧系统曾出现的
//   "首次加载=全部月份,重置后变当前月" 的数据集漂移。
const filters = reactive({ month: '', dept: null, workType: 'all', maxDepth: '' })
const rows = ref([]), total = ref(0), page = ref(1), size = ref(50)
const loading = ref(false), selected = ref([]), suppress = ref(false)

watch(() => ot.currentMonth.value, (m) => {
  if (filters.month === '') filters.month = m
}, { immediate: true })

function params() {
  const p = {
    status: 'verify_mgmt', page: page.value, rows: size.value,
    work_type: filters.workType,
  }
  if (filters.month) p.month = filters.month
  if (filters.dept) p.dept_id = filters.dept
  if (filters.maxDepth !== '') p.max_depth = filters.maxDepth
  return p
}
async function load() {
  loading.value = true
  try {
    const r = await api.listApplies(params())
    rows.value = r.rows || []; total.value = r.total || 0
  } finally { loading.value = false }
}
function search() { page.value = 1; load() }
function onFilterChange() { if (!suppress.value) search() }
function clearFilter() {
  suppress.value = true
  try {
    filters.month = ot.currentMonth.value
    filters.dept = null
    filters.workType = 'all'
    filters.maxDepth = ''
  } finally { suppress.value = false }
  search()
}
watch(() => ot.tick.value, () => load())
onMounted(load)

async function batchVerify() {
  const ids = selected.value.filter((r) => r.status === 'printed').map((r) => r.id)
  if (!ids.length) return ElMessage.warning('请勾选已打印状态的申请单')
  await ot.confirm(`确定核销选中的 ${ids.length} 张申请单吗？`)
  const r = await api.batchVerify(ids)
  ElMessage.success(r.msg); ot.bump(); load()
}
async function verifyOne(row) {
  await ot.confirm(`确定核销 ${row.apply_no} 吗？`)
  const r = await api.batchVerify([row.id])
  ElMessage.success(r.msg); ot.bump(); load()
}
async function unverify(row) {
  await ot.confirm('确定反核销吗？')
  const r = await api.unverifyApply(row.id)
  ElMessage.success(r.msg); ot.bump(); load()
}
async function revert(row) {
  await ot.confirm('确定退回草稿吗？人员记录将回到待汇总池，申请单会被销毁。')
  const r = await api.revertToDraft(row.id)
  ElMessage.success(r.msg); ot.bump(); load()
}

// ---- 补休登记
const compVisible = ref(false)
const compPersonnel = ref([])
const comp = reactive({ applyId: 0, personnelId: null, leaveDate: new Date().toISOString().slice(0, 10),
                        leaveType: '全天', start: '0830', end: '1730', hours: 8, balance: 0, reason: '' })
async function openComp(row) {
  const info = await api.getApplyInfo(row.id)
  compPersonnel.value = info.details || []
  comp.applyId = row.id
  comp.personnelId = compPersonnel.value[0]?.personnel_id || null
  comp.leaveDate = new Date().toISOString().slice(0, 10)
  comp.leaveType = '全天'
  comp.hours = 8
  comp.reason = ''
  compVisible.value = true
  await loadBalance()
}
async function loadBalance() {
  if (!comp.personnelId) return
  const r = await api.getCompBalance(comp.personnelId)
  comp.balance = r.balance || 0
}
function onLeaveTypeChange() {
  if (comp.leaveType === '全天') comp.hours = 8
  else if (comp.leaveType === '半天') comp.hours = 4
  else updateHours()
}
function updateHours() {
  const toMin = (s) => {
    const v = String(s || '').replace(/\D/g, '')
    return v.length >= 4 ? Number(v.slice(0, 2)) * 60 + Number(v.slice(2, 4)) : null
  }
  const a = toMin(comp.start), b = toMin(comp.end)
  if (a === null || b === null) return
  let d = b - a
  if (d <= 0) d += 24 * 60
  comp.hours = Number((d / 60).toFixed(2))
}
async function saveComp() {
  if (!comp.personnelId) return ElMessage.warning('请选择人员')
  if (!(comp.hours > 0)) return ElMessage.warning('补休时长必须大于0')
  const r = await api.saveCompLeave({
    personnelId: comp.personnelId, leaveDate: comp.leaveDate, hours: comp.hours,
    leaveType: comp.leaveType, reason: comp.reason,
    startTime: comp.leaveType === '自定义' ? `${comp.leaveDate} ${comp.start.slice(0, 2)}:${comp.start.slice(2)}` : null,
    endTime: comp.leaveType === '自定义' ? `${comp.leaveDate} ${comp.end.slice(0, 2)}:${comp.end.slice(2)}` : null,
  })
  ElMessage.success(r.msg)
  compVisible.value = false
  ot.bump()
  load()
}
</script>
