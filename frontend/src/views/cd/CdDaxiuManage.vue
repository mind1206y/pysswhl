<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getCdDicts, listCdDaxiu, getCdDaxiu, addCdDaxiu, updateCdDaxiu,
  deleteCdDaxiu, exportCdDaxiu,
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
    const data = await listCdDaxiu(buildParams())
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
  daxiudate: '', lb: '报废更换', nr: '', gdh: '',
  gdkj: '', xbqkj: '', fmkj: '', xfskj: '',
  num: null, bz: '', cfd: '', sgy: '', sgtel: '',
})
const form = reactive(blankForm())
const rules = {
  daxiudate: [{ required: true, message: '请选择大修日期', trigger: 'change' }],
  nr: [{ required: true, message: '请输入项目内容', trigger: 'blur' }],
  gdh: [{ required: true, message: '请输入工单号', trigger: 'blur' }],
}

function openCreate() {
  editingId.value = null
  Object.assign(form, blankForm())
  dialog.value = true
  nextTick(() => formRef.value?.clearValidate())
}
async function openEdit(row) {
  const data = await getCdDaxiu(row.id)
  editingId.value = data.id
  Object.assign(form, blankForm(), {
    bbdate: (data.bbdate || '').slice(0, 7) || curMonth(),
    daxiudate: data.daxiudate || '', lb: data.lb || '报废更换', nr: data.nr || '',
    gdh: data.gdh || '', gdkj: data.gdkj || '', xbqkj: data.xbqkj || '',
    fmkj: data.fmkj || '', xfskj: data.xfskj || '', num: data.num,
    bz: data.bz || '', cfd: data.cfd || '', sgy: data.sgy || '', sgtel: data.sgtel || '',
  })
  dialog.value = true
  nextTick(() => formRef.value?.clearValidate())
}
function buildPayload() {
  return {
    bbdate: form.bbdate ? `${form.bbdate}-25` : '',
    daxiudate: form.daxiudate, lb: form.lb, nr: form.nr, gdh: form.gdh,
    gdkj: form.gdkj, xbqkj: form.xbqkj, fmkj: form.fmkj, xfskj: form.xfskj,
    num: form.num === '' ? null : form.num, bz: form.bz, cfd: form.cfd,
    sgy: form.sgy, sgtel: form.sgtel,
  }
}
async function submitForm() {
  if (saving.value) return
  saving.value = true
  try {
    await formRef.value.validate()
    const payload = buildPayload()
    if (editingId.value) await updateCdDaxiu(editingId.value, payload)
    else await addCdDaxiu(payload)
    ElMessage.success(editingId.value ? '修改成功' : '添加成功')
    dialog.value = false
    load()
  } finally { saving.value = false }
}
const dialogTitle = computed(() => editingId.value ? '编辑大修数据' : '添加传导设备大修')

// ===== 删除 =====
async function doDelete() {
  const row = requireOne(); if (!row) return
  await ElMessageBox.confirm('确定要删除数据吗', '提示', { type: 'warning' })
  await deleteCdDaxiu(row.id)
  ElMessage.success('删除成功')
  load()
}

// ===== 导出 =====
const exporting = ref(false)
async function doExport() {
  exporting.value = true
  try {
    await exportCdDaxiu(buildParams(false))
    ElMessage.success('已导出传导设备大修明细')
  } finally { exporting.value = false }
}
</script>

<template>
  <div class="cddaxiu-page">
    <el-card shadow="never" class="filter-card">
      <div class="page-title">{{ bt }}传导设备大修/更新记录</div>
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
      <el-button size="small" :loading="exporting" @click="doExport">导出EXCEL</el-button>
      <span class="toolbar-hint">共 {{ total }} 条 · 双击行可编辑</span>
    </div>

    <!-- 两级表头:分组列连续,其余顶层列由 Element Plus 自动 rowspan -->
    <el-table v-loading="loading" :data="rows" border stripe size="small" row-key="id"
      height="calc(100vh - 290px)" @selection-change="onSelectionChange" @row-dblclick="openEdit">
      <el-table-column type="selection" width="42" />
      <el-table-column v-if="wide" prop="id" label="编号" width="58" />
      <el-table-column prop="bumen" label="部门" width="84" show-overflow-tooltip />
      <el-table-column label="设备大修/更新记录">
        <el-table-column prop="daxiudate" label="日期" width="96">
          <template #default="{ row }">{{ fmt(row.daxiudate) }}</template>
        </el-table-column>
        <el-table-column prop="lb" label="大修/更新类别" width="92" show-overflow-tooltip />
        <el-table-column prop="nr" label="项目内容（更新、大修地点）" width="130" show-overflow-tooltip />
      </el-table-column>
      <el-table-column prop="gdh" label="工单号" width="88" show-overflow-tooltip />
      <el-table-column label="口径">
        <el-table-column prop="gdkj" label="管道" width="68" />
        <el-table-column prop="xbqkj" label="修补器" width="68" />
        <el-table-column prop="fmkj" label="阀门" width="68" />
        <el-table-column prop="xfskj" label="消防栓" width="76" />
      </el-table-column>
      <el-table-column prop="num" label="数量" width="58" align="right" />
      <el-table-column label="备注">
        <el-table-column prop="bz" label="外力损坏" width="84" show-overflow-tooltip />
      </el-table-column>
      <el-table-column prop="cfd" label="其他存放点" width="92" show-overflow-tooltip />
      <el-table-column label="施工情况">
        <el-table-column prop="sgy" label="施工员" width="76" show-overflow-tooltip />
        <el-table-column prop="sgtel" label="施工电话" width="100" show-overflow-tooltip />
      </el-table-column>
      <el-table-column prop="bbdate" label="报表日期" width="96">
        <template #default="{ row }">{{ fmt(row.bbdate) }}</template>
      </el-table-column>
      <el-table-column v-if="wide" prop="finadate" label="最后操作日期" width="144">
        <template #default="{ row }">{{ fmt(row.finadate, 19) }}</template>
      </el-table-column>
      <el-table-column v-if="wide" prop="username" label="操作员" width="76" />
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[30, 60, 120]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>

    <!-- 添加 / 编辑 -->
    <el-dialog v-model="dialog" :title="dialogTitle" width="560px" top="5vh"
      class="std-dialog cd-long-dialog" :close-on-click-modal="false">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
        <el-form-item label="报表日期" prop="bbdate">
          <el-date-picker v-model="form.bbdate" type="month" value-format="YYYY-MM"
            format="YYYY年MM月" :editable="false" placeholder="选择月份" style="width: 100%" />
        </el-form-item>
        <el-form-item label="大修日期" prop="daxiudate">
          <el-date-picker v-model="form.daxiudate" type="date" value-format="YYYY-MM-DD"
            :editable="false" placeholder="选择日期" style="width: 100%" />
        </el-form-item>
        <el-form-item label="大修类别">
          <el-select v-model="form.lb" placeholder="选择大修类别" style="width: 100%">
            <el-option v-for="l in dicts.daxiu_lb" :key="l" :label="l" :value="l" />
          </el-select>
        </el-form-item>
        <el-form-item label="项目内容" prop="nr">
          <el-input v-model="form.nr" />
        </el-form-item>
        <el-form-item label="工单号" prop="gdh">
          <el-input v-model="form.gdh" />
        </el-form-item>
        <el-form-item label="管道口径">
          <el-select v-model="form.gdkj" placeholder="选择管道口径" clearable style="width: 100%">
            <el-option v-for="g in dicts.guanjing" :key="g" :label="g" :value="g" />
          </el-select>
        </el-form-item>
        <el-form-item label="修补器口径">
          <el-select v-model="form.xbqkj" placeholder="选择修补器口径" clearable style="width: 100%">
            <el-option v-for="g in dicts.guanjing" :key="g" :label="g" :value="g" />
          </el-select>
        </el-form-item>
        <el-form-item label="阀门口径">
          <el-select v-model="form.fmkj" placeholder="选择阀门口径" clearable style="width: 100%">
            <el-option v-for="g in dicts.guanjing" :key="g" :label="g" :value="g" />
          </el-select>
        </el-form-item>
        <el-form-item label="消防栓口径">
          <el-select v-model="form.xfskj" placeholder="选择消防栓口径" clearable style="width: 100%">
            <el-option v-for="g in dicts.guanjing" :key="g" :label="g" :value="g" />
          </el-select>
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="form.num" :precision="2" :min="0"
            controls-position="right" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注损坏">
          <el-input v-model="form.bz" />
        </el-form-item>
        <el-form-item label="其他存放点">
          <el-input v-model="form.cfd" />
        </el-form-item>
        <el-form-item label="施工员">
          <el-input v-model="form.sgy" />
        </el-form-item>
        <el-form-item label="施工电话">
          <el-input v-model="form.sgtel" />
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
.cddaxiu-page { display: flex; flex-direction: column; gap: 10px; }
.filter-card :deep(.el-card__body) { padding: 10px 14px; }
.page-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 12px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.toolbar :deep(.el-button) { height: 32px; }
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }
</style>
