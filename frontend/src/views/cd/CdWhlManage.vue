<script setup>
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getCdDicts, listCdWhl, generateCdWhl, getCdWhlRemark, saveCdWhlRemark,
  setCdLock, exportCdWhl,
} from '@/api/cd'

function curMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}
function fmt(v, len = 10) { return v ? String(v).slice(0, len) : '' }

// ===== 公共字典 =====
const dicts = reactive({
  departments: [], guancai: [], guanjing: [], daxiu_lb: [], bdlb: [],
  report_month: '', report_date: '', bt: '', is_locked: false, can_lock: false,
})
const bt = ref('')

// ===== 列表与筛选(rq 一律 YYYY-MM) =====
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const footer = ref({})
const page = ref(1)
const size = ref(30)
const filters = reactive({ keyword: '', rq: '', bmid: null })

function buildParams(withPage = true) {
  const p = {}
  if (withPage) { p.page = page.value; p.size = size.value }
  p.rq = filters.rq
  if (filters.keyword) p.keyword = filters.keyword
  if (filters.bmid) p.bmid = filters.bmid
  return p
}
async function load() {
  loading.value = true
  try {
    const data = await listCdWhl(buildParams())
    rows.value = data.items || []
    total.value = data.total || 0
    footer.value = data.footer || {}
    if (data.bt) bt.value = data.bt
  } finally { loading.value = false }
}
function search() { page.value = 1; load() }

// 合计行:直接用后端 footer(照旧 Getxz 是当前页合计,非筛选全量),备注列写「合计」
function summaryMethod({ columns }) {
  return columns.map((c) => {
    if (c.property === 'bz') return '合计'
    const v = footer.value[c.property]
    return v === undefined || v === null ? '' : v
  })
}

// 多列页面 <1920px 隐次要列,避免横向滚动条(照 ClFeiyongManage)
const wide = ref(window.innerWidth >= 1920)
function onResize() { wide.value = window.innerWidth >= 1920 }

onMounted(async () => {
  window.addEventListener('resize', onResize)
  const d = await getCdDicts()
  Object.assign(dicts, d)
  filters.rq = dicts.report_month || curMonth()
  bt.value = dicts.bt || ''
  load()
})
onBeforeUnmount(() => window.removeEventListener('resize', onResize))

// ===== 勾选 =====
const selection = ref([])
function onSelectionChange(v) { selection.value = v }
function requireOne() {
  if (selection.value.length !== 1) { ElMessage.warning('请选中且仅选中一条记录'); return null }
  return selection.value[0]
}

// ===== 生成报表 =====
const generating = ref(false)
async function doGenerate() {
  await ElMessageBox.confirm('确定要生成当月报表吗？', '提示', { type: 'warning' })
  generating.value = true
  try {
    await generateCdWhl(filters.rq)
    ElMessage.success('报表已生成')
    load()
  } finally { generating.value = false }
}

// ===== 锁定报表 =====
async function onLockChange(val) {
  try {
    await setCdLock(val)
    ElMessage.success(val ? '报表已锁定' : '报表已解锁')
    load()
  } catch {
    dicts.is_locked = !val
  }
}

// ===== 编辑备注 =====
const remarkOpen = ref(false)
const remarkId = ref(null)
const remarkForm = reactive({ bz: '' })
const remarkSaving = ref(false)
async function openRemark(row) {
  const d = await getCdWhlRemark(row.id)
  remarkId.value = row.id
  remarkForm.bz = d.bz || ''
  remarkOpen.value = true
}
async function saveRemark() {
  if (remarkSaving.value) return
  remarkSaving.value = true
  try {
    await saveCdWhlRemark({ id: remarkId.value, bz: remarkForm.bz })
    ElMessage.success('备注已保存')
    remarkOpen.value = false
    load()
  } finally { remarkSaving.value = false }
}

// ===== 导出 =====
const exporting = ref(false)
async function doExport() {
  exporting.value = true
  try {
    await exportCdWhl(buildParams(false))
    ElMessage.success('已导出传导设备完好率汇总表')
  } finally { exporting.value = false }
}
</script>

<template>
  <div class="cdwhl-page">
    <el-card shadow="never" class="filter-card">
      <div class="page-title">{{ bt }}传导设备完好率统计汇总表</div>
      <el-form inline class="filter-form">
        <el-form-item>
          <el-input v-model="filters.keyword" placeholder="输入备注模糊查询"
            clearable style="width: 220px" @keyup.enter="search" @change="search" />
        </el-form-item>
        <el-form-item label="报表月份">
          <el-date-picker v-model="filters.rq" type="month" value-format="YYYY-MM"
            format="YYYY年MM月" :editable="false" placeholder="选择月份"
            style="width: 140px" @change="search" />
        </el-form-item>
        <el-form-item label="部门">
          <el-select v-model="filters.bmid" placeholder="===选择部门===" clearable filterable
            style="width: 150px" @change="search">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="dicts.can_lock" label="锁定报表">
          <el-switch v-model="dicts.is_locked" @change="onLockChange" />
        </el-form-item>
      </el-form>
    </el-card>

    <div class="toolbar">
      <el-button type="primary" size="small" :loading="generating" @click="doGenerate">生成报表</el-button>
      <el-button size="small" @click="() => { const r = requireOne(); if (r) openRemark(r) }">编辑备注</el-button>
      <el-button size="small" :loading="exporting" @click="doExport">导出EXCEL</el-button>
      <span class="toolbar-hint">共 {{ total }} 条 · 双击行可编辑备注</span>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe size="small" row-key="id"
      height="calc(100vh - 290px)" show-summary :summary-method="summaryMethod"
      @selection-change="onSelectionChange" @row-dblclick="openRemark">
      <el-table-column type="selection" width="42" />
      <el-table-column prop="bz" label="备注" min-width="160" show-overflow-tooltip />
      <el-table-column v-if="wide" prop="id" label="编号" width="66" />
      <el-table-column prop="bumen" label="部门" width="100" show-overflow-tooltip />
      <el-table-column prop="bbdate" label="报表日期" width="100">
        <template #default="{ row }">{{ fmt(row.bbdate) }}</template>
      </el-table-column>
      <el-table-column prop="ts" label="设备台数" width="84" align="right" />
      <el-table-column prop="sytss" label="实有台时数" width="96" align="right" />
      <el-table-column prop="decgztss" label="故障台时数" width="96" align="right" />
      <el-table-column prop="decwhtss" label="完好台时数" width="96" align="right" />
      <el-table-column prop="whl" label="设备完好率%" width="104" align="right" />
      <el-table-column prop="xzts" label="本月新增设备台数" width="100" align="right" />
      <el-table-column prop="bfts" label="本月报废设备台数" width="100" align="right" />
      <el-table-column prop="dcts" label="本月调出设备台数" width="100" align="right" />
      <el-table-column prop="tyts" label="本月停用设备台数" width="100" align="right" />
      <el-table-column v-if="wide" prop="finadate" label="生成日期" width="150">
        <template #default="{ row }">{{ fmt(row.finadate, 19) }}</template>
      </el-table-column>
      <el-table-column v-if="wide" prop="username" label="操作员" width="90" />
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[30, 60, 120]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>

    <!-- 编辑备注 -->
    <el-dialog v-model="remarkOpen" title="编辑备注" width="480px" top="12vh"
      class="std-dialog" :close-on-click-modal="false">
      <el-form :model="remarkForm" label-width="70px">
        <el-form-item label="备注">
          <el-input v-model="remarkForm.bz" type="textarea" :rows="5" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="remarkOpen = false">取消</el-button>
        <el-button type="primary" :loading="remarkSaving" @click="saveRemark">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.cdwhl-page { display: flex; flex-direction: column; gap: 10px; }
.filter-card :deep(.el-card__body) { padding: 10px 14px; }
.page-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 12px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.toolbar :deep(.el-button) { height: 32px; }
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }
</style>
