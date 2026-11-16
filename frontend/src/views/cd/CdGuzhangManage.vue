<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getCdDicts, listCdGz, getCdGz, addCdGz, updateCdGz, deleteCdGz,
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

// ===== 列表与筛选 =====
const loading = ref(false)
const rows = ref([])
const total = ref(0)
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
    const data = await listCdGz(buildParams())
    rows.value = data.items || []
    total.value = data.total || 0
    if (data.bt) bt.value = data.bt
  } finally { loading.value = false }
}
function search() { page.value = 1; load() }

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

// ===== 添加 / 编辑 =====
const dialog = ref(false)
const editingId = ref(null)
const saving = ref(false)
const formRef = ref()
const blankForm = () => ({
  bbdate: curMonth(), // 月份控件值 YYYY-MM,提交时补 -25
  sbname: '', guancai: '', guanjing: '', didian: '',
  ksdate: '', jsdate: '', yy: '', dects: null, bz: '',
})
const form = reactive(blankForm())
const rules = {
  sbname: [{ required: true, message: '请输入设备名称', trigger: 'blur' }],
  didian: [{ required: true, message: '请输入故障地点', trigger: 'blur' }],
  ksdate: [{ required: true, message: '请选择故障发生日期', trigger: 'change' }],
  jsdate: [
    { required: true, message: '请选择故障结束日期', trigger: 'change' },
    {
      validator: (rule, value, callback) => {
        if (value && form.ksdate && value < form.ksdate) {
          callback(new Error('结束日期不能早于开始日期'))
        } else callback()
      },
      trigger: 'change',
    },
  ],
}

function openCreate() {
  editingId.value = null
  Object.assign(form, blankForm())
  dialog.value = true
  nextTick(() => formRef.value?.clearValidate())
}
async function openEdit(row) {
  const data = await getCdGz(row.id)
  editingId.value = data.id
  Object.assign(form, blankForm(), {
    bbdate: (data.bbdate || '').slice(0, 7) || curMonth(),
    sbname: data.sbname || '', guancai: data.guancai || '', guanjing: data.guanjing || '',
    didian: data.didian || '', ksdate: data.ksdate || '', jsdate: data.jsdate || '',
    yy: data.yy || '', dects: data.dects, bz: data.bz || '',
  })
  dialog.value = true
  nextTick(() => formRef.value?.clearValidate())
}
function buildPayload() {
  return {
    bbdate: form.bbdate ? `${form.bbdate}-25` : '',
    sbname: form.sbname, guancai: form.guancai, guanjing: form.guanjing,
    didian: form.didian, ksdate: form.ksdate, jsdate: form.jsdate,
    yy: form.yy, dects: form.dects === '' ? null : form.dects, bz: form.bz,
  }
}
async function submitForm() {
  if (saving.value) return
  saving.value = true
  try {
    await formRef.value.validate()
    const payload = buildPayload()
    if (editingId.value) await updateCdGz(editingId.value, payload)
    else await addCdGz(payload)
    ElMessage.success(editingId.value ? '修改成功' : '添加成功')
    dialog.value = false
    load()
  } finally { saving.value = false }
}
const dialogTitle = computed(() => editingId.value ? '编辑故障明细数据' : '添加传导设备故障')

// ===== 删除 =====
async function doDelete() {
  const row = requireOne(); if (!row) return
  await ElMessageBox.confirm('确定要删除数据吗', '提示', { type: 'warning' })
  await deleteCdGz(row.id)
  ElMessage.success('删除成功')
  load()
}
</script>

<template>
  <div class="cdgz-page">
    <el-card shadow="never" class="filter-card">
      <div class="page-title">{{ bt }}传导设备故障明细表</div>
      <el-form inline class="filter-form">
        <el-form-item>
          <el-input v-model="filters.keyword" placeholder="输入设备名称模糊查询"
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
      </el-form>
    </el-card>

    <div class="toolbar">
      <el-button type="primary" size="small" @click="openCreate">添加</el-button>
      <el-button size="small" @click="() => { const r = requireOne(); if (r) openEdit(r) }">编辑</el-button>
      <el-button size="small" @click="doDelete">删除</el-button>
      <span class="toolbar-hint">共 {{ total }} 条 · 双击行可编辑</span>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe size="small" row-key="id"
      height="calc(100vh - 290px)" @selection-change="onSelectionChange" @row-dblclick="openEdit">
      <el-table-column type="selection" width="42" />
      <el-table-column v-if="wide" prop="id" label="编号" width="66" />
      <el-table-column prop="bumen" label="部门" width="100" show-overflow-tooltip />
      <el-table-column prop="bbdate" label="报表日期" width="100">
        <template #default="{ row }">{{ fmt(row.bbdate) }}</template>
      </el-table-column>
      <el-table-column prop="sbname" label="设备名称" min-width="150" show-overflow-tooltip />
      <el-table-column prop="guanjing" label="管径" width="80" />
      <el-table-column prop="guancai" label="管材" width="80" />
      <el-table-column prop="didian" label="故障地点" min-width="120" show-overflow-tooltip />
      <el-table-column prop="ksdate" label="故障开始日期" width="108">
        <template #default="{ row }">{{ fmt(row.ksdate) }}</template>
      </el-table-column>
      <el-table-column prop="jsdate" label="故障结束日期" width="108">
        <template #default="{ row }">{{ fmt(row.jsdate) }}</template>
      </el-table-column>
      <el-table-column prop="yy" label="故障原因" min-width="140" show-overflow-tooltip />
      <el-table-column prop="dects" label="故障台时数" width="96" align="right" />
      <el-table-column prop="bz" label="备注是否停水" width="100" show-overflow-tooltip />
      <el-table-column v-if="wide" prop="finadate" label="最后操作日期" width="150">
        <template #default="{ row }">{{ fmt(row.finadate, 19) }}</template>
      </el-table-column>
      <el-table-column v-if="wide" prop="username" label="操作员" width="90" />
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[30, 60, 120]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>

    <!-- 添加 / 编辑 -->
    <el-dialog v-model="dialog" :title="dialogTitle" width="560px" top="7vh"
      class="std-dialog cd-long-dialog" :close-on-click-modal="false">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
        <el-form-item label="报表日期" prop="bbdate">
          <el-date-picker v-model="form.bbdate" type="month" value-format="YYYY-MM"
            format="YYYY年MM月" :editable="false" placeholder="选择月份" style="width: 100%" />
        </el-form-item>
        <el-form-item label="设备名称" prop="sbname">
          <el-input v-model="form.sbname" />
        </el-form-item>
        <el-form-item label="管材">
          <el-select v-model="form.guancai" placeholder="选择管材" clearable style="width: 100%">
            <el-option v-for="g in dicts.guancai" :key="g" :label="g" :value="g" />
          </el-select>
        </el-form-item>
        <el-form-item label="管径">
          <el-select v-model="form.guanjing" placeholder="选择管径" clearable style="width: 100%">
            <el-option v-for="g in dicts.guanjing" :key="g" :label="g" :value="g" />
          </el-select>
        </el-form-item>
        <el-form-item label="故障地点" prop="didian">
          <el-input v-model="form.didian" />
        </el-form-item>
        <el-form-item label="故障发生日期" prop="ksdate">
          <el-date-picker v-model="form.ksdate" type="date" value-format="YYYY-MM-DD"
            :editable="false" placeholder="选择日期" style="width: 100%" />
        </el-form-item>
        <el-form-item label="故障结束日期" prop="jsdate">
          <el-date-picker v-model="form.jsdate" type="date" value-format="YYYY-MM-DD"
            :editable="false" placeholder="选择日期" style="width: 100%" />
        </el-form-item>
        <el-form-item label="故障原因">
          <el-input v-model="form.yy" />
        </el-form-item>
        <el-form-item label="故障时数">
          <el-input-number v-model="form.dects" :precision="2" :min="0"
            controls-position="right" style="width: 100%" />
        </el-form-item>
        <el-form-item label="是否停水">
          <el-input v-model="form.bz" placeholder="备注是否停水(自由填写,照旧)" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitForm">
          {{ editingId ? '确定修改' : '确定增加' }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.cdgz-page { display: flex; flex-direction: column; gap: 10px; }
.filter-card :deep(.el-card__body) { padding: 10px 14px; }
.page-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 12px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.toolbar :deep(.el-button) { height: 32px; }
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }
</style>
