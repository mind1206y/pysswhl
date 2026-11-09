<template>
  <div>
    <el-card class="filter-card" shadow="never">
      <div class="filter-row">
        <div class="filter-group">
          <label>搜索：</label>
          <el-input v-model="filters.keyword" placeholder="姓名" size="small" clearable style="width: 140px" @keyup.enter="search" />
        </div>
        <div class="filter-group">
          <label>月份：</label>
          <el-select v-model="filters.month" size="small" style="width: 110px" @change="onFilterChange">
            <el-option v-for="m in ot.months.value" :key="m" :label="m" :value="m" />
          </el-select>
        </div>
        <div class="filter-group">
          <label>状态：</label>
          <el-select v-model="filters.status" size="small" style="width: 120px" @change="onFilterChange">
            <el-option label="全部" value="all" />
            <el-option v-for="(t, k) in statusOptions" :key="k" :label="t" :value="k" />
          </el-select>
        </div>
      </div>
    </el-card>

    <div class="toolbar">
      <el-button size="small" type="primary" @click="search">搜索</el-button>
      <el-button size="small" @click="clearSearch">重置</el-button>
      <el-button size="small" @click="batchSubmit">批量提交</el-button>
      <el-button size="small" @click="batchDelete">批量删除</el-button>
      <el-button size="small" type="primary" plain @click="newRecord">新建加班记录</el-button>
      <el-button size="small" type="primary" plain style="font-weight: bold" @click="ot.openBatch()">批量新建</el-button>
      <el-button size="small" @click="templateVisible = true">下载导入模板</el-button>
      <el-button size="small" @click="$refs.importFile.click()">批量导入</el-button>
      <el-button size="small" @click="doExportQx">导出维抢修审批</el-button>
      <el-button size="small" v-if="ot.perms.value.is_admin" @click="doExportRecords">导出加班记录</el-button>
      <input ref="importFile" type="file" accept=".xlsx,.xls" style="display: none" @change="onImportFile" />
    </div>

    <div class="table-card">
      <el-table :data="rows" border size="small" v-loading="loading" row-key="id" height="520"
                @selection-change="(v) => (selected = v)">
        <el-table-column type="selection" width="42" />
        <el-table-column prop="apply_no" label="编号" width="130">
          <template #default="{ row }"><span class="grid-link" @click="viewRecord(row)">{{ row.apply_no }}</span></template>
        </el-table-column>
        <el-table-column prop="personnelName" label="姓名" width="75" align="center" />
        <el-table-column prop="deptName" label="部门" width="180" show-overflow-tooltip />
        <el-table-column prop="apply_month" label="月份" width="72" align="center" />
        <el-table-column prop="work_type" label="加班类型" width="110" align="center" />
        <el-table-column label="结算" width="68" align="center">
          <template #default="{ row }">
            <span :style="{ color: row.settle_type === '补休' ? '#ff9800' : '#666' }">{{ row.settle_type || '加班费' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="total_hours" label="总时长(h)" width="88" align="center" />
        <el-table-column label="原始时长(h)" width="96" align="center">
          <template #default="{ row }">{{ Number(row.rawHours || 0).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="金额" width="80" align="center">
          <template #default="{ row }">{{ row.settle_type === '补休' ? '—' : Math.round(row.overtimeAmount || 0) }}</template>
        </el-table-column>
        <el-table-column label="加班明细" min-width="300">
          <template #default="{ row }">
            <span class="entry-by">录入人：{{ row.applyUserName }}</span>
            <span class="grid-link" @click="openDetail(row)" v-html="row.timeSlots || '查看明细'"></span>
          </template>
        </el-table-column>
        <el-table-column prop="create_time" label="操作时间" width="140" align="center" />
        <el-table-column label="状态" width="82" align="center">
          <template #default="{ row }"><span :class="ot.tagClass(row.status)">{{ ot.tagText(row.status) }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <template v-if="row.status === 'draft'">
                <span class="grid-link" @click="editRecord(row)">编辑</span>
                <span class="grid-danger" @click="removeRecord(row)">删除</span>
                <span class="grid-link" @click="submitOne(row)">提交</span>
              </template>
              <span v-else-if="row.status === 'submitted'" class="grid-link" @click="recallOne(row)">撤回</span>
              <span v-else class="grid-link" @click="viewRecord(row)">查看</span>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
                       :page-sizes="[50, 100, 200]" layout="total, sizes, prev, pager, next, jumper"
                       @current-change="load" @size-change="search" />
      </div>
    </div>

    <!-- 明细抽屉 -->
    <el-drawer v-model="detailVisible" size="90%" class="ot-drawer" :title="detailTitle" destroy-on-close>
      <div class="ad-body">
        <el-tabs v-model="detailTab">
          <el-tab-pane label="明细表格" name="grid">
            <el-table :data="detailRows" border size="small" max-height="480">
              <el-table-column prop="workType" label="加班类型" width="130" />
              <el-table-column prop="workDate" label="日期" width="120" />
              <el-table-column label="时段" width="160">
                <template #default="{ row }">{{ (row.startTime || '').slice(11) }}-{{ (row.endTime || '').slice(11) }}</template>
              </el-table-column>
              <el-table-column prop="rawHours" label="原始时长" width="100" />
              <el-table-column prop="totalHours" label="折算时长" width="100" />
              <el-table-column prop="amount" label="金额" width="90" />
              <el-table-column prop="multiplier" label="倍数" width="80" />
              <el-table-column prop="reason" label="工作内容" min-width="220" />
              <el-table-column label="操作" width="80" v-if="detailEditable">
                <template #default="{ row }"><span class="grid-danger" @click="deleteDetailEntry(row)">删除</span></template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="日历看板" name="cal">
            <CalendarBoard :rows="detailRows" />
          </el-tab-pane>
        </el-tabs>
      </div>
    </el-drawer>

    <!-- 导入模板选人 -->
    <el-dialog v-model="templateVisible" title="选择人员下载模板" width="700px" class="ot-dialog" append-to-body>
      <div class="filter-row" style="margin-bottom: 8px">
        <div class="filter-group">
          <label>部门：</label>
          <el-tree-select v-model="tplDept" :data="ot.deptTreeData.value" node-key="value"
                          :props="{ label: 'label', children: 'children' }" check-strictly clearable
                          size="small" style="width: 280px" />
        </div>
        <el-input v-model="tplSearch" placeholder="搜索姓名/工号" size="small" clearable style="width: 170px" />
      </div>
      <div class="transfer-body">
        <div class="transfer-panel">
          <div class="transfer-title">待选人员</div>
          <div class="transfer-list">
            <div v-for="p in tplLeft" :key="p.id" style="padding: 3px">
              <el-checkbox :model-value="tplSelected.includes(p.id)" @change="(v) => toggleTpl(p.id, v)">
                {{ p.name }} <span class="e-tip">{{ p.employee_no }}</span>
              </el-checkbox>
            </div>
          </div>
        </div>
        <div class="transfer-btns">
          <el-button size="small" @click="tplSelected = tplLeft.map((p) => p.id).concat(tplSelected)">›</el-button>
          <el-button size="small" @click="tplSelected = []">‹</el-button>
        </div>
        <div class="transfer-panel">
          <div class="transfer-title">已选人员（{{ new Set(tplSelected).size }} 人）</div>
          <div class="transfer-list">
            <div v-for="id in [...new Set(tplSelected)]" :key="id" style="padding: 3px; font-size: 12px; display: flex; justify-content: space-between">
              <span>{{ nameOf(id) }}</span><span class="grid-danger" @click="tplSelected = tplSelected.filter((x) => x !== id)">×</span>
            </div>
          </div>
        </div>
      </div>
      <template #footer>
        <el-button @click="templateVisible = false">关闭</el-button>
        <el-button type="primary" @click="doDownloadTemplate">下载模板</el-button>
      </template>
    </el-dialog>

    <!-- 导入结果 -->
    <el-dialog v-model="importResultVisible" title="导入结果" width="640px" class="ot-dialog" append-to-body>
      <div style="margin-bottom: 8px">{{ importResult.Msg }}</div>
      <el-table v-if="importResult?.Errors?.length" :data="importResult.Errors" border size="small" max-height="360">
        <el-table-column prop="Row" label="行号" width="80" />
        <el-table-column prop="Name" label="姓名" width="120" />
        <el-table-column prop="Msg" label="说明" />
      </el-table>
      <template #footer><el-button type="primary" @click="importResultVisible = false">知道了</el-button></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, inject, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as api from '@/api/overtime'
import CalendarBoard from '../dialogs/CalendarBoard.vue'

const ot = inject('ot')
const statusOptions = {
  draft: '草稿', submitted: '已提交', grouped: '已汇总', printed: '已打印',
  verified: '已核销', pending: '审批中', approved: '已通过', rejected: '已驳回',
}
const filters = reactive({ keyword: '', month: '', status: 'all' })
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(50)
const loading = ref(false)
const selected = ref([])
const suppress = ref(false)

function params() {
  const p = { page: page.value, rows: size.value }
  if (filters.keyword) p.keyword = filters.keyword
  if (filters.month) p.month = filters.month
  if (filters.status && filters.status !== 'all') p.status = filters.status
  return p
}
async function load() {
  loading.value = true
  try {
    const r = await api.listMyRecords(params())
    rows.value = r.rows || []
    total.value = r.total || 0
  } finally { loading.value = false }
}
function search() { page.value = 1; load() }
function onFilterChange() { if (!suppress.value) search() }
function clearSearch() {
  suppress.value = true
  try {
    filters.keyword = ''
    filters.status = 'all'
    filters.month = ot.currentMonth.value   // 与首次加载一致:当前月
  } finally { suppress.value = false }
  search()
}
watch(() => ot.currentMonth.value, (m) => { if (!filters.month) filters.month = m }, { immediate: true })
watch(() => ot.tick.value, () => load())
onMounted(load)

function ids() { return selected.value.map((r) => r.id) }
async function batchSubmit() {
  if (!ids().length) return ElMessage.warning('请先勾选记录')
  await ot.confirm(`确定提交选中的 ${ids().length} 条记录吗？`)
  const r = await api.batchSubmitPersonal(ids())
  ElMessage.success(r.msg); load()
}
async function batchDelete() {
  if (!ids().length) return ElMessage.warning('请先勾选记录')
  await ot.confirm(`确定删除选中的 ${ids().length} 条记录吗？`)
  const r = await api.batchDeletePersonal(ids())
  ElMessage.success(r.msg); load()
}
async function submitOne(row) {
  const r = await api.submitPersonal(row.id)
  ElMessage.success(r.msg); load()
}
async function recallOne(row) {
  const r = await api.recallPersonal(row.id)
  ElMessage.success(r.msg); load()
}
async function removeRecord(row) {
  await ot.confirm('确定删除该记录吗？')
  await api.deletePersonal(row.id)
  ElMessage.success('删除成功'); load()
}
function newRecord() {
  ot.openEntry({ mode: 'personal', onSaved: load })
}
function editRecord(row) {
  ot.openEntry({ mode: 'personal', detailId: row.id, applyMonth: row.apply_month,
                 workType: row.work_type, settleType: row.settle_type, onSaved: load })
}
function viewRecord(row) {
  if (row.apply_id) ot.openApplyDrawer({ id: row.apply_id })
  else ot.openEntry({ mode: 'personal', detailId: row.id, readonly: true, applyMonth: row.apply_month,
                      workType: row.work_type, settleType: row.settle_type })
}

// ---- 明细抽屉
const detailVisible = ref(false)
const detailTab = ref('grid')
const detailTitle = ref('加班明细')
const detailRows = ref([])
const detailEditable = ref(false)
let detailId = 0
async function openDetail(row) {
  detailId = row.id
  detailTitle.value = `加班明细 - ${row.apply_no}`
  detailEditable.value = row.status === 'draft'
  detailTab.value = 'grid'
  const r = await api.getPersonalDetail(row.id)
  detailRows.value = r.rows || []
  detailVisible.value = true
}
async function deleteDetailEntry(row) {
  await ot.confirm('确定删除该时段吗？')
  await api.deleteEntry(row.entryId)
  ElMessage.success('删除成功')
  const r = await api.getPersonalDetail(detailId)
  detailRows.value = r.rows || []
  if (!detailRows.value.length) detailVisible.value = false
  load()
}

// ---- 导入模板
const templateVisible = ref(false)
const tplDept = ref(null)
const tplSearch = ref('')
const tplSelected = ref([])
const tplLeft = computed(() => {
  const kw = (tplSearch.value || '').trim().toLowerCase()
  return ot.personnel.value.filter((p) => (!tplDept.value || p.dept_id === tplDept.value)
    && (!kw || `${p.name} ${p.employee_no}`.toLowerCase().includes(kw)))
})
function toggleTpl(id, v) { tplSelected.value = v ? [...tplSelected.value, id] : tplSelected.value.filter((x) => x !== id) }
function nameOf(id) { return ot.personnel.value.find((p) => p.id === id)?.name || `ID:${id}` }
async function doDownloadTemplate() {
  const uniq = [...new Set(tplSelected.value)]
  await api.downloadTemplate({
    names: uniq.map(nameOf).join('|'),
    employeeNos: uniq.map((id) => ot.personnel.value.find((p) => p.id === id)?.employee_no || '').join('|'),
  })
  ElMessage.success('模板已下载')
  templateVisible.value = false
}

// ---- 导入 / 导出
const importResultVisible = ref(false)
const importResult = ref({})
async function onImportFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  importResult.value = await api.importPersonalExcel(file)
  importResultVisible.value = true
  e.target.value = ''
  load()
}
async function doExportQx() {
  await api.exportQx({ month: filters.month })
  ElMessage.success('已导出 Excel')
}
async function doExportRecords() {
  await api.exportRecords({ month: filters.month, keyword: filters.keyword })
  ElMessage.success('已导出 Excel')
}
</script>
