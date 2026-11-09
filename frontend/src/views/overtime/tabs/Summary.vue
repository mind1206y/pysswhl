<template>
  <div>
    <el-card class="filter-card" shadow="never">
      <div class="filter-row" style="margin-bottom: 6px">
        <div class="filter-group">
          <label>月份：</label>
          <el-select v-model="f.month" size="small" style="width: 120px" @change="onChange">
            <el-option v-for="o in monthOptions" :key="o.v" :label="o.t" :value="o.v" />
          </el-select>
        </div>
        <div class="filter-group">
          <label>部门：</label>
          <el-tree-select v-model="f.dept" :data="ot.deptTreeData.value" node-key="value"
                          :props="{ label: 'label', children: 'children' }" check-strictly clearable
                          size="small" style="width: 280px" @change="onChange" />
        </div>
        <div class="filter-group">
          <el-input v-model="f.keyword" placeholder="姓名/工号/事由" size="small" clearable
                    style="width: 180px" @keyup.enter="search" />
        </div>
        <div class="filter-group">
          <label>类型：</label>
          <el-select v-model="f.workType" size="small" style="width: 130px" @change="onChange">
            <el-option label="全部" value="all" />
            <el-option v-for="w in ot.workTypes.value" :key="w" :label="w" :value="w" />
          </el-select>
        </div>
        <div class="filter-group">
          <label>状态：</label>
          <el-select v-model="f.status" size="small" style="width: 110px" @change="onChange">
            <el-option label="全部" value="all" />
            <el-option label="已提交" value="submitted" />
            <el-option label="已汇总" value="grouped" />
            <el-option label="已打印" value="printed" />
            <el-option label="已核销" value="verified" />
          </el-select>
        </div>
      </div>
      <div class="filter-row">
        <div class="filter-group">
          <el-select v-model="f.maxDepth" size="small" style="width: 120px" @change="onChange">
            <el-option label="全部下级" value="" />
            <el-option label="本级" value="0" />
            <el-option v-for="i in 5" :key="i" :label="`本级+${i}`" :value="String(i)" />
          </el-select>
        </div>
        <el-button size="small" type="primary" @click="search">搜索</el-button>
        <el-button size="small" @click="clearFilter">重置</el-button>
        <el-button size="small" @click="toggleSort">{{ sortByRaw ? '按部门+姓名排序' : '按原始时长排序' }}</el-button>
        <el-button size="small" @click="$refs.sumFile.click()">上传Excel匹配导出</el-button>
        <input ref="sumFile" type="file" accept=".xlsx,.xls" style="display: none" @change="onSumFile" />
        <span class="spacer"></span>
        <span class="badge">合计原始时长：{{ Number(footer.rawHours || 0).toFixed(2) }} h | {{ footer.over36Count || 0 }}人超36h</span>
      </div>
    </el-card>

    <div class="table-card">
      <el-table :data="rows" border size="small" v-loading="loading" height="500"
                @row-click="openDetail">
        <el-table-column prop="deptName" label="部门" width="170" show-overflow-tooltip />
        <el-table-column prop="personnelName" label="姓名" width="85" />
        <el-table-column label="合计原始时长(h)" width="130" align="right">
          <template #default="{ row }">
            <span :style="numStyle(row.personRawTotal)">{{ Number(row.personRawTotal || 0).toFixed(2) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="合计金额(元)" width="120" align="right">
          <template #default="{ row }">
            <span :style="numStyle(row.personAmountTotal)">{{ Math.round(row.personAmountTotal || 0) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="employeeNo" label="工号" width="100" />
        <el-table-column label="加班类型" width="125">
          <template #default="{ row }"><span class="grid-link">{{ row.workType }}</span></template>
        </el-table-column>
        <el-table-column prop="settleType" label="结算" width="70" />
        <el-table-column label="状态" width="84" align="center">
          <template #default="{ row }"><span :class="ot.tagClass(row.status)">{{ ot.tagText(row.status) }}</span></template>
        </el-table-column>
        <el-table-column prop="rawHours" label="本行原始时长(h)" width="130" />
        <el-table-column prop="totalHours" label="加班时长(h)" width="115" />
        <el-table-column label="加班金额(元)" width="120" align="right">
          <template #default="{ row }">{{ row.settleType === '补休' ? '—' : Math.round(row.totalAmount || 0) }}</template>
        </el-table-column>
        <el-table-column prop="entryCount" label="加班次数" width="95" align="center" />
        <el-table-column prop="reasons" label="加班事由" min-width="320" show-overflow-tooltip />
        <el-table-column prop="applyUserName" label="录入人" width="90" />
      </el-table>
      <div class="pager">
        <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
                       :page-sizes="[50, 100, 200]" layout="total, sizes, prev, pager, next, jumper"
                       @current-change="load" @size-change="search" />
      </div>
    </div>

    <!-- 汇总明细抽屉 -->
    <el-drawer v-model="detailVisible" size="90%" class="ot-drawer" :title="detailTitle" destroy-on-close>
      <div class="ad-body">
        <el-tabs v-model="detailTab" @tab-change="loadDetail">
          <el-tab-pane label="明细表格" name="grid">
            <el-table :data="detailRows" border size="small" max-height="480">
              <el-table-column prop="workType" label="加班类型" width="130" />
              <el-table-column prop="workDate" label="日期" width="120" />
              <el-table-column label="时段" width="150">
                <template #default="{ row }">{{ (row.startTime || '').slice(11) }}-{{ (row.endTime || '').slice(11) }}</template>
              </el-table-column>
              <el-table-column prop="rawHours" label="原始时长" width="100" />
              <el-table-column prop="totalHours" label="折算时长" width="100" />
              <el-table-column prop="amount" label="金额" width="90" />
              <el-table-column prop="reason" label="工作内容" min-width="240" />
              <el-table-column label="状态" width="90">
                <template #default="{ row }"><span :class="ot.tagClass(row.status)">{{ ot.tagText(row.status) }}</span></template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="日历看板" name="cal"><CalendarBoard :rows="detailRows" /></el-tab-pane>
          <el-tab-pane label="全部类型看板" name="allcal"><CalendarBoard :rows="allTypeRows" /></el-tab-pane>
        </el-tabs>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, inject, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as api from '@/api/overtime'
import CalendarBoard from '../dialogs/CalendarBoard.vue'

const ot = inject('ot')
const monthOptions = computed(() => {
  const ms = ot.months.value
  const opts = [{ v: 'all', t: '全部' }]
  const years = [...new Set(ms.map((m) => m.slice(0, 4)))]
  years.forEach((y) => opts.push({ v: y, t: `${y} 全年` }))
  ms.forEach((m) => opts.push({ v: m, t: `${m.slice(0, 4)}-${m.slice(4)}` }))
  return opts
})
const f = reactive({ month: '', dept: null, keyword: '', workType: 'all', status: 'all', maxDepth: '' })
const rows = ref([]), total = ref(0), page = ref(1), size = ref(50)
const footer = ref({}), loading = ref(false), sortByRaw = ref(false), suppress = ref(false)
watch(() => ot.currentMonth.value, (m) => { if (m && !f.month) f.month = m }, { immediate: true })

function params() {
  const p = {
    page: page.value, rows: size.value, work_type: f.workType, status: f.status,
    sort_by_raw: sortByRaw.value,
  }
  if (f.month) p.month = f.month
  if (f.dept) p.dept_id = f.dept
  if (f.keyword) p.keyword = f.keyword
  if (f.maxDepth !== '') p.max_depth = f.maxDepth
  return p
}
async function load() {
  loading.value = true
  try {
    const r = await api.getSummary(params())
    rows.value = r.rows || []
    total.value = r.total || 0
    footer.value = (r.footer || [])[0] || {}
  } finally { loading.value = false }
}
function search() { page.value = 1; load() }
function onChange() { if (!suppress.value) search() }
function clearFilter() {
  suppress.value = true
  try {
    f.month = ot.currentMonth.value
    f.dept = null; f.keyword = ''; f.workType = 'all'; f.status = 'all'; f.maxDepth = ''
  } finally { suppress.value = false }
  search()
}
function toggleSort() { sortByRaw.value = !sortByRaw.value; search() }
function numStyle(v) {
  const n = Number(v || 0)
  if (n > 36) return 'color:#d9534f;font-weight:bold'
  if (n >= 25) return 'color:#f0ad4e;font-weight:bold'
  return ''
}
watch(() => ot.tick.value, () => load())
onMounted(load)

// 明细抽屉
const detailVisible = ref(false), detailTab = ref('grid'), detailTitle = ref('')
const detailRows = ref([]), allTypeRows = ref([])
let detailCtx = {}
function openDetail(row) {
  detailCtx = row
  detailTitle.value = `${row.personnelName} - ${row.workType}`
  detailTab.value = 'grid'
  detailVisible.value = true
  loadDetail()
}
async function loadDetail() {
  if (!detailCtx.personnelId) return
  const base = {
    personnelId: detailCtx.personnelId, month: f.month === 'all' ? '' : f.month,
    status: f.status, keyword: f.keyword,
  }
  if (detailTab.value === 'allcal') {
    allTypeRows.value = (await api.getSummaryDetail({ ...base, work_type: 'all' })).rows || []
  } else {
    detailRows.value = (await api.getSummaryDetail({ ...base, work_type: detailCtx.workType })).rows || []
  }
}

async function onSumFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  if (!f.month || f.month === 'all') { e.target.value = ''; return ElMessage.warning('请先选择月份') }
  if (!f.workType || f.workType === 'all') { e.target.value = ''; return ElMessage.warning('请先选择具体加班类型') }
  const fd = new FormData()
  fd.append('file', file)
  fd.append('month', f.month)
  fd.append('workType', f.workType)
  const r = await api.uploadSummary(fd)
  ElMessage.success(`已导出：匹配 ${r.matched} 人，未匹配 ${r.unmatched} 人`)
  e.target.value = ''
}
</script>
