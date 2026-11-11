<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createSimCard,
  deleteSimCard,
  deleteSimTaocan,
  downloadFeeTemplate,
  downloadSimTemplate,
  downloadStatusTemplate,
  exportSimCards,
  getSimCardDicts,
  getSimCardFees,
  getSimCardHistory,
  listSimCards,
  updateSimCard,
  uploadFeeFile,
  uploadReconcile,
  uploadSimTemplate,
  uploadStatusFile,
} from '@/api/simcard'

const pad = (n) => String(n).padStart(2, '0')
const now = new Date()
const currentMonth = `${now.getFullYear()}-${pad(now.getMonth() + 1)}`
const money = (v) => Number(v || 0).toFixed(2)

const dicts = reactive({
  departments: [],
  zt: [],
  wangluo: [],
  vpn: [],
  taocan: [],
  djr: [],
  zhanghu: [],
  default_bmid: null,
  current_year: now.getFullYear(),
  current_month: now.getMonth() + 1,
  perms: { view: true, manage: false },
})
const canManage = computed(() => !!dicts.perms.manage)

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(30)
const currentRow = ref(null)
const tableRef = ref()
const feeMonth = ref(currentMonth)
const expandedKeys = ref([])
const feeMap = reactive({})
const feeLoading = reactive({})
const feeYear = computed(() => Number((feeMonth.value || currentMonth).slice(0, 4)))

const filters = reactive({
  keyword: '',
  bmid: [],
  zt: '',
  wangluo: '',
  djr: '',
  zhanghu: '',
})

function buildParams() {
  const [year, month] = (feeMonth.value || currentMonth).split('-')
  const p = {
    year: Number(year),
    month: Number(month),
    keyword: filters.keyword || '',
  }
  if (filters.bmid.length) p.bmid = filters.bmid.join(',')
  if (filters.zt) p.zt = filters.zt
  if (filters.wangluo) p.wangluo = filters.wangluo
  if (filters.djr) p.djr = filters.djr
  if (filters.zhanghu) p.zhanghu = filters.zhanghu
  return p
}

async function load() {
  loading.value = true
  try {
    const data = await listSimCards({ ...buildParams(), page: page.value, size: size.value })
    rows.value = data.items || []
    total.value = data.total || 0
    if (currentRow.value) {
      currentRow.value = rows.value.find((r) => r.id === currentRow.value.id) || null
    }
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  expandedKeys.value = []
  load()
}

function resetFilters() {
  Object.assign(filters, { keyword: '', bmid: [], zt: '', wangluo: '', djr: '', zhanghu: '' })
  feeMonth.value = currentMonth
  search()
}

function onFeeMonthChange() {
  expandedKeys.value = []
  search()
}

function rowClassName({ row }) {
  if (/_X$/.test(row.kahao || '')) return 'row-deleted'
  if (row.zt === '备用') return 'row-standby'
  if (row.zt === '销卡') return 'row-cancelled'
  return ''
}

const months = Array.from({ length: 12 }, (_, i) => i + 1)

async function loadFees(row) {
  if (feeMap[row.id]) return
  feeLoading[row.id] = true
  try {
    feeMap[row.id] = await getSimCardFees(row.id, feeYear.value)
  } finally {
    feeLoading[row.id] = false
  }
}

function feeData(id) {
  return feeMap[id] || { months: Array(12).fill(0), zong: 0 }
}

function onExpandChange(row, expandedRows) {
  if (expandedRows.length) {
    expandedKeys.value = expandedRows.map((r) => r.id)
    expandedRows.forEach((r) => loadFees(r))
  } else {
    expandedKeys.value = expandedKeys.value.filter((id) => id !== row.id)
  }
}

async function openHistory(row) {
  historyTitle.value = `编辑历史 · ${row.kahao}`
  historyRows.value = []
  historyLoading.value = true
  historyDialog.value = true
  try {
    const data = await getSimCardHistory(row.id)
    historyRows.value = data.items || []
  } finally {
    historyLoading.value = false
  }
}

const historyDialog = ref(false)
const historyTitle = ref('')
const historyRows = ref([])
const historyLoading = ref(false)

const dialogVisible = ref(false)
const editing = ref(null)
const formRef = ref()
const form = reactive({
  bm: null,
  kahao: '',
  xuliehao: '',
  imhao: '',
  ip: '',
  vpn: '',
  taocan: '',
  zt: '',
  wangluo: '',
  yongtu: '',
  didian: '',
  glren: '',
  syren: '',
  zhanghu: '',
  bz: '',
})
const rules = {
  bm: [{ required: true, message: '请选择部门', trigger: 'change' }],
  kahao: [{ required: true, message: '请填写卡号', trigger: 'blur' }],
}

function defaultBmid() {
  return dicts.default_bmid || dicts.departments[0]?.id || null
}

function resetForm() {
  Object.assign(form, {
    bm: defaultBmid(),
    kahao: '',
    xuliehao: '',
    imhao: '',
    ip: '',
    vpn: '',
    taocan: '',
    zt: '',
    wangluo: '',
    yongtu: '',
    didian: '',
    glren: '',
    syren: '',
    zhanghu: '',
    bz: '',
  })
}

function openAdd() {
  editing.value = null
  resetForm()
  dialogVisible.value = true
}

function openEdit(row) {
  const target = row || currentRow.value
  if (!target) {
    ElMessage.warning('请选择要修改的数据')
    return
  }
  editing.value = target
  Object.assign(form, {
    bm: target.bm || defaultBmid(),
    kahao: target.kahao || '',
    xuliehao: target.xuliehao || '',
    imhao: target.imhao || '',
    ip: target.ip || '',
    vpn: target.vpn || '',
    taocan: target.taocan || '',
    zt: target.zt || '',
    wangluo: target.wangluo || '',
    yongtu: target.yongtu || '',
    didian: target.didian || '',
    glren: target.glren || '',
    syren: target.syren || '',
    zhanghu: target.zhanghu || '',
    bz: target.bz || '',
  })
  dialogVisible.value = true
}

async function submitForm() {
  await formRef.value.validate()
  const payload = { ...form }
  if (editing.value) {
    await updateSimCard(editing.value.id, payload)
    ElMessage.success('修改成功')
  } else {
    await createSimCard(payload)
    ElMessage.success('成功添加卡号')
  }
  dialogVisible.value = false
  await load()
}

async function doDelete() {
  const row = currentRow.value
  if (!row) {
    ElMessage.warning('请选择要删除的记录')
    return
  }
  await ElMessageBox.confirm('确定要删除该卡号吗？删除后可在“已删除”状态中查看。', '提示', {
    type: 'warning',
  })
  await deleteSimCard(row.id)
  ElMessage.success('删除成功')
  currentRow.value = null
  await load()
}

const taocanDialog = ref(false)

function openTaocanManage() {
  taocanDialog.value = true
}

async function removeTaocan(value) {
  await ElMessageBox.confirm(`确定要从套餐字典删除「${value}」吗？`, '提示', { type: 'warning' })
  await deleteSimTaocan(value)
  const idx = dicts.taocan.indexOf(value)
  if (idx >= 0) dicts.taocan.splice(idx, 1)
  if (form.taocan === value) form.taocan = ''
  ElMessage.success('已删除')
}

const uploadModes = {
  sim: '上传 SIM 卡模板文件',
  status: '上传批量状态更改',
  reconcile: '上传 SIM 卡核对文件',
}
const uploadMode = ref('')
const fileInput = ref()

function pickFile(mode) {
  uploadMode.value = mode
  if (fileInput.value) fileInput.value.value = ''
  fileInput.value.click()
}

async function onFilePicked(event) {
  const file = event.target.files?.[0]
  if (!file) return
  const mode = uploadMode.value
  try {
    if (mode === 'sim') {
      const res = await uploadSimTemplate(file, defaultBmid())
      ElMessage.success(`上传完成：新增 ${res.added} 条，跳过 ${res.skipped} 条`)
      await load()
    } else if (mode === 'status') {
      const res = await uploadStatusFile(file)
      ElMessage.success(`上传完成：更新 ${res.updated} 条，未匹配 ${res.skipped} 条`)
      await load()
    } else if (mode === 'reconcile') {
      await uploadReconcile(file)
      ElMessage.success('核对完成，结果文件已开始下载')
    }
  } finally {
    event.target.value = ''
  }
}

const feeDialog = ref(false)
const feeFormRef = ref()
const feeForm = reactive({ bmid: null, month: currentMonth, fileType: 'telecom', file: null })
const feeRules = {
  bmid: [{ required: true, message: '请选择部门', trigger: 'change' }],
  month: [{ required: true, message: '请选择年月', trigger: 'change' }],
}

function openFeeUpload() {
  Object.assign(feeForm, {
    bmid: defaultBmid(),
    month: feeMonth.value || currentMonth,
    fileType: 'telecom',
    file: null,
  })
  feeDialog.value = true
}

function onFeeFileChange(uploadFile) {
  feeForm.file = uploadFile.raw || null
}

const feeSubmitting = ref(false)

async function submitFeeUpload() {
  await feeFormRef.value.validate()
  if (!feeForm.file) {
    ElMessage.warning('请选择上传文件')
    return
  }
  const [year, month] = feeForm.month.split('-')
  feeSubmitting.value = true
  try {
    const res = await uploadFeeFile({
      file: feeForm.file,
      bmid: feeForm.bmid,
      year: Number(year),
      month: Number(month),
      fileType: feeForm.fileType,
    })
    ElMessage.success(`成功导入 ${res.count} 条记录${res.skipped ? `，跳过 ${res.skipped} 条` : ''}`)
    feeDialog.value = false
    Object.keys(feeMap).forEach((k) => delete feeMap[k])
    expandedKeys.value = []
    await load()
  } finally {
    feeSubmitting.value = false
  }
}

async function doExport() {
  await exportSimCards(buildParams())
  ElMessage.success('已导出当前筛选记录')
}

function downloadTemplate(kind) {
  if (kind === 'sim') downloadSimTemplate()
  else if (kind === 'fee') downloadFeeTemplate()
  else downloadStatusTemplate()
}

function onUploadCommand(command) {
  if (command === 'fee') openFeeUpload()
  else pickFile(command)
}

function onTemplateCommand(command) {
  downloadTemplate(command)
}

async function init() {
  const data = await getSimCardDicts()
  Object.assign(dicts, data)
  load()
}

onMounted(init)
</script>

<template>
  <div class="sim-page">
    <div class="page-head">
      <div>
        <div class="page-title">通信号码明细表</div>
        <div class="page-sub">SIM 卡台账、话费与批量核对</div>
      </div>
      <div class="head-actions">
        <el-button v-if="canManage" type="primary" @click="openAdd">添加</el-button>
        <el-button v-if="canManage" @click="openEdit()">编辑</el-button>
        <el-button v-if="canManage" type="danger" plain @click="doDelete">删除</el-button>
        <el-button @click="doExport">导出 EXCEL</el-button>
        <el-dropdown v-if="canManage" @command="onUploadCommand">
          <el-button>
            上传
            <span class="caret">▾</span>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="sim">上传 SIM 卡模板文件</el-dropdown-item>
              <el-dropdown-item command="status">上传批量状态更改</el-dropdown-item>
              <el-dropdown-item command="reconcile">上传 SIM 卡核对文件</el-dropdown-item>
              <el-dropdown-item command="fee" divided>上传话费</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-dropdown @command="onTemplateCommand">
          <el-button>
            模板
            <span class="caret">▾</span>
          </el-button>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="sim">下载 SIM 卡模板文件</el-dropdown-item>
              <el-dropdown-item command="fee">下载话费清单模板</el-dropdown-item>
              <el-dropdown-item command="status">下载批量状态更改模板</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </div>
    </div>

    <el-card shadow="never" class="filter-card">
      <div class="filters">
        <el-input
          v-model="filters.keyword"
          placeholder="模糊查询：卡号/使用人/地点/序列号/备注/用途/VPN"
          clearable
          class="filter-search"
          @keyup.enter="search"
          @clear="search"
        />
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
        <el-select
          v-model="filters.bmid"
          multiple
          collapse-tags
          collapse-tags-tooltip
          clearable
          filterable
          placeholder="部门"
          class="filter-item"
        >
          <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
        </el-select>
        <el-select v-model="filters.zt" clearable placeholder="状态" class="filter-small">
          <el-option v-for="z in dicts.zt" :key="z" :label="z" :value="z" />
        </el-select>
        <el-select v-model="filters.wangluo" clearable placeholder="运营商" class="filter-small">
          <el-option v-for="w in dicts.wangluo" :key="w" :label="w" :value="w" />
        </el-select>
        <el-select v-model="filters.djr" clearable filterable placeholder="登记人" class="filter-small">
          <el-option v-for="d in dicts.djr" :key="d" :label="d" :value="d" />
        </el-select>
        <el-select v-model="filters.zhanghu" clearable placeholder="账户" class="filter-small">
          <el-option v-for="z in dicts.zhanghu" :key="z" :label="z" :value="z" />
        </el-select>
        <span class="month-label">话费年月</span>
        <el-date-picker
          v-model="feeMonth"
          type="month"
          value-format="YYYY-MM"
          :clearable="false"
          class="filter-small"
          @change="onFeeMonthChange"
        />
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table
        ref="tableRef"
        v-loading="loading"
        :data="rows"
        row-key="id"
        border
        stripe
        highlight-current-row
        :expand-row-keys="expandedKeys"
        :row-class-name="rowClassName"
        max-height="calc(100vh - 300px)"
        @current-change="(row) => (currentRow = row)"
        @row-dblclick="openEdit"
        @expand-change="onExpandChange"
      >
        <el-table-column type="expand" width="42">
          <template #default="{ row }">
            <div v-loading="feeLoading[row.id]" class="fee-panel">
              <div class="fee-title">{{ row.kahao }} · {{ feeYear }} 年话费</div>
              <el-table :data="[feeData(row.id)]" size="small" border class="fee-table">
                <el-table-column label="年度合计" width="110" fixed>
                  <template #default="{ row: fee }">{{ money(fee.zong) }}</template>
                </el-table-column>
                <el-table-column
                  v-for="m in months"
                  :key="m"
                  :label="`${m}月`"
                  min-width="70"
                  align="right"
                >
                  <template #default="{ row: fee }">{{ money(fee.months?.[m - 1]) }}</template>
                </el-table-column>
              </el-table>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="70" fixed>
          <template #default="{ row }">
            <el-button link type="primary" @click="openHistory(row)">历史</el-button>
          </template>
        </el-table-column>
        <el-table-column prop="kahao" label="卡号" width="135" fixed show-overflow-tooltip />
        <el-table-column prop="xuliehao" label="序列号" width="140" show-overflow-tooltip />
        <el-table-column label="当月费用" width="105" align="right">
          <template #default="{ row }">{{ money(row.fy) }}</template>
        </el-table-column>
        <el-table-column prop="bumen" label="部门" width="120" show-overflow-tooltip />
        <el-table-column prop="didian" label="地点" min-width="180" show-overflow-tooltip />
        <el-table-column prop="yongtu" label="用途" min-width="120" show-overflow-tooltip />
        <el-table-column prop="bz" label="备注" min-width="160" show-overflow-tooltip />
        <el-table-column prop="taocan" label="套餐" width="120" show-overflow-tooltip />
        <el-table-column prop="zt" label="状态" width="100" />
        <el-table-column prop="wangluo" label="运营商" width="110" />
        <el-table-column prop="dengjiren" label="登记人" width="100" />
        <el-table-column prop="syren" label="使用人" width="100" />
        <el-table-column prop="glren" label="管理人" width="100" />
        <el-table-column prop="zhanghu" label="账户" width="110" />
        <el-table-column prop="vpn" label="VPN" width="140" show-overflow-tooltip />
        <el-table-column prop="bianjiren" label="最后编辑人" width="110" />
        <el-table-column prop="djriqi" label="登记时间" width="160" />
        <el-table-column prop="zhriqi" label="最后时间" width="160" />
      </el-table>
      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          :total="total"
          :page-sizes="[30, 60, 100, 200]"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @current-change="load"
          @size-change="search"
        />
      </div>
    </el-card>

    <el-dialog
      v-model="dialogVisible"
      :title="editing ? '编辑通信号码' : '新增通信号码'"
      width="780px"
      destroy-on-close
      class="std-dialog"
    >
      <el-form ref="formRef" :model="form" :rules="rules" label-width="82px" class="sim-form">
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="部门" prop="bm">
              <el-select v-model="form.bm" filterable placeholder="请选择部门" class="w-full">
                <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="卡号" prop="kahao">
              <el-input v-model="form.kahao" maxlength="150" placeholder="必填" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="序列号">
              <el-input v-model="form.xuliehao" maxlength="150" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="IM号">
              <el-input v-model="form.imhao" maxlength="150" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="IP">
              <el-input v-model="form.ip" maxlength="150" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="VPN">
              <el-select
                v-model="form.vpn"
                filterable
                allow-create
                default-first-option
                clearable
                placeholder="请选择或输入 VPN"
                class="w-full"
              >
                <el-option v-for="v in dicts.vpn" :key="v" :label="v" :value="v" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item>
              <template #label>
                <span>套餐</span>
                <el-button link type="primary" class="label-link" @click="openTaocanManage">
                  管理
                </el-button>
              </template>
              <el-select
                v-model="form.taocan"
                filterable
                allow-create
                default-first-option
                clearable
                placeholder="请选择或输入套餐"
                class="w-full"
              >
                <el-option v-for="t in dicts.taocan" :key="t" :label="t" :value="t" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="状态">
              <el-select v-model="form.zt" clearable placeholder="请选择状态" class="w-full">
                <el-option
                  v-for="z in dicts.zt.filter((x) => x !== '已删除')"
                  :key="z"
                  :label="z"
                  :value="z"
                />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="运营商">
              <el-select v-model="form.wangluo" clearable placeholder="请选择网络" class="w-full">
                <el-option v-for="w in dicts.wangluo" :key="w" :label="w" :value="w" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="用途">
              <el-input v-model="form.yongtu" maxlength="350" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="地点">
              <el-input v-model="form.didian" maxlength="550" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="管理人">
              <el-input v-model="form.glren" maxlength="120" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="使用人">
              <el-input v-model="form.syren" maxlength="120" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="账户">
              <el-select v-model="form.zhanghu" clearable placeholder="请选择账户" class="w-full">
                <el-option v-for="z in dicts.zhanghu" :key="z" :label="z" :value="z" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="24">
            <el-form-item label="备注">
              <el-input v-model="form.bz" type="textarea" :rows="3" maxlength="450" show-word-limit />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="feeDialog" title="话费上传" width="460px" destroy-on-close class="std-dialog">
      <el-form ref="feeFormRef" :model="feeForm" :rules="feeRules" label-width="86px">
        <el-form-item label="部门" prop="bmid">
          <el-select v-model="feeForm.bmid" filterable placeholder="请选择部门" class="w-full">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="年月" prop="month">
          <el-date-picker
            v-model="feeForm.month"
            type="month"
            value-format="YYYY-MM"
            :clearable="false"
            class="w-full"
          />
        </el-form-item>
        <el-form-item label="清单类型">
          <el-radio-group v-model="feeForm.fileType">
            <el-radio value="telecom">电信</el-radio>
            <el-radio value="mobile">移动</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="上传文件">
          <el-upload
            drag
            :auto-upload="false"
            :limit="1"
            accept=".xls,.xlsx"
            :on-change="onFeeFileChange"
            class="fee-upload"
          >
            <div class="upload-text">点击或拖拽 Excel 文件到此处</div>
            <div class="upload-hint">第一列卡号、第二列话费；移动清单以“分”为单位</div>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="feeDialog = false">取消</el-button>
        <el-button type="primary" :loading="feeSubmitting" @click="submitFeeUpload">上传</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="historyDialog" :title="historyTitle" width="760px" class="std-dialog">
      <div class="sim-card">
        <el-table v-loading="historyLoading" :data="historyRows" border max-height="520">
        <el-table-column prop="edit_time_text" label="时间" width="170" />
        <el-table-column prop="edit_user" label="操作人" width="100" />
        <el-table-column prop="field_name" label="字段" width="100" />
        <el-table-column label="变更内容">
          <template #default="{ row }">
            <span class="hist-old">{{ row.old_value || '(空)' }}</span>
            <span class="hist-arrow"> → </span>
            <span class="hist-new">{{ row.new_value || '(空)' }}</span>
          </template>
        </el-table-column>
        </el-table>
      </div>
    </el-dialog>

    <el-dialog v-model="taocanDialog" title="套餐字典" width="420px" class="std-dialog">
      <div class="sim-card">
        <div class="taocan-list">
        <div v-for="t in dicts.taocan" :key="t" class="taocan-item">
          <span>{{ t }}</span>
          <el-button link type="danger" @click="removeTaocan(t)">删除</el-button>
        </div>
        <el-empty v-if="!dicts.taocan.length" description="暂无套餐" :image-size="70" />
        </div>
      </div>
    </el-dialog>

    <input
      ref="fileInput"
      type="file"
      accept=".xls,.xlsx"
      style="display: none"
      @change="onFilePicked"
    />
  </div>
</template>

<style scoped>
.sim-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}
.page-title {
  font-size: 20px;
  font-weight: 600;
  color: #1c1e54;
}
.page-sub {
  margin-top: 4px;
  font-size: 12px;
  color: #64748d;
}
.head-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.caret {
  margin-left: 4px;
  font-size: 12px;
}
.filter-card :deep(.el-card__body) {
  padding: 14px 16px;
}
.filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
}
.filter-search {
  width: 340px;
  max-width: 100%;
}
.filter-item {
  width: 180px;
}
.filter-small {
  width: 130px;
}
.month-label {
  font-size: 13px;
  color: #475569;
  margin-left: 4px;
}
.table-card :deep(.el-card__body) {
  padding: 0;
}
.table-card :deep(.el-table) {
  border-radius: 8px 8px 0 0;
}
.pager {
  display: flex;
  justify-content: flex-end;
  padding: 12px 16px;
}
.fee-panel {
  padding: 10px 16px 14px;
  background: #f8fafc;
}
.fee-title {
  font-size: 13px;
  font-weight: 600;
  color: #1c1e54;
  margin-bottom: 8px;
}
.fee-table {
  max-width: 1180px;
}
.sim-form :deep(.el-form-item) {
  margin-bottom: 14px;
}
.sim-card {
  background: #fff;
  border: none;
  border-radius: 12px;
  padding: 12px 14px;
  box-shadow: 0 1px 2px rgba(16, 24, 40, .04), 0 4px 14px rgba(16, 24, 40, .05);
}
.w-full {
  width: 100%;
}
.label-link {
  margin-left: 6px;
  padding: 0;
  height: auto;
}
.fee-upload {
  width: 100%;
}
.upload-text {
  font-size: 13px;
  color: #334155;
}
.upload-hint {
  margin-top: 4px;
  font-size: 12px;
  color: #94a3b8;
}
.hist-old {
  color: #64748d;
}
.hist-arrow {
  color: #94a3b8;
}
.hist-new {
  color: #1c1e54;
}
.taocan-list {
  max-height: 380px;
  overflow: auto;
}
.taocan-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 4px;
  border-bottom: 1px solid #eef2f7;
}
.table-card :deep(.row-deleted) td {
  background: rgba(0, 0, 0, 0.05) !important;
  color: #94a3b8;
  text-decoration: line-through;
}
.table-card :deep(.row-standby) td {
  background: rgba(46, 125, 50, 0.08) !important;
}
.table-card :deep(.row-cancelled) td {
  background: rgba(198, 40, 40, 0.07) !important;
}
@media (max-width: 768px) {
  .filter-search {
    width: 100%;
  }
}
</style>
