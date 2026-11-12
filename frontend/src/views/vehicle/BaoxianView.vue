<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createBaoxian, deleteBaoxian, downloadTemplate, exportBaoxian, getBaoxian,
  getBaoxianDicts, getBxcomList, listBaoxian, searchBaoxianVehicles, updateBaoxian,
  uploadBaoxian,
} from '@/api/baoxian'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const username = computed(() => auth.user?.username || '')

// ===== 字典 =====
const dicts = reactive({ departments: [], years: [], lx: [] })
const bxcoms = ref([]) // 历史保险公司聚合标签(照旧 GetbxcomList)

// ===== 列表与筛选(照旧 GetList) =====
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const tj = ref(0) // 筛选结果合计金额(照旧 footer 合计行,作用于全部筛选行)
const page = ref(1)
const size = ref(30)
const filters = reactive({ keyword: '', year: null, lx: '', dept: null })

function buildParams(withPage = true) {
  const p = {}
  if (withPage) { p.page = page.value; p.size = size.value }
  if (filters.keyword) p.keyword = filters.keyword
  if (filters.year) p.year = filters.year
  if (filters.lx) p.lx = filters.lx
  if (filters.dept) p.dept = filters.dept
  return p
}
async function load() {
  loading.value = true
  try {
    const data = await listBaoxian(buildParams())
    rows.value = data.items
    total.value = data.total
    tj.value = data.tj || 0
  } finally { loading.value = false }
}
function search() { page.value = 1; load() }
function showAll() {
  Object.assign(filters, { keyword: '', year: null, lx: '', dept: null })
  page.value = 1
  load()
}
function money(v) { return v == null ? '' : Number(v).toFixed(2) }

// 合计行(照旧 footer:「合计（元）：」挂在投保金额列)
function summaryMethod({ columns }) {
  return columns.map((col, i) => {
    if (i === 0) return '合计'
    if (col.property === 'jine') return `合计（元）：${Number(tj.value).toFixed(2)}`
    return ''
  })
}

// ===== 车辆下拉(照旧 Getch:用途≠油卡、未删除) =====
const vehicleOptions = ref([])
const vehicleLoading = ref(false)
async function searchVehicles(q) {
  vehicleLoading.value = true
  try { vehicleOptions.value = await searchBaoxianVehicles(q) }
  finally { vehicleLoading.value = false }
}

// ===== 保险类别胶囊(照旧 large-label) =====
const lxPills = ['商业车险', '交强险']

// ===== 添加 / 编辑(照旧 addDiv/editDiv) =====
const dialog = ref(false)
const editingId = ref(null)
const saving = ref(false)
const formRef = ref()
const blankForm = () => ({
  lx: '商业车险', cheid: null, tbdate: '', bxcom: '', bdnumber: '',
  dqdate: '', jingshou: '', jine: null, bz: '',
})
const form = reactive(blankForm())
const rules = {
  cheid: [{ required: true, message: '请选择有效车号', trigger: 'change' }],
  tbdate: [{ required: true, message: '请选择投保日期', trigger: 'change' }],
  bxcom: [{ required: true, message: '请输入保险公司', trigger: 'blur' }],
  bdnumber: [{ required: true, message: '请输入保单号', trigger: 'blur' }],
  dqdate: [{ required: true, message: '请选择保险到期', trigger: 'change' }],
  jingshou: [{ required: true, message: '请输入经手人', trigger: 'blur' }],
  jine: [{ required: true, message: '请输入投保金额', trigger: 'blur' }],
}

async function openCreate() {
  editingId.value = null
  Object.assign(form, blankForm())
  await Promise.all([searchVehicles(''), loadBxcoms()])
  dialog.value = true
}

async function loadBxcoms() {
  if (bxcoms.value.length) return
  try {
    const list = await getBxcomList()
    bxcoms.value = list.map((x) => x.duixiang)
  } catch { bxcoms.value = [] }
}

// 编辑回显:历史「商业险」写法按关键字归并到「商业车险」(照旧)
function normalizeLx(v) {
  const s = (v || '').toString()
  if (s === '商业车险' || s === '交强险') return s
  if (s.indexOf('商业') !== -1) return '商业车险'
  if (s.indexOf('交强') !== -1) return '交强险'
  return s
}

async function openEdit(row) {
  // 非登记人不可编辑(登记人为空的历史数据放行,与后端口径一致)
  if (row.djname && row.djname !== username.value) {
    ElMessage.warning('只有登记人才能编辑该记录')
    return
  }
  const data = await getBaoxian(row.id)
  editingId.value = data.id
  Object.assign(form, blankForm(), {
    lx: normalizeLx(data.lx),
    cheid: data.cheid,
    tbdate: data.tbdate || '',
    bxcom: data.bxcom || '',
    bdnumber: data.bdnumber || '',
    dqdate: data.dqdate || '',
    jingshou: data.jingshou || '',
    jine: data.jine,
    bz: data.bz || '',
  })
  vehicleOptions.value = [{ id: data.cheid, chehao: data.chehao || '' }]
  await Promise.all([searchVehicles(''), loadBxcoms()])
  dialog.value = true
}

function buildPayload() {
  return {
    cheid: form.cheid,
    tbdate: form.tbdate || null,
    bdnumber: form.bdnumber,
    lx: form.lx,
    jine: form.jine === '' ? null : form.jine,
    bxcom: form.bxcom,
    dqdate: form.dqdate || null,
    jingshou: form.jingshou,
    bz: form.bz,
  }
}
async function submitForm() {
  if (saving.value) return  // 防双击重复提交
  saving.value = true
  try {
    await formRef.value.validate()
    if (editingId.value) await updateBaoxian(editingId.value, buildPayload())
    else await createBaoxian(buildPayload())
    ElMessage.success(editingId.value ? '修改成功' : '添加成功')
    dialog.value = false
    load()
  } finally { saving.value = false }
}

// ===== 删除(照旧 Deletegz:无本人限制) =====
function requireOne() {
  if (selection.value.length !== 1) { ElMessage.warning('请选中且仅选中一条记录'); return null }
  return selection.value[0]
}
async function doDelete() {
  const row = requireOne(); if (!row) return
  await ElMessageBox.confirm('确定要删除数据吗', '提示', { type: 'warning' })
  await deleteBaoxian(row.id)
  ElMessage.success('删除成功')
  load()
}

// ===== 上传导入(照旧 UploadFile:.xlsx 且文件名含「保险」) =====
const fileInput = ref()
function uploadFile() { fileInput.value?.click() }
async function doUpload(ev) {
  const file = ev.target.files?.[0]
  ev.target.value = ''
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.xlsx') || !file.name.includes('保险')) {
    ElMessage.error('文件名须包含“保险”且为 .xlsx 文件')
    return
  }
  loading.value = true
  try {
    const summary = await uploadBaoxian(file)
    ElMessage({ message: summary, type: summary.includes('失败') ? 'error' : 'success' })
    load()
    bxcoms.value = [] // 有新保险公司时刷新聚合标签
  } finally { loading.value = false }
}

const selection = ref([])
function onSelectionChange(v) { selection.value = v }

onMounted(async () => {
  const d = await getBaoxianDicts()
  Object.assign(dicts, d)
  load()
})
</script>

<template>
  <div class="baoxian-page">
    <!-- 查询条件(照旧 toolbar 筛选区) -->
    <el-card shadow="never" class="filter-card">
      <div class="filter-title">车辆保险信息表</div>
      <el-form inline class="filter-form">
        <el-form-item label="关键字">
          <el-input v-model="filters.keyword" placeholder="保险公司、车号" clearable
            style="width: 220px" @keyup.enter="search" />
        </el-form-item>
        <el-form-item label="年度">
          <el-select v-model="filters.year" placeholder="选择年度" clearable
            style="width: 110px">
            <el-option v-for="y in dicts.years" :key="y" :label="`${y}年`" :value="y" />
          </el-select>
        </el-form-item>
        <el-form-item label="保险种类">
          <el-select v-model="filters.lx" placeholder="（全部）" clearable style="width: 120px">
            <el-option v-for="x in dicts.lx" :key="x" :label="x" :value="x" />
          </el-select>
        </el-form-item>
        <el-form-item label="部门">
          <el-select v-model="filters.dept" placeholder="（全部部门）" clearable filterable
            style="width: 160px">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
          <el-button @click="showAll">显示全部</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 工具栏(照旧 toolbar:添加保单/编辑/删除/下载记录/上传保险数据/模板下载/显示全部) -->
    <div class="toolbar">
      <el-button type="primary" size="small" @click="openCreate">添加保单</el-button>
      <el-button size="small" @click="() => { const r = requireOne(); if (r) openEdit(r) }">编辑</el-button>
      <el-button size="small" @click="doDelete">删除</el-button>
      <el-button size="small" @click="exportBaoxian(buildParams(false))">下载记录</el-button>
      <el-button size="small" @click="uploadFile">上传保险数据</el-button>
      <el-button size="small" @click="downloadTemplate">模板下载</el-button>
      <span class="toolbar-hint">共 {{ total }} 条 · 合计（元）：{{ Number(tj).toFixed(2) }} · 双击行可编辑</span>
    </div>
    <input ref="fileInput" type="file" accept=".xlsx" style="display: none" @change="doUpload">

    <!-- 主表格(照旧 datagrid 13 列 + footer 合计行) -->
    <el-table v-loading="loading" :data="rows" border stripe size="small"
      height="calc(100vh - 300px)" row-key="id" show-summary :summary-method="summaryMethod"
      @selection-change="onSelectionChange" @row-dblclick="openEdit">
      <el-table-column type="selection" width="42" />
      <el-table-column prop="id" label="编号" width="70" />
      <el-table-column prop="bumen" label="部门" width="110" show-overflow-tooltip />
      <el-table-column prop="chehao" label="车号" width="120" show-overflow-tooltip />
      <el-table-column prop="tbdate" label="投保日期" width="105" />
      <el-table-column prop="lx" label="保险种类" width="95" />
      <el-table-column prop="jine" label="投保金额" width="105" align="right">
        <template #default="{ row }">{{ money(row.jine) }}</template>
      </el-table-column>
      <el-table-column prop="bxcom" label="保险公司" min-width="130" show-overflow-tooltip />
      <el-table-column prop="bz" label="备注" min-width="120" show-overflow-tooltip />
      <el-table-column prop="jingshou" label="经手人" width="90" show-overflow-tooltip />
      <el-table-column prop="djdate" label="登记日期" width="160">
        <template #default="{ row }">{{ row.djdate ? String(row.djdate).slice(0, 16) : '' }}</template>
      </el-table-column>
      <el-table-column prop="bdnumber" label="保单号" min-width="160" show-overflow-tooltip />
      <el-table-column prop="dqdate" label="保险到期" width="105" />
      <el-table-column prop="djname" label="登记人" width="90" show-overflow-tooltip />
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[30, 60, 120]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>

    <!-- 添加 / 编辑(照旧 addDiv/editDiv 字段顺序;类别胶囊 + 历史公司标签) -->
    <el-dialog v-model="dialog" :title="editingId ? '编辑数据' : '添加保单'" width="520px"
      class="std-dialog" :close-on-click-modal="false">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="112px">
        <el-form-item label="保险类别：">
          <div class="pill-group">
            <label v-for="x in lxPills" :key="x" class="large-label"
              :class="{ 'lg-checked': form.lx === x }">
              <input v-model="form.lx" type="radio" name="lx" :value="x" class="large-radio">{{ x }}
            </label>
          </div>
        </el-form-item>
        <el-form-item label="车号：" prop="cheid">
          <el-select v-model="form.cheid" filterable remote :remote-method="searchVehicles"
            :loading="vehicleLoading" placeholder="输入车号搜索" style="width: 100%">
            <el-option v-for="o in vehicleOptions" :key="o.id" :label="o.chehao" :value="o.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="投保日期：" prop="tbdate">
          <el-date-picker v-model="form.tbdate" type="date" value-format="YYYY-MM-DD"
            placeholder="选择投保日期" style="width: 100%" />
        </el-form-item>
        <el-form-item label="保险公司：" prop="bxcom">
          <el-select v-model="form.bxcom" filterable allow-create default-first-option
            placeholder="选择或直接输入新公司" style="width: 100%">
            <el-option v-for="x in bxcoms" :key="x" :label="x" :value="x" />
          </el-select>
        </el-form-item>
        <el-form-item label="保单号：" prop="bdnumber">
          <el-input v-model="form.bdnumber" placeholder="请输入保单号" />
        </el-form-item>
        <el-form-item label="保险到期：" prop="dqdate">
          <el-date-picker v-model="form.dqdate" type="date" value-format="YYYY-MM-DD"
            placeholder="选择保险到期" style="width: 100%" />
        </el-form-item>
        <el-form-item label="经手人：" prop="jingshou">
          <el-input v-model="form.jingshou" placeholder="请输入经手人" />
        </el-form-item>
        <el-form-item label="投保金额(元)：" prop="jine">
          <el-input-number v-model="form.jine" :precision="2" :min="0"
            controls-position="right" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注：">
          <el-input v-model="form.bz" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.baoxian-page { display: flex; flex-direction: column; gap: 10px; }
.filter-card :deep(.el-card__body) { padding: 10px 14px; }
.filter-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 12px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }

/* 保险类别胶囊单选(照旧 large-label,配色与主题一致) */
.pill-group { display: flex; align-items: center; }
.large-label {
  display: inline-flex; align-items: center;
  padding: 5px 14px; font-size: 14px; cursor: pointer; margin-right: 10px;
  border: 1px solid #dfe6ee; border-radius: 16px; background: #fff;
  transition: all 0.15s;
}
.large-label:hover { background: rgba(83, 58, 253, 0.06); border-color: #b9b9f9; }
.large-label.lg-checked {
  background: rgba(83, 58, 253, 0.10); border-color: #533afd;
  color: #4434d4; font-weight: 600;
}
.large-radio { margin-right: 6px; cursor: pointer; }
</style>
