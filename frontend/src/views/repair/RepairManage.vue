<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts'
import {
  addRepairDetail,
  auditRepairs,
  createRepair,
  createRepairImageToken,
  deleteRepair,
  deleteRepairDetail,
  deleteRepairImage,
  exportRepairs,
  getRepair,
  getRepairChart,
  getRepairDicts,
  getRepairRemaining,
  getVehicleHistory,
  listRepairDetails,
  listRepairs,
  searchRepairDetails,
  searchRepairVehicles,
  updateRepair,
  updateRepairDetail,
  uploadRepairImages,
} from '@/api/repair'

const dicts = reactive({
  departments: [], vehicles: [], wxdw_all: [], wxdw_used: [], lx: [],
  pjorgs: [], zk: [], years: [], current_year: new Date().getFullYear(),
  perms: { view: true, manage: false, audit: false },
})
const canManage = computed(() => !!dicts.perms.manage)
const canAudit = computed(() => !!dicts.perms.audit)

const pad = (n) => String(n).padStart(2, '0')
const fmtDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const dateNow = new Date()
const defaultRange = [`${dateNow.getFullYear()}-01-01`, fmtDate(dateNow)]
const money = (v) => Number(v || 0).toFixed(2)

// ===== 列表 =====
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(30)
const footer = ref({ jine: 0 })
const selection = ref([])
const filters = reactive({
  dateRange: [...defaultRange], year: '', bmid: null, cheid: null, wxdw: null, keyword: '',
})

function buildParams() {
  const p = {}
  if (Array.isArray(filters.dateRange) && filters.dateRange.length === 2) {
    p.rq = filters.dateRange[0]
    p.rqend = filters.dateRange[1]
  }
  if (filters.bmid) p.bmid = filters.bmid
  if (filters.cheid) p.cheid = filters.cheid
  if (filters.wxdw) p.wxdw = filters.wxdw
  if (filters.keyword) p.keyword = filters.keyword
  return p
}

async function load() {
  loading.value = true
  try {
    const data = await listRepairs({ ...buildParams(), page: page.value, size: size.value })
    rows.value = data.items
    total.value = data.total
    footer.value = data.footer || { jine: 0 }
    Object.keys(detailMap).forEach((k) => delete detailMap[k])
  } finally {
    loading.value = false
  }
}
function search() { page.value = 1; load() }
function onSelectionChange(v) { selection.value = v }
function requireOne() {
  if (selection.value.length !== 1) {
    ElMessage.warning('请先勾选一条记录')
    return null
  }
  return selection.value[0]
}
function onYearChange() {
  if (filters.year) filters.dateRange = [`${filters.year}-01-01`, `${filters.year}-12-31`]
  search()
}
function showAll() {
  Object.assign(filters, {
    dateRange: [...defaultRange], year: '', bmid: null, cheid: null, wxdw: null, keyword: '',
  })
  search()
}
function summaryMethod({ columns }) {
  const sums = []
  columns.forEach((col, i) => {
    if (col.property === 'xiangmu') sums[i] = '合计'
    else if (col.property === 'jine') sums[i] = money(footer.value.jine)
    else sums[i] = ''
  })
  return sums
}

// ===== 展开明细 =====
const detailMap = reactive({})
const detailLoading = reactive({})
async function onExpand(row, expandedRows) {
  const expanded = Array.isArray(expandedRows) ? expandedRows.includes(row) : !!expandedRows
  if (!expanded) return
  detailLoading[row.ID] = true
  try {
    detailMap[row.ID] = (await listRepairDetails(row.ID)).items
  } finally {
    detailLoading[row.ID] = false
  }
}

// ===== 审批 / 删除 =====
async function setAudit(auditRows, approved) {
  if (!auditRows.length) { ElMessage.warning('请先勾选维修单'); return }
  await ElMessageBox.confirm(
    `确定要${approved ? '审批' : '取消审批'}选中的 ${auditRows.length} 条维修单吗？`,
    '提示', { type: 'warning' },
  )
  await auditRepairs(auditRows.map((r) => r.ID), approved)
  ElMessage.success(approved ? '已审批' : '已取消审批')
  load()
}
function toggleAudit(row) { setAudit([row], !row.sp) }
function auditSelected(approved) { setAudit(selection.value, approved) }

async function doDelete() {
  const row = requireOne()
  if (!row) return
  if (row.sp) { ElMessage.warning('已审批的维修单不能删除'); return }
  await ElMessageBox.confirm(`确定删除维修单 ${row.ID} 吗？有明细记录的维修单不能删除。`, '提示', { type: 'warning' })
  await deleteRepair(row.ID)
  ElMessage.success('删除成功')
  load()
}

async function doExport(kind) {
  await exportRepairs(buildParams(), kind)
  ElMessage.success('已导出当前筛选记录')
}

// ===== 维修单弹窗 =====
const orderDialog = ref(false)
const orderTab = ref('basic')
const editingOrder = ref(null)
const orderFormRef = ref()
const vehicleOptions = ref([])
const vehicleLoading = ref(false)
const orderForm = reactive({
  cheid: null, chehao: '', lx: [], wxdw: null, zk: '1', jcriqi: fmtDate(dateNow),
  xiangmu: '', jine: null, gonglinum: null, bxren: '', ccriqi: null,
})
const orderRules = {
  cheid: [{ required: true, message: '请选择车号', trigger: 'change' }],
  lx: [{ type: 'array', required: true, min: 1, message: '请至少选择一个维修类别', trigger: 'change' }],
  wxdw: [{ required: true, message: '请选择维修单位', trigger: 'change' }],
  jcriqi: [{ required: true, message: '请选择进场日期', trigger: 'change' }],
  xiangmu: [{ required: true, message: '请填写项目名称', trigger: 'blur' }],
  jine: [{ required: true, message: '请填写总金额', trigger: 'blur' }],
}
const history = ref([])
const historyLoading = ref(false)

function resetOrderForm() {
  Object.assign(orderForm, {
    cheid: null, chehao: '', lx: [], wxdw: null, zk: '1', jcriqi: fmtDate(new Date()),
    xiangmu: '', jine: null, gonglinum: null, bxren: '', ccriqi: null,
  })
  history.value = []
  stagedImages.value.forEach((s) => URL.revokeObjectURL(s.url))
  stagedImages.value = []
  orderImages.value = []
}
async function openCreate() {
  editingOrder.value = null
  resetOrderForm()
  orderTab.value = 'basic'
  vehicleOptions.value = dicts.vehicles
  orderDialog.value = true
}
async function openEdit(row) {
  if (!row) return
  if (row.sp) { ElMessage.warning('该维修单已审批，不允许修改'); return }
  const info = await getRepair(row.ID)
  editingOrder.value = info
  Object.assign(orderForm, {
    cheid: info.cheid, chehao: info.chehao, lx: (info.lx || '').split(',').filter(Boolean),
    wxdw: info.wxdw, zk: String(Number(info.zk ?? 1)), jcriqi: info.jcriqi,
    xiangmu: info.xiangmu, jine: info.jine, gonglinum: info.gonglinum,
    bxren: info.bxren, ccriqi: info.ccriqi,
  })
  vehicleOptions.value = dicts.vehicles
  stagedImages.value = []
  orderImages.value = await resolveImages(info.tps || [])
  orderTab.value = 'basic'
  orderDialog.value = true
}
function onRowDblclick(row) { openEdit(row) }

async function remoteVehicles(q) {
  if (!q) { vehicleOptions.value = dicts.vehicles; return }
  vehicleLoading.value = true
  try { vehicleOptions.value = await searchRepairVehicles(q) } finally { vehicleLoading.value = false }
}
async function onVehicleChange(id) {
  const v = vehicleOptions.value.find((x) => x.id === id) || dicts.vehicles.find((x) => x.id === id)
  orderForm.chehao = v?.text || ''
  if (!editingOrder.value && id) {
    historyLoading.value = true
    try { history.value = (await getVehicleHistory(id)).items } finally { historyLoading.value = false }
  }
}

function orderPayload() {
  return {
    cheid: orderForm.cheid,
    lx: orderForm.lx.join(','),
    wxdw: orderForm.wxdw,
    zk: orderForm.zk === '' || orderForm.zk == null ? 1 : Number(orderForm.zk),
    jcriqi: orderForm.jcriqi,
    xiangmu: orderForm.xiangmu,
    jine: Number(orderForm.jine),
    gonglinum: orderForm.gonglinum === '' || orderForm.gonglinum == null ? null : Number(orderForm.gonglinum),
    bxren: orderForm.bxren || '',
    ccriqi: orderForm.ccriqi || null,
  }
}
async function uploadStaged(id) {
  if (!stagedImages.value.length) return
  const fd = new FormData()
  stagedImages.value.forEach((s) => fd.append('files', s.file))
  await uploadRepairImages(id, fd)
  stagedImages.value.forEach((s) => URL.revokeObjectURL(s.url))
  stagedImages.value = []
}
const orderSaving = ref(false)
async function saveOrder(keepOpen = false) {
  if (orderSaving.value) return  // 防双击重复提交
  orderSaving.value = true
  try {
    await orderFormRef.value.validate()
    const payload = orderPayload()
    if (editingOrder.value) {
      await updateRepair(editingOrder.value.ID, payload)
      if (stagedImages.value.length) await uploadStaged(editingOrder.value.ID)
      ElMessage.success('修改成功')
      orderDialog.value = false
      load()
      return
    }
    const row = await createRepair(payload)
    await uploadStaged(row.ID)
    ElMessage.success('添加成功')
    if (keepOpen) {
      const { wxdw, zk } = orderForm
      resetOrderForm()
      orderForm.wxdw = wxdw
      orderForm.zk = zk
      vehicleOptions.value = dicts.vehicles
      ElMessage.success('保存成功，可继续录入')
    } else {
      orderDialog.value = false
    }
    load()
  } finally { orderSaving.value = false }
}

// ===== 图片 =====
const stagedImages = ref([])
const stageInput = ref()
function onStageImages(e) {
  const files = [...e.target.files]
  files.forEach((file) => stagedImages.value.push({ file, url: URL.createObjectURL(file) }))
  e.target.value = ''
}
function removeStaged(i) {
  URL.revokeObjectURL(stagedImages.value[i].url)
  stagedImages.value.splice(i, 1)
}
const orderImages = ref([])
const editImageInput = ref()
async function resolveImages(list) {
  const out = []
  for (const img of list) {
    let src = ''
    try { src = (await createRepairImageToken(img.id)).url } catch { /* ignore */ }
    out.push({ ...img, src, error: false })
  }
  return out
}
async function onEditImagePick(e) {
  const files = [...e.target.files]
  if (!files.length) return
  const fd = new FormData()
  files.forEach((f) => fd.append('files', f))
  await uploadRepairImages(editingOrder.value.ID, fd)
  e.target.value = ''
  const info = await getRepair(editingOrder.value.ID)
  orderImages.value = await resolveImages(info.tps || [])
  ElMessage.success('图片已上传')
  load()
}
async function removeOrderImage(img) {
  await ElMessageBox.confirm('确定删除该图片吗？', '提示', { type: 'warning' })
  await deleteRepairImage(img.id)
  orderImages.value = orderImages.value.filter((i) => i.id !== img.id)
  if (!stagedImages.value.length) load()
}

// 列表图片查看
const imageDialog = ref(false)
const imageOrder = ref(null)
const imageList = ref([])
async function openImages(row) {
  imageOrder.value = row
  imageList.value = await resolveImages(row.tps || [])
  imageDialog.value = true
}

// ===== 维修明细弹窗 =====
const detailDialog = ref(false)
const detailOrder = ref(null)
const mxFormRef = ref()
const mxForm = reactive({
  id: null, pjorgs: '', xiangmu: '', guige: '', gjz: '', zkqiandanjia: null, shuliang: 1,
})
const mxRules = {
  pjorgs: [{ required: true, message: '请选择配件费或工时费', trigger: 'change' }],
  xiangmu: [{ required: true, message: '请填写项目名称', trigger: 'blur' }],
  zkqiandanjia: [{ required: true, message: '请填写原单价', trigger: 'blur' }],
  shuliang: [{ required: true, message: '请填写数量', trigger: 'blur' }],
}
const mxList = ref([])
const mxLoading = ref(false)
const mxKeyword = ref('')
const mxRemainingText = ref('')
const zkValue = computed(() => Number(detailOrder.value?.zk ?? 1))
const mxDanjia = computed(() => Math.round(zkValue.value * Number(mxForm.zkqiandanjia || 0) * 100) / 100)
const mxZonge = computed(() => Math.round(mxDanjia.value * Number(mxForm.shuliang || 0) * 100) / 100)

async function loadMxList() {
  if (!detailOrder.value) return
  mxLoading.value = true
  try {
    mxList.value = (await searchRepairDetails({
      cheid: detailOrder.value.cheid, wxdid: detailOrder.value.ID, keyword: mxKeyword.value,
    })).items
  } finally { mxLoading.value = false }
}
let mxTimer = null
function onMxKeywordInput() {
  clearTimeout(mxTimer)
  mxTimer = setTimeout(loadMxList, 300)
}
async function refreshRemaining() {
  if (!detailOrder.value) return
  const params = { ze: mxZonge.value }
  if (mxForm.id) params.mxid = mxForm.id
  const r = await getRepairRemaining(detailOrder.value.ID, params)
  mxRemainingText.value = r.text
}
async function openAddDetail(row) {
  detailOrder.value = row
  Object.assign(mxForm, { id: null, pjorgs: '', xiangmu: '', guige: '', gjz: '', zkqiandanjia: null, shuliang: 1 })
  mxKeyword.value = ''
  mxRemainingText.value = ''
  detailDialog.value = true
  await Promise.all([loadMxList(), nextTick()])
  refreshRemaining()
}
async function openEditDetail(row, d) {
  detailOrder.value = row
  Object.assign(mxForm, {
    id: d.id, pjorgs: d.pjorgs, xiangmu: d.xiangmu, guige: d.guige,
    gjz: d.gjz, zkqiandanjia: d.zkqiandanjia, shuliang: d.shuliang,
  })
  mxRemainingText.value = ''
  detailDialog.value = true
  await nextTick()
  refreshRemaining()
}
const mxSaving = ref(false)
async function saveDetail() {
  if (mxSaving.value) return  // 防双击重复提交
  mxSaving.value = true
  try {
    await mxFormRef.value.validate()
    const payload = {
      pjorgs: mxForm.pjorgs, xiangmu: mxForm.xiangmu, guige: mxForm.guige,
      gjz: mxForm.gjz, zkqiandanjia: Number(mxForm.zkqiandanjia), shuliang: Number(mxForm.shuliang),
    }
    if (mxForm.id) {
      await updateRepairDetail(mxForm.id, payload)
      ElMessage.success('修改成功')
    } else {
      await addRepairDetail(detailOrder.value.ID, payload)
      ElMessage.success('添加成功')
      Object.assign(mxForm, { pjorgs: '', xiangmu: '', guige: '', gjz: '', zkqiandanjia: null, shuliang: 1 })
    }
    await loadMxList()
    refreshRemaining()
    load()
  } finally { mxSaving.value = false }
}
async function removeDetail(d, order) {
  if (order) detailOrder.value = order
  await ElMessageBox.confirm('确定要删除该明细数据吗？', '提示', { type: 'warning' })
  await deleteRepairDetail(d.id)
  ElMessage.success('删除成功')
  await loadMxList()
  refreshRemaining()
  load()
}

// ===== 年度维修费图表 =====
const chartDialog = ref(false)
const chartEl = ref()
let chart = null
const chartLoading = ref(false)
async function openChart() {
  chartLoading.value = true
  chartDialog.value = true
  try {
    await nextTick()
    await new Promise((resolve) => setTimeout(resolve, 50))
    if (!chartEl.value) return
    const y = filters.dateRange?.[0] ? Number(String(filters.dateRange[0]).slice(0, 4)) : dicts.current_year
    const data = await getRepairChart({ year: y, bmid: filters.bmid || undefined })
    if (!chart) chart = echarts.init(chartEl.value)
    chart.clear()
    chart.setOption({
      title: {
        text: `${data.name || ''} ${data.year}年全年维修费：${money(data.total)}元`,
        left: 'center', top: 8, textStyle: { fontSize: 15 },
      },
      tooltip: { trigger: 'axis', valueFormatter: (v) => `${money(v)} 元` },
      grid: { left: 62, right: 28, top: 64, bottom: 36 },
      xAxis: { type: 'category', data: ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月'] },
      yAxis: { type: 'value', name: '元' },
      series: [{
        name: '维修费', type: 'bar', data: data.months, barMaxWidth: 42,
        label: { show: true, position: 'top', formatter: (p) => (p.value ? money(p.value) : '') },
        itemStyle: { color: '#5b7cfa' },
      }],
    })
    chart.resize()
  } finally { chartLoading.value = false }
}
function onChartClosed() { if (chart) { chart.dispose(); chart = null } }

onBeforeUnmount(() => { if (chart) chart.dispose() })

onMounted(async () => {
  const d = await getRepairDicts()
  Object.assign(dicts, d)
  vehicleOptions.value = d.vehicles
  load()
})
</script>

<template>
  <div class="repair-page">
    <el-card shadow="never" class="filter-card">
      <div class="filter-title">车辆维修信息表</div>
      <el-form inline class="filter-form">
        <el-form-item label="维修日期">
          <el-date-picker v-model="filters.dateRange" type="daterange" value-format="YYYY-MM-DD"
            range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期"
            style="width: 240px" @change="search" />
        </el-form-item>
        <el-form-item label="年度">
          <el-select v-model="filters.year" placeholder="按年度" clearable style="width: 105px" @change="onYearChange">
            <el-option v-for="y in dicts.years" :key="y" :label="`${y}年`" :value="y" />
          </el-select>
        </el-form-item>
        <el-form-item label="部门">
          <el-select v-model="filters.bmid" placeholder="选择部门" clearable filterable style="width: 150px" @change="search">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="车号">
          <el-select v-model="filters.cheid" placeholder="选择车号" clearable filterable style="width: 190px" @change="search">
            <el-option v-for="v in dicts.vehicles" :key="v.id" :label="v.text" :value="v.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="维修单位">
          <el-select v-model="filters.wxdw" placeholder="选择维修单位" clearable filterable style="width: 190px" @change="search">
            <el-option v-for="u in dicts.wxdw_used" :key="u.id" :label="u.dwname" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="关键字">
          <el-input v-model="filters.keyword" placeholder="车号 / 项目 / 维修单位 / 金额" clearable
            style="width: 220px" @keyup.enter="search" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
          <el-button @click="showAll">显示全部</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <div class="toolbar">
      <template v-if="canAudit">
        <el-button size="small" type="primary" @click="auditSelected(true)">审批维修</el-button>
        <el-button size="small" @click="auditSelected(false)">取消审批</el-button>
      </template>
      <el-button size="small" @click="openCreate">添加维修单</el-button>
      <el-button size="small" @click="() => { const r = requireOne(); if (r) openEdit(r) }">编辑</el-button>
      <el-button v-if="canManage" size="small" @click="doDelete">删除</el-button>
      <el-button size="small" @click="doExport('dan')">导出维修单</el-button>
      <el-button size="small" @click="doExport('mx')">导出维修明细</el-button>
      <el-button size="small" @click="openChart">年度维修费</el-button>
      <span class="toolbar-hint">共 {{ total }} 条 · 双击行可编辑 · 展开行查看维修明细</span>
    </div>

    <el-table v-loading="loading" :data="rows" border size="small" height="calc(100vh - 300px)"
      row-key="ID" show-summary :summary-method="summaryMethod"
      @selection-change="onSelectionChange" @row-dblclick="onRowDblclick" @expand-change="onExpand">
      <el-table-column type="selection" width="42" fixed="left" />
      <el-table-column type="expand" width="38" fixed="left">
        <template #default="{ row }">
          <div class="sub-wrap">
            <div class="sub-title">
              维修明细表
              <el-button link type="primary" size="small" @click="openAddDetail(row)">+ 添加明细</el-button>
              <span v-if="!detailLoading[row.ID] && !(detailMap[row.ID] || []).length" class="sub-empty">
                该维修单暂无明细
              </span>
            </div>
            <el-table :data="detailMap[row.ID] || []" size="small" border style="min-width: 1080px"
              v-loading="detailLoading[row.ID]">
              <el-table-column prop="id" label="编号" width="70" />
              <el-table-column prop="xiangmu" label="项目名" min-width="150" show-overflow-tooltip />
              <el-table-column prop="zkqiandanjia" label="原价" width="90" align="right">
                <template #default="{ row: d }">{{ money(d.zkqiandanjia) }}</template>
              </el-table-column>
              <el-table-column prop="danjia" label="单价（元）" width="100" align="right">
                <template #default="{ row: d }">{{ money(d.danjia) }}</template>
              </el-table-column>
              <el-table-column prop="shuliang" label="数量" width="70" align="right" />
              <el-table-column prop="zonge" label="总额" width="100" align="right">
                <template #default="{ row: d }">{{ money(d.zonge) }}</template>
              </el-table-column>
              <el-table-column prop="pjorgs" label="配件或工时" width="100" />
              <el-table-column prop="gjz" label="关键字" width="100" show-overflow-tooltip />
              <el-table-column prop="guige" label="规格" width="120" show-overflow-tooltip />
              <el-table-column prop="username" label="登记人" width="90" />
              <el-table-column prop="djriqi" label="登记日期" width="145">
                <template #default="{ row: d }">{{ (d.djriqi || '').slice(0, 16) }}</template>
              </el-table-column>
              <el-table-column label="删除或修改" width="110" fixed="right">
                <template #default="{ row: d }">
                  <el-button link type="primary" size="small" @click="openEditDetail(row, d)">修改</el-button>
                  <el-button link type="danger" size="small" @click="removeDetail(d, row)">删除</el-button>
                </template>
              </el-table-column>
              <template #empty><span /></template>
            </el-table>
          </div>
        </template>
      </el-table-column>

      <el-table-column label="审批" width="76" align="center">
        <template #default="{ row }">
          <el-button v-if="canAudit" link size="small" :type="row.sp ? 'success' : 'info'"
            @click="toggleAudit(row)">{{ row.sp ? '已审批' : '待审批' }}</el-button>
          <el-tag v-else :type="row.sp ? 'success' : 'info'" size="small">{{ row.sp ? '已审' : '未审' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="添加" width="64" align="center">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openAddDetail(row)">明细</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="lx" label="维保类型" width="110" show-overflow-tooltip />
      <el-table-column prop="jcriqi" label="进场日期" width="105" />
      <el-table-column prop="bm" label="部门" width="120" show-overflow-tooltip />
      <el-table-column prop="bxren" label="报修人" width="90" show-overflow-tooltip />
      <el-table-column prop="chehao" label="车号" width="110" />
      <el-table-column prop="xiangmu" label="维修项目" min-width="240" show-overflow-tooltip />
      <el-table-column prop="jine" label="总金额" width="100" align="right">
        <template #default="{ row }">{{ money(row.jine) }}</template>
      </el-table-column>
      <el-table-column prop="zk" label="折扣" width="70" align="center">
        <template #default="{ row }">{{ row.zk ?? 1 }}</template>
      </el-table-column>
      <el-table-column prop="cllx" label="车辆类型" width="100" show-overflow-tooltip />
      <el-table-column prop="gonglinum" label="公里数" width="90" align="right" />
      <el-table-column prop="dwname" label="维修单位" width="170" show-overflow-tooltip />
      <el-table-column prop="gongshifei" label="工时费" width="92" align="right">
        <template #default="{ row }">{{ money(row.gongshifei) }}</template>
      </el-table-column>
      <el-table-column prop="peijianfei" label="配件费" width="92" align="right">
        <template #default="{ row }">{{ money(row.peijianfei) }}</template>
      </el-table-column>
      <el-table-column prop="sx" label="尚需录" width="90" align="right">
        <template #default="{ row }">{{ money(row.sx) }}</template>
      </el-table-column>
      <el-table-column prop="username" label="登记人" width="90" />
      <el-table-column prop="djriqi" label="登记日期" width="145">
        <template #default="{ row }">{{ (row.djriqi || '').slice(0, 16) }}</template>
      </el-table-column>
      <el-table-column label="图片" width="80" align="center">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openImages(row)">{{ row.tps?.length || 0 }} 张</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="sptime" label="审批时间" width="145">
        <template #default="{ row }">{{ (row.sptime || '').slice(0, 16) }}</template>
      </el-table-column>
      <el-table-column prop="spren" label="审批人" width="90" />
      <el-table-column prop="ID" label="流水号" width="80" align="center" />
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[30, 60, 120]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>

    <!-- 添加 / 编辑维修单 -->
    <el-dialog v-model="orderDialog" :title="editingOrder ? '编辑维修单' : '添加维修单'"
      :width="editingOrder ? '720px' : 'min(1180px, 96vw)'" top="5vh" :close-on-click-modal="false">
      <div class="order-layout">
        <div v-if="!editingOrder" class="order-left">
          <div class="left-title">车号查询</div>
          <el-select v-model="orderForm.cheid" filterable remote :remote-method="remoteVehicles"
            :loading="vehicleLoading" placeholder="输入车号数字搜索并选择" style="width: 100%" @change="onVehicleChange">
            <el-option v-for="v in vehicleOptions" :key="v.id" :label="v.text" :value="v.id" />
          </el-select>
          <div class="left-title" style="margin-top: 12px">车辆进场维修记录</div>
          <el-table :data="history" size="small" border height="330px" v-loading="historyLoading">
            <el-table-column prop="xiangmu" label="项目" min-width="130" show-overflow-tooltip />
            <el-table-column prop="chehao" label="车号" width="100" />
            <el-table-column prop="gonglinum" label="公里数" width="80" align="right" />
            <el-table-column prop="jine" label="总金额" width="90" align="right">
              <template #default="{ row }">{{ money(row.jine) }}</template>
            </el-table-column>
            <el-table-column prop="jcriqi" label="进场日期" width="105" />
            <template #empty><span /></template>
          </el-table>
        </div>

        <div class="order-right">
          <el-form ref="orderFormRef" :model="orderForm" :rules="orderRules" label-width="92px">
            <el-tabs v-model="orderTab">
              <el-tab-pane label="维修单信息" name="basic">
                <el-form-item v-if="!editingOrder" label="车号" prop="cheid">
                  <el-input v-model="orderForm.chehao" readonly placeholder="请先在左侧选择车号" />
                </el-form-item>
                <el-form-item v-else label="车号">
                  <el-input v-model="orderForm.chehao" readonly />
                </el-form-item>
                <el-form-item label="维修类别" prop="lx">
                  <el-select v-model="orderForm.lx" multiple collapse-tags collapse-tags-tooltip
                    placeholder="维修类别（可多选）" style="width: 100%">
                    <el-option v-for="t in dicts.lx" :key="t" :label="t" :value="t" />
                  </el-select>
                </el-form-item>
                <el-form-item label="维修单位" prop="wxdw">
                  <div class="unit-row">
                    <el-select v-model="orderForm.wxdw" placeholder="请选择维修单位" filterable style="flex: 1">
                      <el-option v-for="u in dicts.wxdw_all" :key="u.id" :label="u.dwname" :value="u.id" />
                    </el-select>
                    <span class="inner-label">折扣：</span>
                    <el-select v-model="orderForm.zk" style="width: 150px">
                      <el-option v-for="z in dicts.zk" :key="z.value + z.label" :label="z.label" :value="z.value" />
                    </el-select>
                  </div>
                </el-form-item>
                <el-form-item label="进场日期" prop="jcriqi">
                  <el-date-picker v-model="orderForm.jcriqi" type="date" value-format="YYYY-MM-DD"
                    style="width: 100%" />
                </el-form-item>
                <el-form-item label="项目名称" prop="xiangmu">
                  <el-input v-model="orderForm.xiangmu" />
                </el-form-item>
                <el-form-item label="总金额(元)" prop="jine">
                  <el-input-number v-model="orderForm.jine" :precision="2" :min="0" :controls="false" style="width: 100%" />
                </el-form-item>
                <el-form-item label="里程表数">
                  <el-input-number v-model="orderForm.gonglinum" :precision="0" :min="0" :controls="false" style="width: 100%" />
                </el-form-item>
                <el-form-item label="申报人">
                  <el-input v-model="orderForm.bxren" />
                </el-form-item>
                <div class="req-tip">带 * 的为必填项</div>
              </el-tab-pane>

              <el-tab-pane label="图片" name="images">
                <input ref="stageInput" type="file" accept=".jpg,.jpeg,.png,.gif,.bmp,.webp" multiple
                  style="display: none" @change="onStageImages" />
                <div class="pic-wrap">
                  <el-button size="small" @click="stageInput.click()">选择图片</el-button>
                  <span class="tip">支持 JPG/PNG，保存维修单后自动上传</span>
                </div>
                <div v-if="!editingOrder" class="img-grid">
                  <div v-for="(s, i) in stagedImages" :key="s.url" class="img-item">
                    <img :src="s.url" />
                    <el-button link type="danger" size="small" @click="removeStaged(i)">删除</el-button>
                  </div>
                </div>
                <template v-else>
                  <input ref="editImageInput" type="file" accept=".jpg,.jpeg,.png,.gif,.bmp,.webp" multiple
                    style="display: none" @change="onEditImagePick" />
                  <div class="pic-wrap">
                    <el-button size="small" @click="editImageInput.click()">上传图片</el-button>
                  </div>
                  <div class="img-grid">
                    <div v-for="img in orderImages" :key="img.id" class="img-item">
                      <img v-if="img.src && !img.error" :src="img.src" @error="img.error = true" />
                      <div v-else class="img-missing">历史图片文件缺失</div>
                      <el-button link type="danger" size="small" @click="removeOrderImage(img)">删除</el-button>
                    </div>
                    <div v-for="(s, i) in stagedImages" :key="s.url" class="img-item">
                      <img :src="s.url" />
                      <el-button link type="danger" size="small" @click="removeStaged(i)">删除</el-button>
                    </div>
                  </div>
                  <div v-if="!orderImages.length && !stagedImages.length" class="tip">暂无图片</div>
                </template>
              </el-tab-pane>
            </el-tabs>
          </el-form>
        </div>
      </div>
      <template #footer>
        <el-button @click="orderDialog = false">取消</el-button>
        <el-button v-if="!editingOrder" @click="saveOrder(true)">保存且继续</el-button>
        <el-button type="primary" @click="saveOrder(false)">保存</el-button>
      </template>
    </el-dialog>

    <!-- 添加 / 编辑维修明细 -->
    <el-dialog v-model="detailDialog" :title="mxForm.id ? '编辑维修明细' : '添加维修明细'"
      :width="mxForm.id ? '720px' : 'min(1200px, 96vw)'" top="5vh" :close-on-click-modal="false">
      <div class="order-layout">
        <div v-if="!mxForm.id" class="order-left">
          <div class="left-title">{{ detailOrder?.chehao }} 的所有维修明细记录</div>
          <el-input v-model="mxKeyword" placeholder="输入项目关键字过滤" clearable
            style="width: 100%; margin-bottom: 8px" @input="onMxKeywordInput" />
          <el-table :data="mxList" size="small" border height="360px" v-loading="mxLoading">
            <el-table-column prop="pjorgs" label="工时材料" width="90" />
            <el-table-column prop="xiangmu" label="项目名称" min-width="140" show-overflow-tooltip />
            <el-table-column prop="shuliang" label="数量" width="60" align="right" />
            <el-table-column prop="danjia" label="单价" width="80" align="right">
              <template #default="{ row }">{{ money(row.danjia) }}</template>
            </el-table-column>
            <el-table-column prop="zonge" label="总金额" width="90" align="right">
              <template #default="{ row }">{{ money(row.zonge) }}</template>
            </el-table-column>
            <el-table-column prop="jcriqi" label="维修单日期" width="105" />
            <el-table-column label="操作" width="100" fixed="right">
              <template #default="{ row: d }">
                <el-button link type="primary" size="small" @click="openEditDetail(detailOrder, d)">修改</el-button>
                <el-button link type="danger" size="small" @click="removeDetail(d)">删除</el-button>
              </template>
            </el-table-column>
            <template #empty><span /></template>
          </el-table>
        </div>

        <div class="order-right">
          <el-form ref="mxFormRef" :model="mxForm" :rules="mxRules" label-width="112px">
            <el-form-item v-if="!mxForm.id" label="维修单流水号">
              <el-input :model-value="detailOrder?.ID" readonly />
            </el-form-item>
            <el-form-item label="工时配件" prop="pjorgs">
              <el-select v-model="mxForm.pjorgs" placeholder="请选择类型" style="width: 100%">
                <el-option v-for="t in dicts.pjorgs" :key="t" :label="t" :value="t" />
              </el-select>
            </el-form-item>
            <el-form-item label="项目关键字">
              <el-input v-model="mxForm.gjz" />
            </el-form-item>
            <el-form-item label="项目名称" prop="xiangmu">
              <el-input v-model="mxForm.xiangmu" />
            </el-form-item>
            <el-form-item label="品牌规格型号">
              <el-input v-model="mxForm.guige" />
            </el-form-item>
            <el-form-item label="原单价(元)" prop="zkqiandanjia">
              <div class="price-row">
                <el-input-number v-model="mxForm.zkqiandanjia" :precision="2" :min="0" :controls="false"
                  style="width: 150px" @change="refreshRemaining" />
                <span class="zk-text">× {{ zkValue }}</span>
                <span class="inner-label">折后单价：</span>
                <el-input :model-value="money(mxDanjia)" readonly style="width: 150px" />
              </div>
            </el-form-item>
            <el-form-item label="数量" prop="shuliang">
              <el-input-number v-model="mxForm.shuliang" :precision="2" :min="0" :controls="false"
                style="width: 100%" @change="refreshRemaining" />
            </el-form-item>
            <el-form-item label="总金额">
              <el-input :model-value="money(mxZonge)" readonly />
            </el-form-item>
            <el-form-item label="总额尚需">
              <el-input :model-value="mxRemainingText" readonly />
            </el-form-item>
          </el-form>
        </div>
      </div>
      <template #footer>
        <el-button @click="detailDialog = false">取消</el-button>
        <el-button type="primary" @click="saveDetail">保存</el-button>
      </template>
    </el-dialog>

    <!-- 图片查看 -->
    <el-dialog v-model="imageDialog" :title="`维修单图片 - ${imageOrder?.chehao || ''} (${imageOrder?.ID || ''})`" width="760px">
      <div class="img-grid">
        <div v-for="img in imageList" :key="img.id" class="img-item">
          <img v-if="img.src && !img.error" :src="img.src" @error="img.error = true" />
          <div v-else class="img-missing">历史图片文件缺失<br /><small>旧生产服务器 Upload 目录未拷入</small></div>
        </div>
      </div>
      <div v-if="!imageList.length" class="tip">暂无图片</div>
    </el-dialog>

    <!-- 年度维修费 -->
    <el-dialog v-model="chartDialog" title="车辆维修费" width="860px" @closed="onChartClosed">
      <div ref="chartEl" v-loading="chartLoading" style="width: 100%; height: 480px" />
    </el-dialog>
  </div>
</template>

<style scoped>
.repair-page { display: flex; flex-direction: column; gap: 10px; }
.filter-card :deep(.el-card__body) { padding: 10px 14px; }
.filter-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 12px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }
.sub-wrap { padding: 8px 12px 12px 46px; position: sticky; left: 0;
  width: min(1180px, calc(100vw - 280px)); overflow-x: auto; box-sizing: border-box; }
.sub-title { font-weight: 600; margin-bottom: 6px; display: flex; align-items: center; gap: 10px; }
.sub-empty { color: #909399; font-weight: 400; font-size: 12px; }
.order-layout { display: flex; gap: 16px; align-items: flex-start; }
.order-left { flex: 0 0 44%; max-width: 560px; }
.order-right { flex: 1 1 auto; min-width: 0; }
.left-title { font-weight: 600; margin-bottom: 6px; }
.order-layout :deep(.el-form-item) { margin-bottom: 12px; }
.unit-row, .price-row { display: flex; align-items: center; gap: 8px; width: 100%; }
.inner-label { color: #606266; white-space: nowrap; }
.zk-text { color: #b3261e; white-space: nowrap; }
.req-tip { color: #909399; font-size: 12px; padding-left: 92px; }
.pic-wrap { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
.tip { color: #909399; font-size: 12px; }
.img-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.img-item { border: 1px solid #e4e7ed; border-radius: 4px; padding: 4px; text-align: center; }
.img-item img { width: 100%; height: 110px; object-fit: cover; display: block; }
.img-missing { height: 110px; display: flex; flex-direction: column; align-items: center;
  justify-content: center; color: #b3261e; font-size: 12px; background: #fafafa; }
@media (max-width: 900px) {
  .order-layout { flex-direction: column; }
  .order-left { flex: 1 1 auto; max-width: none; width: 100%; }
}
</style>
