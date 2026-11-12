<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createClFeiyong, deleteClFeiyong, exportClFeiyong, getClFeiyong,
  getClFeiyongDicts, getClFeiyongUnits, getClFeiyongVehicles,
  listClFeiyong, updateClFeiyong,
} from '@/api/clfeiyong'

// ===== 字典 =====
const dicts = reactive({ years: [], categories: [] })

// ===== 列表与筛选(照旧 GetList:年度 / 类别 / 关键字) =====
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const sum = ref(0)
const page = ref(1)
const size = ref(30)
const filters = reactive({ keyword: '', year: '', lx: '' })

function buildParams(withPage = true) {
  const p = {}
  if (withPage) { p.page = page.value; p.size = size.value }
  if (filters.keyword) p.keyword = filters.keyword
  if (filters.year) p.year = filters.year
  if (filters.lx) p.lx = filters.lx
  return p
}
async function load() {
  loading.value = true
  try {
    const data = await listClFeiyong(buildParams())
    rows.value = data.items
    total.value = data.total
    sum.value = data.sum || 0
  } finally { loading.value = false }
}
function search() { page.value = 1; load() }
function resetFilters() {
  Object.assign(filters, { keyword: '', year: '', lx: '' })
  search()
}
function money(v) { return v === null || v === undefined || v === '' ? '' : Number(v).toFixed(2) }
function fmt(v, len = 10) { return v ? String(v).slice(0, len) : '' }
function summaryMethod({ columns }) {
  return columns.map((c) => {
    if (c.property === 'lx') return '合计（元）：'
    if (c.property === 'jine') return sum.value.toFixed(2)
    return ''
  })
}

// 15 列固定宽合计 ~1588px,内容区在 1600px 窗口下只有 ~1360px:
// 与 Gongdan 同口径,<1920px 隐藏登记日期/最后操作日期两列,避免横向滚动条
const wide = ref(window.innerWidth >= 1920)
function onResize() { wide.value = window.innerWidth >= 1920 }

onMounted(async () => {
  window.addEventListener('resize', onResize)
  const [d, v] = await Promise.all([getClFeiyongDicts(), getClFeiyongVehicles()])
  Object.assign(dicts, d)
  vehicleOptions.value = v
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

// ===== 车辆下拉 / 收费单位联想(照旧 Getch / Getzd) =====
const vehicleOptions = ref([])
function ensureVehicle(id, chehao) {
  if (id && !vehicleOptions.value.some((o) => o.id === id)) {
    vehicleOptions.value = [{ id, value: chehao || '', chehao: chehao || '' }, ...vehicleOptions.value]
  }
}
async function fetchUnits(q, cb) {
  if (!q) { cb([]); return }
  try { cb(await getClFeiyongUnits(q)) } catch { cb([]) }
}

// ===== 添加 / 编辑(照旧 #addDiv / #editDiv) =====
const dialog = ref(false)
const editingId = ref(null)
const saving = ref(false)
const formRef = ref()
const blankForm = () => ({
  cheid: null, lx: '洗车', dw: '', fangshi: '', jingshou: '',
  feiyongdate: '', jine: null, bz: '',
})
const form = reactive(blankForm())
const rules = {
  cheid: [{ required: true, message: '请选择有效车号', trigger: 'change' }],
  lx: [{ required: true, message: '请选择费用类别', trigger: 'change' }],
  feiyongdate: [{ required: true, message: '请选择费用日期', trigger: 'change' }],
  jine: [{ required: true, message: '请输入金额', trigger: 'blur' }],
  fangshi: [{ required: true, message: '请输入收费方式', trigger: 'blur' }],
  jingshou: [{ required: true, message: '请输入经手人', trigger: 'blur' }],
}

function openCreate() {
  editingId.value = null
  Object.assign(form, blankForm())
  dialog.value = true
  nextTick(() => formRef.value?.clearValidate())
}
async function openEdit(row) {
  const data = await getClFeiyong(row.id)
  editingId.value = data.id
  Object.assign(form, blankForm(), {
    cheid: data.cheid, lx: data.lx || '洗车', dw: data.dw || '',
    fangshi: data.fangshi || '', jingshou: data.jingshou || '',
    feiyongdate: data.feiyongdate || '', jine: data.jine, bz: data.bz || '',
  })
  ensureVehicle(data.cheid, data.chehao)
  dialog.value = true
  nextTick(() => formRef.value?.clearValidate())
}
function buildPayload() {
  return {
    cheid: form.cheid, lx: form.lx, jine: form.jine === '' ? null : form.jine,
    bz: form.bz, feiyongdate: form.feiyongdate || null, dw: form.dw,
    fangshi: form.fangshi, jingshou: form.jingshou,
  }
}
async function submitForm() {
  if (saving.value) return  // 防双击重复提交
  saving.value = true
  try {
    await formRef.value.validate()
    const payload = buildPayload()
    if (editingId.value) await updateClFeiyong(editingId.value, payload)
    else await createClFeiyong(payload)
    ElMessage.success(editingId.value ? '修改成功' : '添加成功')
    dialog.value = false
    load()
  } finally { saving.value = false }
}

// ===== 删除 / 下载记录(照旧 Deletegz / loadexcel) =====
async function doDelete() {
  const row = requireOne(); if (!row) return
  await ElMessageBox.confirm('确定要删除数据吗', '提示', { type: 'warning' })
  await deleteClFeiyong(row.id)
  ElMessage.success('删除成功')
  load()
}
async function doExport() {
  await exportClFeiyong(buildParams(false))
  ElMessage.success('已导出 Excel')
}
const dialogTitle = computed(() => editingId.value ? '编辑数据' : '添加费用')
</script>

<template>
  <div class="clfeiyong-page">
    <!-- 查询条件(照旧 toolbarRow) -->
    <el-card shadow="never" class="filter-card">
      <div class="filter-title">车辆各类费用表</div>
      <el-form inline class="filter-form">
        <el-form-item>
          <el-input v-model="filters.keyword" placeholder="输入车号或收费单位模糊查询"
            clearable style="width: 260px" @keyup.enter="search" />
        </el-form-item>
        <el-form-item label="年度">
          <el-select v-model="filters.year" placeholder="年度（全部）" clearable style="width: 150px">
            <el-option v-for="y in dicts.years" :key="y" :label="`${y}年`" :value="y" />
          </el-select>
        </el-form-item>
        <el-form-item label="类别">
          <el-select v-model="filters.lx" placeholder="类别（全部）" clearable style="width: 150px">
            <el-option v-for="c in dicts.categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 工具栏(照旧 datagrid toolbar) -->
    <div class="toolbar">
      <el-button type="primary" size="small" @click="openCreate">添加费用</el-button>
      <el-button size="small" @click="() => { const r = requireOne(); if (r) openEdit(r) }">编辑</el-button>
      <el-button size="small" @click="doDelete">删除</el-button>
      <el-button size="small" @click="doExport">下载记录</el-button>
      <span class="toolbar-hint">共 {{ total }} 条 · 合计 {{ money(sum) }} 元 · 双击行可编辑</span>
    </div>

    <!-- 主表格(照旧 GetList 13 列 + footer 合计行) -->
    <el-table v-loading="loading" :data="rows" border stripe size="small"
      height="calc(100vh - 290px)" row-key="id" show-summary :summary-method="summaryMethod"
      @selection-change="onSelectionChange" @row-dblclick="openEdit">
      <el-table-column type="selection" width="42" />
      <el-table-column prop="id" label="编号" width="66" />
      <el-table-column prop="bumen" label="部门" width="120" show-overflow-tooltip />
      <el-table-column prop="chehao" label="车号" width="110" />
      <el-table-column prop="feiyongdate" label="费用日期" width="110">
        <template #default="{ row }">{{ fmt(row.feiyongdate) }}</template>
      </el-table-column>
      <el-table-column prop="lx" label="费用名称" width="100" />
      <el-table-column prop="jine" label="金额" width="100" align="right">
        <template #default="{ row }">{{ money(row.jine) }}</template>
      </el-table-column>
      <el-table-column prop="dw" label="收费单位" min-width="200" show-overflow-tooltip />
      <el-table-column prop="bz" label="备注" min-width="120" show-overflow-tooltip />
      <el-table-column prop="fangshi" label="收费方式" width="100" />
      <el-table-column prop="jingshou" label="经手人" width="100" />
      <el-table-column v-if="wide" prop="djdate" label="登记日期" width="160">
        <template #default="{ row }">{{ fmt(row.djdate, 16) }}</template>
      </el-table-column>
      <el-table-column v-if="wide" prop="zuihoudate" label="最后操作日期" width="160">
        <template #default="{ row }">{{ fmt(row.zuihoudate, 16) }}</template>
      </el-table-column>
      <el-table-column prop="username" label="操作" width="100" />
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[30, 60, 90]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>

    <!-- 添加 / 编辑(照旧 #addDiv / #editDiv 字段顺序) -->
    <el-dialog v-model="dialog" :title="dialogTitle" width="560px" top="7vh"
      class="std-dialog" :close-on-click-modal="false">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="费用类别" prop="lx">
          <el-radio-group v-model="form.lx">
            <el-radio v-for="c in dicts.categories" :key="c" :value="c">{{ c }}</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="车号" prop="cheid">
          <el-select v-model="form.cheid" filterable placeholder="请选择车号" style="width: 100%">
            <el-option v-for="o in vehicleOptions" :key="o.id" :label="o.chehao" :value="o.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="收费单位">
          <el-autocomplete v-model="form.dw" :fetch-suggestions="fetchUnits"
            :trigger-on-focus="false" placeholder="输入可联想历史收费单位" style="width: 100%" />
        </el-form-item>
        <el-form-item label="收费方式" prop="fangshi">
          <el-input v-model="form.fangshi" placeholder="如：转账" />
        </el-form-item>
        <el-form-item label="经手人" prop="jingshou">
          <el-input v-model="form.jingshou" />
        </el-form-item>
        <el-form-item label="日期" prop="feiyongdate">
          <el-date-picker v-model="form.feiyongdate" type="date" value-format="YYYY-MM-DD"
            :editable="false" placeholder="选择费用日期" style="width: 100%" />
        </el-form-item>
        <el-form-item label="金额(元)" prop="jine">
          <el-input-number v-model="form.jine" :precision="2" :min="0"
            controls-position="right" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.bz" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="submitForm">
          {{ editingId ? '确定修改' : '确定增加' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.clfeiyong-page { display: flex; flex-direction: column; gap: 10px; }
.filter-card :deep(.el-card__body) { padding: 10px 14px; }
.filter-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 12px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }
</style>
