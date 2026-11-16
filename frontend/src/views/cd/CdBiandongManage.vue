<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getCdDicts, listCdBd, getCdBd, addCdBd, updateCdBd, deleteCdBd,
  downloadCdBdTemplate, uploadCdBdTemplate,
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

// ===== 列表与筛选(额外 bdlb) =====
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(30)
const filters = reactive({ keyword: '', rq: '', bmid: null, bdlb: '' })

function buildParams(withPage = true) {
  const p = {}
  if (withPage) { p.page = page.value; p.size = size.value }
  p.rq = filters.rq
  if (filters.keyword) p.keyword = filters.keyword
  if (filters.bmid) p.bmid = filters.bmid
  if (filters.bdlb) p.bdlb = filters.bdlb
  return p
}
async function load() {
  loading.value = true
  try {
    const data = await listCdBd(buildParams())
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
  bdlb: '', sbname: '',
})
const form = reactive(blankForm())
const rules = {
  bdlb: [{ required: true, message: '请选择变动类别', trigger: 'change' }],
  sbname: [{ required: true, message: '请输入设备明细', trigger: 'blur' }],
}

function openCreate() {
  editingId.value = null
  Object.assign(form, blankForm())
  dialog.value = true
  nextTick(() => formRef.value?.clearValidate())
}
async function openEdit(row) {
  const data = await getCdBd(row.id)
  editingId.value = data.id
  Object.assign(form, blankForm(), {
    bbdate: (data.bbdate || '').slice(0, 7) || curMonth(),
    bdlb: data.bdlb || '', sbname: data.sbname || '',
  })
  dialog.value = true
  nextTick(() => formRef.value?.clearValidate())
}
function buildPayload() {
  return {
    bbdate: form.bbdate ? `${form.bbdate}-25` : '',
    bdlb: form.bdlb, sbname: form.sbname,
  }
}
async function submitForm() {
  if (saving.value) return
  saving.value = true
  try {
    await formRef.value.validate()
    const payload = buildPayload()
    if (editingId.value) await updateCdBd(editingId.value, payload)
    else await addCdBd(payload)
    ElMessage.success(editingId.value ? '修改成功' : '添加成功')
    dialog.value = false
    load()
  } finally { saving.value = false }
}
const dialogTitle = computed(() => editingId.value ? '编辑变动设备数据' : '新增变动明细')

// ===== 删除 =====
async function doDelete() {
  const row = requireOne(); if (!row) return
  await ElMessageBox.confirm('确定要删除数据吗', '提示', { type: 'warning' })
  await deleteCdBd(row.id)
  ElMessage.success('删除成功')
  load()
}

// ===== 下载模板 / 上传模板 =====
async function doDownloadTemplate() {
  await downloadCdBdTemplate()
  ElMessage.success('已下载传导设备变动表模板')
}
const fileInput = ref()
const uploading = ref(false)
async function onFileChange(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const fd = new FormData()
  fd.append('file', file)
  uploading.value = true
  try {
    await uploadCdBdTemplate(fd)
    ElMessage.success('上传成功')
    load()
  } finally {
    uploading.value = false
    e.target.value = ''
  }
}
</script>

<template>
  <div class="cdbd-page">
    <el-card shadow="never" class="filter-card">
      <div class="page-title">{{ bt }}传导设备变动明细表</div>
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
        <el-form-item label="变动类别">
          <el-select v-model="filters.bdlb" placeholder="===选择变动类别===" clearable
            style="width: 150px" @change="search">
            <el-option v-for="b in dicts.bdlb" :key="b" :label="b" :value="b" />
          </el-select>
        </el-form-item>
      </el-form>
    </el-card>

    <div class="toolbar">
      <el-button type="primary" size="small" @click="openCreate">添加</el-button>
      <el-button size="small" @click="() => { const r = requireOne(); if (r) openEdit(r) }">编辑</el-button>
      <el-button size="small" @click="doDelete">删除</el-button>
      <el-button size="small" @click="doDownloadTemplate">下载传导设备变动表模板</el-button>
      <el-button size="small" :loading="uploading" @click="fileInput?.click()">上传传导设备变动表</el-button>
      <input ref="fileInput" type="file" accept=".xls,.xlsx" style="display:none" @change="onFileChange" />
      <span class="toolbar-hint">共 {{ total }} 条 · 双击行可编辑</span>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe size="small" row-key="id"
      height="calc(100vh - 290px)" @selection-change="onSelectionChange" @row-dblclick="openEdit">
      <el-table-column type="selection" width="42" />
      <el-table-column v-if="wide" prop="id" label="编号" width="66" />
      <el-table-column prop="bbdate" label="报表日期" width="110">
        <template #default="{ row }">{{ fmt(row.bbdate) }}</template>
      </el-table-column>
      <el-table-column prop="bumen" label="部门" width="120" show-overflow-tooltip />
      <el-table-column prop="bdlb" label="变动类别" width="120" show-overflow-tooltip />
      <el-table-column prop="sbname" label="设备名称" min-width="260" show-overflow-tooltip />
      <el-table-column prop="adddate" label="录入日期" width="150">
        <template #default="{ row }">{{ fmt(row.adddate, 19) }}</template>
      </el-table-column>
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
    <el-dialog v-model="dialog" :title="dialogTitle" width="520px" top="10vh"
      class="std-dialog" :close-on-click-modal="false">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px">
        <el-form-item label="报表日期" prop="bbdate">
          <el-date-picker v-model="form.bbdate" type="month" value-format="YYYY-MM"
            format="YYYY年MM月" :editable="false" placeholder="选择月份" style="width: 100%" />
        </el-form-item>
        <el-form-item label="变动类别" prop="bdlb">
          <el-select v-model="form.bdlb" placeholder="选择变动类别" style="width: 100%">
            <el-option v-for="b in dicts.bdlb" :key="b" :label="b" :value="b" />
          </el-select>
        </el-form-item>
        <el-form-item label="设备明细" prop="sbname">
          <el-input v-model="form.sbname" type="textarea" :rows="3" />
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
.cdbd-page { display: flex; flex-direction: column; gap: 10px; }
.filter-card :deep(.el-card__body) { padding: 10px 14px; }
.page-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 12px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.toolbar :deep(.el-button) { height: 32px; }
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }
</style>
