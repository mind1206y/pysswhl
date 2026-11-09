<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  addAccident, batchInspect, createImageToken, createVehicle, deleteAccident,
  deleteAccidentImage, deleteVehicle, deleteVehicleImage, exportVehicles,
  exportVehiclesPdf, getOilMonthStat, getVehicle, getVehicleDicts, inspectVehicle,
  listAccidents, listAccidentImages, listVehicles, scrapVehicle, undoInspectVehicle,
  updateAccident, updateVehicle, uploadAccidentImages, uploadVehicleImages,
} from '@/api/vehicle'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
// view = 模块入口 + 日常操作(增删改/年检/出险登记); manage = 删除/报废/图片附件类管理操作
const canOperate = computed(() => auth.hasPerm('vehicle:view'))
const canManage = computed(() => auth.hasPerm('vehicle:manage'))
const isSuper = computed(() => !!auth.user?.is_superuser)
const yearNow = new Date().getFullYear()

// ===== 字典 =====
const dicts = reactive({
  lx: [], yongtu: [], oil: [], zeren: [], departments: [], years: [],
  current_year: yearNow, reminder: [], lx_used: [], yongtu_used: [],
})

// ===== 列设置(旧系统 31 列全量复刻,可按需隐藏;默认全显) =====
const ALL_COLUMNS = [
  { prop: 'chehao', label: '车号', width: 100, fixed: 'left', sortable: true },
  { prop: 'lx', label: '类型', width: 140 },
  { prop: 'pinpai', label: '品牌', width: 80 },
  { prop: 'bumen', label: '部门', width: 100 },
  { prop: 'chuchang', label: '注册日期', width: 105, sortable: true },
  { prop: 'oilYear', label: '年度合计升数(L)', width: 130, sortable: true },
  { prop: 'tps', label: '图片', width: 78 },
  { prop: 'useCountYear', label: '总派车数(次)', width: 115, sortable: true },
  { prop: 'wxCountYear', label: '年度维修', width: 130, sortable: true },
  { prop: 'oilStat', label: '加油明细', width: 84 },
  { prop: 'exportPdf', label: '导出PDF', width: 84 },
  { prop: 'NextInspectionDate', label: '下次年检', width: 108, sortable: true },
  { prop: 'jls', label: '出险数', width: 74, sortable: true },
  { prop: 'xinghao', label: '型号', width: 100 },
  { prop: 'IsInspected', label: '年检状态', width: 145 },
  { prop: 'ReminderLevel', label: '年检剩余天数', width: 200 },
  { prop: 'oil', label: '油品', width: 68 },
  { prop: 'jiashiyuan', label: '使用人', width: 86 },
  { prop: 'yongtu', label: '车辆用途', width: 92 },
  { prop: 'caozuo', label: '操作员', width: 86 },
  { prop: 'spzt', label: '审批状态', width: 92 },
  { prop: 'zt', label: '车辆状态', width: 88 },
  { prop: 'InspectionDate', label: '标注年检日期', width: 118 },
  { prop: 'txjb', label: '提醒级别', width: 96 },
  { prop: 'ifnj', label: '年检否', width: 80 },
  { prop: 'zuihoutime', label: '最后操作日期', width: 145 },
  { prop: 'ID', label: '编号', width: 70 },
  { prop: 'pingshi', label: '办公地点', width: 110 },
  { prop: 'zhoumo', label: '停放点', width: 110 },
  { prop: 'bm', label: '原部门', width: 100 },
]
const COL_KEY = 'vehicle_visible_columns'
function defaultCols() { return ALL_COLUMNS.map((c) => c.prop) }
const visibleCols = ref(JSON.parse(localStorage.getItem(COL_KEY) || 'null') || defaultCols())
const shownColumns = computed(() => ALL_COLUMNS.filter((c) => visibleCols.value.includes(c.prop)))
const colDialog = ref(false)
const colDraft = ref([])
function openColDialog() { colDraft.value = [...visibleCols.value]; colDialog.value = true }
function applyCols() {
  visibleCols.value = ALL_COLUMNS.filter((c) => colDraft.value.includes(c.prop)).map((c) => c.prop)
  localStorage.setItem(COL_KEY, JSON.stringify(visibleCols.value))
  colDialog.value = false
}

// ===== 列表与筛选 =====
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const sortProp = ref('')
const sortOrder = ref('')
const filters = reactive({
  keyword: '', bmid: null, chellx: [], chelyt: '', year: yearNow,
  scrap: false, nocd: false, next_month: false,
})

function buildParams() {
  const p = { page: page.value, size: size.value, year: filters.year }
  if (filters.keyword) p.keyword = filters.keyword
  if (filters.bmid) p.bmid = filters.bmid
  if (filters.chellx.length) p.chellx = filters.chellx.join(',')
  if (filters.chelyt) p.chelyt = filters.chelyt
  if (filters.scrap) p.scrap = true
  if (filters.nocd) p.nocd = true
  if (filters.next_month) p.next_month = true
  if (sortProp.value) { p.sort = sortProp.value; p.order = sortOrder.value }
  return p
}
async function load() {
  loading.value = true
  try {
    const data = await listVehicles(buildParams())
    rows.value = data.items
    total.value = data.total
  } finally { loading.value = false }
}
function search() { page.value = 1; load() }
function resetFilters() {
  Object.assign(filters, {
    keyword: '', bmid: null, chellx: [], chelyt: '', year: yearNow,
    scrap: false, nocd: false, next_month: false,
  })
  sortProp.value = ''; sortOrder.value = ''
  search()
}
function onSortChange({ prop, order }) {
  sortProp.value = order ? prop : ''
  sortOrder.value = order === 'descending' ? 'desc' : 'asc'
  search()
}
function rowClass({ row }) {
  if (row.yongtu === '110联动车') return 'row-110'
  if (row.yongtu === '抄表用车') return 'row-chaobiao'
  return ''
}
function fmt(v, len = 10) { return v ? String(v).slice(0, len) : '' }
function money(v) { return Number(v || 0).toFixed(2).replace(/\.00$/, '') }

onMounted(async () => {
  const d = await getVehicleDicts()
  Object.assign(dicts, d)
  filters.year = d.current_year || yearNow
  load()
})

// ===== 勾选 =====
const selection = ref([])
function onSelectionChange(v) { selection.value = v }
function requireOne() {
  if (selection.value.length !== 1) { ElMessage.warning('请选中且仅选中一条记录'); return null }
  return selection.value[0]
}

// ===== 新增 / 编辑 =====
const editDialog = ref(false)
const editingId = ref(null)
const editTab = ref('basic')
const editFormRef = ref()
const blankForm = () => ({
  bmid: null, yongtu: '', oil: '', oilcard: '', lx: '', chehao: '', pinpai: '',
  xinghao: '', chuchang: '', telphone: '', pingshi: '', zhoumo: '',
  grriqi: '', jiage: null, etc: '', danganhao: '', syxingzhi: '', zws: null,
  fadongjihao: '', chejiahao: '', pailiang: '', jiashiyuan: '', jsz: '',
  zt: 1,
})
const form = reactive(blankForm())
const editRules = {
  chehao: [{ required: true, message: '请输入车号', trigger: 'blur' }],
  lx: [{ required: true, message: '请选择车辆类型', trigger: 'change' }],
}
const formDeptOptions = computed(() => {
  if (isSuper.value) return dicts.departments
  return (auth.user?.departments || []).map((d) => ({ id: d.id, name: d.name }))
})
const deptLocked = computed(() => !isSuper.value && (auth.user?.departments || []).length <= 1)

function openCreate() {
  editingId.value = null
  Object.assign(form, blankForm())
  form.bmid = formDeptOptions.value[0]?.id ?? null
  editTab.value = 'basic'
  editDialog.value = true
}
function openEdit(row) {
  if (!canOperate.value) return
  editingId.value = row.id
  const obj = blankForm()
  for (const k of Object.keys(obj)) {
    if (k === 'zt') obj[k] = row.zt || row.delf || 1
    else if (['chuchang', 'grriqi'].includes(k)) obj[k] = row[k] || null
    else obj[k] = row[k] ?? (['jiage', 'zws'].includes(k) ? null : '')
  }
  Object.assign(form, obj)
  editTab.value = 'basic'
  editDialog.value = true
  loadEditImages(row.id)
}
function buildPayload() {
  const p = { ...form }
  for (const k of ['chuchang', 'grriqi']) if (!p[k]) p[k] = null
  for (const k of ['jiage', 'zws']) if (p[k] === '' || p[k] === undefined) p[k] = null
  delete p.zt // 车辆状态走独立的报废接口
  return p
}
async function submitEdit() {
  await editFormRef.value.validate()
  const payload = buildPayload()
  if (editingId.value) await updateVehicle(editingId.value, payload)
  else await createVehicle(payload)
  ElMessage.success(editingId.value ? '修改成功，资料已重新进入待审批' : '添加成功')
  editDialog.value = false
  load()
}

// ===== 编辑弹窗内的图片 =====
const editImages = ref([])
async function loadEditImages(id) {
  const info = await getVehicle(id)
  editImages.value = await resolveImages(info.images || [], 'car')
}
async function resolveImages(list, kind) {
  const out = []
  for (const img of list) {
    let src = ''
    try { src = (await createImageToken(img.id, kind)).url } catch { /* 忽略 */ }
    out.push({ ...img, src, error: false, kind })
  }
  return out
}
async function onEditImagePick(e) {
  const files = [...e.target.files]
  if (!files.length) return
  const fd = new FormData()
  files.forEach((f) => fd.append('files', f))
  await uploadVehicleImages(editingId.value, fd)
  e.target.value = ''
  ElMessage.success('图片已上传')
  loadEditImages(editingId.value)
}
async function removeEditImage(img) {
  await ElMessageBox.confirm('确定删除这张图片？', '提示', { type: 'warning' })
  await deleteVehicleImage(img.id)
  loadEditImages(editingId.value)
}

// ===== 工具栏操作 =====
async function doDelete() {
  const row = requireOne(); if (!row) return
  await ElMessageBox.confirm(`确定删除车辆 ${row.chehao}？有派车/加油记录的车辆不能删除。`, '提示', { type: 'warning' })
  await deleteVehicle(row.id)
  ElMessage.success('已删除'); load()
}
async function doScrap() {
  const row = requireOne(); if (!row) return
  await ElMessageBox.confirm(`确定将 ${row.chehao} 标记为报废？`, '提示', { type: 'warning' })
  await scrapVehicle(row.id)
  ElMessage.success('已报废'); load()
}
async function doMark(row) {
  await inspectVehicle(row.id)
  ElMessage.success('已标注年检'); load()
}
async function doUndo(row) {
  await undoInspectVehicle(row.id)
  ElMessage.success('已撤销年检'); load()
}
async function doBatchMark() {
  if (!selection.value.length) { ElMessage.warning('请先勾选车辆'); return }
  const ids = selection.value.filter((r) => !r.IsInspected).map((r) => r.id)
  if (!ids.length) { ElMessage.warning('所选车辆均已标注年检'); return }
  await ElMessageBox.confirm(`确定将选中的 ${ids.length} 辆车标注为年检完成？`, '批量标记年检', { type: 'warning' })
  const res = await batchInspect(ids)
  ElMessage.success(`成功 ${res.success} 辆${res.failed.length ? `，跳过 ${res.failed.length} 辆` : ''}`)
  load()
}
async function doExport() { await exportVehicles(buildParams()); ElMessage.success('已导出 Excel') }
async function doExportPdf(row) {
  const ids = row ? [row.id] : selection.value.map((r) => r.id)
  if (!ids.length) { ElMessage.warning('请先勾选车辆'); return }
  await exportVehiclesPdf(ids)
  ElMessage.success('已导出 PDF')
}

// ===== 行展开:出险记录 =====
const accidents = reactive({})
const accidentLoading = reactive({})
async function onExpand(row, expanded) {
  if (!expanded) return
  accidentLoading[row.id] = true
  try {
    accidents[row.id] = await listAccidents(row.id, filters.year)
  } finally { accidentLoading[row.id] = false }
}
const cxDialog = ref(false)
const cxEditing = ref(null)
const cxCarId = ref(null)
const cxFormRef = ref()
const blankCx = () => ({
  riqi: '', zeren: '', jiashiyuan: '', jine: null, miaoshu: '',
  dizhi: '', gongli: null, bm: '',
})
const cxForm = reactive(blankCx())
function openCxCreate(row) {
  cxCarId.value = row ? row.id : (requireOne()?.id ?? null)
  if (!cxCarId.value) return
  cxEditing.value = null
  Object.assign(cxForm, blankCx(), { bm: row?.bumen || '' })
  cxDialog.value = true
}
function openCxEdit(row, acc) {
  cxCarId.value = row.id
  cxEditing.value = acc.id
  Object.assign(cxForm, blankCx(), {
    riqi: acc.riqi || '', zeren: acc.zeren || '', jiashiyuan: acc.jiashiyuan || '',
    jine: acc.jine, miaoshu: acc.miaoshu || '', dizhi: acc.dizhi || '',
    gongli: acc.gongli, bm: acc.bm || '',
  })
  cxDialog.value = true
}
async function submitCx() {
  if (!cxForm.riqi) { ElMessage.warning('请选择出险日期'); return }
  const data = { ...cxForm, jine: cxForm.jine === '' ? null : cxForm.jine,
    gongli: cxForm.gongli === '' ? null : cxForm.gongli }
  if (cxEditing.value) await updateAccident(cxEditing.value, data)
  else await addAccident(cxCarId.value, data)
  ElMessage.success(cxEditing.value ? '已修改' : '已添加')
  cxDialog.value = false
  accidents[cxCarId.value] = await listAccidents(cxCarId.value, filters.year)
  load()
}
async function removeCx(row, acc) {
  await ElMessageBox.confirm('确定删除这条出险记录？', '提示', { type: 'warning' })
  await deleteAccident(acc.id)
  ElMessage.success('已删除')
  accidents[row.id] = await listAccidents(row.id, filters.year)
  load()
}

// ===== 加油月度统计 =====
const oilDialog = ref(false)
const oilYear = ref(yearNow)
const oilData = ref(null)
const oilCar = ref(null)
async function openOil(row, year) {
  oilCar.value = row
  oilYear.value = year || filters.year
  oilData.value = await getOilMonthStat(row.id, oilYear.value)
  oilDialog.value = true
}
async function reloadOil() {
  oilData.value = await getOilMonthStat(oilCar.value.id, oilYear.value)
}

// ===== 图片查看弹窗 =====
const imageDialog = ref(false)
const imageCar = ref(null)
const imageList = ref([])
async function openImages(row) {
  imageCar.value = row
  imageList.value = await resolveImages(row.tps || [], 'car')
  imageDialog.value = true
}
async function onImagePick(e) {
  const files = [...e.target.files]
  if (!files.length) return
  const fd = new FormData()
  files.forEach((f) => fd.append('files', f))
  await uploadVehicleImages(imageCar.value.id, fd)
  e.target.value = ''
  ElMessage.success('图片已上传')
  const info = await getVehicle(imageCar.value.id)
  imageList.value = await resolveImages(info.images || [], 'car')
  load()
}
async function removeImage(img) {
  await ElMessageBox.confirm('确定删除这张图片？', '提示', { type: 'warning' })
  await deleteVehicleImage(img.id)
  imageList.value = imageList.value.filter((i) => i.id !== img.id)
  load()
}

// ===== 出险图片 =====
const cxImageDialog = ref(false)
const cxImageList = ref([])
const cxImageAcc = ref(null)
async function openCxImages(acc) {
  cxImageAcc.value = acc
  const list = await listAccidentImages(acc.id)
  cxImageList.value = await resolveImages(list, 'accident')
  cxImageDialog.value = true
}
async function onCxImagePick(e) {
  const files = [...e.target.files]
  if (!files.length) return
  const fd = new FormData()
  files.forEach((f) => fd.append('files', f))
  await uploadAccidentImages(cxImageAcc.value.id, fd)
  e.target.value = ''
  cxImageList.value = await resolveImages(await listAccidentImages(cxImageAcc.value.id), 'accident')
  ElMessage.success('图片已上传')
}
async function removeCxImage(img) {
  await deleteAccidentImage(img.id)
  cxImageList.value = cxImageList.value.filter((i) => i.id !== img.id)
}

// ===== 年检功能说明 =====
const docDialog = ref(false)
</script>

<template>
  <div class="vehicle-page">
    <!-- 查询条件(照旧 north 区) -->
    <el-card shadow="never" class="filter-card">
      <div class="filter-title">车辆管理系统</div>
      <el-form inline class="filter-form">
        <el-form-item label="关键字">
          <el-input v-model="filters.keyword" placeholder="车号、品牌等..." clearable
            style="width: 190px" @keyup.enter="search" />
        </el-form-item>
        <el-form-item label="部门">
          <el-select v-model="filters.bmid" placeholder="选择部门" clearable filterable style="width: 140px">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="车辆类型">
          <el-select v-model="filters.chellx" multiple collapse-tags collapse-tags-tooltip
            placeholder="车辆类型" clearable style="width: 190px">
            <el-option v-for="t in dicts.lx" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="用途">
          <el-select v-model="filters.chelyt" placeholder="选择用途" clearable style="width: 125px">
            <el-option v-for="t in dicts.yongtu" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="统计年度">
          <el-select v-model="filters.year" style="width: 105px" @change="search">
            <el-option v-for="y in dicts.years" :key="y" :label="`${y}年`" :value="y" />
          </el-select>
        </el-form-item>
        <el-form-item label="车辆状态">
          <el-switch v-model="filters.scrap" active-text="报废" inactive-text="正常"
            inline-prompt style="width: 58px" @change="search" />
        </el-form-item>
        <el-form-item label="油卡筛选">
          <el-switch v-model="filters.nocd" active-text="非油卡" inactive-text="所有"
            inline-prompt style="width: 66px" @change="search" />
        </el-form-item>
        <el-form-item label="下月年检">
          <el-checkbox v-model="filters.next_month" @change="search" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 工具栏(照旧 datagrid toolbar) -->
    <div class="toolbar">
      <template v-if="canOperate">
        <el-button type="primary" size="small" @click="openCreate">添加</el-button>
        <el-button size="small" @click="() => { const r = requireOne(); if (r) openEdit(r) }">编辑</el-button>
        <el-button v-if="canManage" size="small" @click="doDelete">删除</el-button>
        <el-button v-if="canManage" size="small" @click="doScrap">报废</el-button>
        <el-button size="small" @click="openCxCreate()">添加出险记录</el-button>
        <el-button size="small" @click="doBatchMark">批量标记年检完成</el-button>
      </template>
      <el-button size="small" @click="doExport">导出 Excel</el-button>
      <el-button size="small" @click="doExportPdf()">批量导出 PDF</el-button>
      <el-button size="small" @click="openColDialog">显示列设置</el-button>
      <el-button size="small" text type="primary" @click="docDialog = true">年检提醒功能说明</el-button>
      <span class="toolbar-hint">共 {{ total }} 辆 · 双击行可编辑 · 展开行查看出险记录</span>
    </div>

    <!-- 主表格 -->
    <el-table v-loading="loading" :data="rows" border stripe size="small" height="calc(100vh - 290px)"
      row-key="id" :row-class-name="rowClass" @selection-change="onSelectionChange"
      @sort-change="onSortChange" @row-dblclick="openEdit" @expand-change="onExpand">
      <el-table-column type="selection" width="42" fixed="left" />
      <el-table-column type="expand" width="40" fixed="left">
        <template #default="{ row }">
          <div class="sub-wrap">
            <div class="sub-title">
              出险记录（{{ filters.year }}年）
              <el-button v-if="canOperate" link type="primary" size="small" @click="openCxCreate(row)">+ 添加</el-button>
              <span v-if="!accidentLoading[row.id] && !(accidents[row.id] || []).length" class="sub-empty">
                该年度暂无出险记录
              </span>
            </div>
            <el-table :data="accidents[row.id] || []" size="small" border
              style="min-width: 1120px" v-loading="accidentLoading[row.id]">
              <el-table-column prop="id" label="编号" width="65" />
              <el-table-column prop="bm" label="部门" width="110" />
              <el-table-column prop="jiashiyuan" label="责任人" width="90" />
              <el-table-column prop="riqi" label="日期" width="105" />
              <el-table-column prop="zeren" label="责任" width="90" />
              <el-table-column prop="dizhi" label="地点" width="120" />
              <el-table-column prop="miaoshu" label="描述" min-width="220" show-overflow-tooltip />
              <el-table-column prop="jine" label="金额（元）" width="100" />
              <el-table-column prop="gongli" label="公里" width="80" />
              <el-table-column prop="caozuo" label="记录人" width="90" />
              <el-table-column prop="zuihou" label="最后操作日期" width="145" />
              <el-table-column label="图片" width="80">
                <template #default="{ row: acc }">
                  <el-button link type="primary" size="small" @click="openCxImages(acc)">查看</el-button>
                </template>
              </el-table-column>
              <el-table-column v-if="canOperate" label="操作" width="120" fixed="right">
                <template #default="{ row: acc }">
                  <el-button link type="primary" size="small" @click="openCxEdit(row, acc)">编辑</el-button>
                  <el-button link type="danger" size="small" @click="removeCx(row, acc)">删除</el-button>
                </template>
              </el-table-column>
              <template #empty><span /></template>
            </el-table>
          </div>
        </template>
      </el-table-column>

      <el-table-column v-for="col in shownColumns" :key="col.prop"
        :prop="col.prop" :label="col.label" :width="col.width"
        :fixed="col.fixed" :sortable="col.sortable ? 'custom' : false" show-overflow-tooltip>
        <template #default="{ row }">
          <!-- 图片 -->
          <el-button v-if="col.prop === 'tps'" link type="primary" size="small" @click="openImages(row)">
            {{ row.tps?.length || 0 }} 张
          </el-button>
          <!-- 年度合计升数 -->
          <span v-else-if="col.prop === 'oilYear'">{{ money(row.oilYear) }}</span>
          <!-- 总派车数 -->
          <span v-else-if="col.prop === 'useCountYear'">{{ row.useCountYear || 0 }}</span>
          <!-- 年度维修(悬停看近五年) -->
          <el-popover v-else-if="col.prop === 'wxCountYear'" placement="bottom" :width="260" trigger="hover">
            <template #reference>
              <span class="link-like">{{ row.wxCountYear || 0 }}次 / {{ money(row.wxAmountYear) }}元</span>
            </template>
            <div class="pop-title">近五年维修统计</div>
            <div v-for="w in (row.wx5Years || [])" :key="w.year" class="pop-row">
              <span>{{ w.year }}年</span><span>{{ w.count }}次</span><span>{{ money(w.amount) }}元</span>
            </div>
            <div v-if="!row.wx5Years?.length" class="pop-empty">近五年无维修记录</div>
          </el-popover>
          <!-- 加油明细 -->
          <el-button v-else-if="col.prop === 'oilStat'" link type="primary" size="small"
            @click="openOil(row)">明细</el-button>
          <!-- 导出 PDF -->
          <el-button v-else-if="col.prop === 'exportPdf'" link type="primary" size="small"
            @click="doExportPdf(row)">PDF</el-button>
          <!-- 出险数 -->
          <span v-else-if="col.prop === 'jls'">{{ row.jls || 0 }}</span>
          <!-- 年检状态 + 标记/撤销 -->
          <div v-else-if="col.prop === 'IsInspected'" class="inspect-cell">
            <el-tag :type="row.IsInspected ? 'success' : 'warning'" size="small">
              {{ !row.chuchang ? '-' : (row.IsInspected ? '已年检' : '未年检') }}
            </el-tag>
            <el-button v-if="canOperate && row.chuchang" link :type="row.IsInspected ? 'info' : 'primary'"
              size="small" @click="row.IsInspected ? doUndo(row) : doMark(row)">
              {{ row.IsInspected ? '撤销' : '标记' }}
            </el-button>
          </div>
          <!-- 年检剩余天数进度条 -->
          <div v-else-if="col.prop === 'ReminderLevel'" class="remind-cell">
            <el-progress :percentage="row.reminder_percent || 0" :color="row.reminder_color"
              :stroke-width="8" :show-text="false" />
            <span :style="{ color: row.reminder_color }">{{ row.reminder_text }}</span>
          </div>
          <!-- 审批状态 -->
          <el-tag v-else-if="col.prop === 'spzt'" :type="row.spzt === '待审批' ? 'warning' : 'success'" size="small">
            {{ row.spzt || '-' }}
          </el-tag>
          <!-- 车辆状态 -->
          <el-tag v-else-if="col.prop === 'zt'" :type="row.zt === 2 ? 'danger' : 'success'" size="small">
            {{ row.zt === 2 ? '报废' : '正常' }}
          </el-tag>
          <!-- 提醒级别 -->
          <span v-else-if="col.prop === 'txjb'">
            {{ dicts.reminder.find((r) => r.value === row.txjb)?.label || '-' }}
          </span>
          <!-- 年检否 -->
          <span v-else-if="col.prop === 'ifnj'">{{ row.ifnj ? '已年检' : '未检' }}</span>
          <!-- 编号 -->
          <span v-else-if="col.prop === 'ID'">{{ row.id }}</span>
          <!-- 日期/时间 -->
          <span v-else-if="['chuchang', 'InspectionDate', 'NextInspectionDate'].includes(col.prop)">
            {{ fmt(row[col.prop]) }}
          </span>
          <span v-else-if="col.prop === 'zuihoutime'">{{ fmt(row.zuihoutime, 16) }}</span>
          <span v-else>{{ row[col.prop] ?? '' }}</span>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[20, 60, 100]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>

    <!-- 添加 / 编辑车辆 -->
    <el-dialog v-model="editDialog" :title="editingId ? '车辆明细数据' : '添加车辆明细'"
      width="840px" top="5vh" :close-on-click-modal="false">
      <el-tabs v-model="editTab">
        <el-tab-pane label="车辆信息" name="basic">
          <el-form ref="editFormRef" :model="form" :rules="editRules" label-width="86px" class="form-grid">
            <el-form-item label="部门">
              <el-select v-model="form.bmid" :disabled="deptLocked" clearable filterable style="width: 100%">
                <el-option v-for="d in formDeptOptions" :key="d.id" :label="d.name" :value="d.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="车辆用途">
              <el-select v-model="form.yongtu" clearable filterable allow-create style="width: 100%">
                <el-option v-for="t in dicts.yongtu" :key="t" :label="t" :value="t" />
              </el-select>
            </el-form-item>
            <el-form-item label="油品">
              <el-select v-model="form.oil" clearable style="width: 100%">
                <el-option v-for="t in dicts.oil" :key="t" :label="t" :value="t" />
              </el-select>
            </el-form-item>
            <el-form-item label="油卡号"><el-input v-model="form.oilcard" /></el-form-item>
            <el-form-item label="类型" prop="lx">
              <el-select v-model="form.lx" filterable style="width: 100%">
                <el-option v-for="t in dicts.lx" :key="t" :label="t" :value="t" />
              </el-select>
            </el-form-item>
            <el-form-item label="车号" prop="chehao"><el-input v-model="form.chehao" /></el-form-item>
            <el-form-item label="品牌"><el-input v-model="form.pinpai" /></el-form-item>
            <el-form-item label="型号"><el-input v-model="form.xinghao" /></el-form-item>
            <el-form-item label="注册日期">
              <el-date-picker v-model="form.chuchang" type="date" value-format="YYYY-MM-DD"
                clearable style="width: 100%" />
            </el-form-item>
            <el-form-item label="电话"><el-input v-model="form.telphone" /></el-form-item>
            <el-form-item label="办公地点"><el-input v-model="form.pingshi" /></el-form-item>
            <el-form-item label="停放点"><el-input v-model="form.zhoumo" /></el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="车辆信息2" name="extra">
          <el-form :model="form" label-width="86px" class="form-grid">
            <el-form-item label="购置日期">
              <el-date-picker v-model="form.grriqi" type="date" value-format="YYYY-MM-DD"
                clearable style="width: 100%" />
            </el-form-item>
            <el-form-item label="购置价格"><el-input-number v-model="form.jiage" :precision="2" :min="0"
              controls-position="right" style="width: 100%" /></el-form-item>
            <el-form-item label="ETC"><el-input v-model="form.etc" /></el-form-item>
            <el-form-item label="档案号"><el-input v-model="form.danganhao" /></el-form-item>
            <el-form-item label="使用性质"><el-input v-model="form.syxingzhi" /></el-form-item>
            <el-form-item label="座位数"><el-input-number v-model="form.zws" :precision="0" :min="0"
              controls-position="right" style="width: 100%" /></el-form-item>
            <el-form-item label="发动机号"><el-input v-model="form.fadongjihao" /></el-form-item>
            <el-form-item label="车架号"><el-input v-model="form.chejiahao" /></el-form-item>
            <el-form-item label="排量"><el-input v-model="form.pailiang" /></el-form-item>
            <el-form-item label="使用人"><el-input v-model="form.jiashiyuan" /></el-form-item>
            <el-form-item label="驾照号"><el-input v-model="form.jsz" /></el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="图片" name="images">
          <div v-if="!editingId" class="tip">保存车辆后即可查看、上传图片</div>
          <div v-else-if="!canManage" class="tip">可查看图片；上传/删除图片需要「车辆管理」权限</div>
          <template v-else>
            <label class="upload-btn">
              选择图片上传
              <input type="file" accept=".jpg,.jpeg,.png,.gif,.bmp,.webp" multiple
                style="display: none" @change="onEditImagePick" />
            </label>
            <div class="img-grid">
              <div v-for="img in editImages" :key="img.id" class="img-item">
                <img v-if="img.src && !img.error" :src="img.src" @error="img.error = true" />
                <div v-else class="img-missing">图片文件缺失</div>
                <el-button link type="danger" size="small" @click="removeEditImage(img)">删除</el-button>
              </div>
              <div v-if="!editImages.length" class="tip">暂无图片</div>
            </div>
          </template>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" @click="submitEdit">{{ editingId ? '确定修改' : '确定增加' }}</el-button>
      </template>
    </el-dialog>

    <!-- 出险记录 -->
    <el-dialog v-model="cxDialog" :title="cxEditing ? '显示出险记录' : '添加出险记录'" width="640px">
      <el-form :model="cxForm" label-width="90px" class="form-grid">
        <el-form-item label="部门"><el-input v-model="cxForm.bm" /></el-form-item>
        <el-form-item label="日期"><el-date-picker v-model="cxForm.riqi" type="date"
          value-format="YYYY-MM-DD" style="width: 100%" /></el-form-item>
        <el-form-item label="责任">
          <el-select v-model="cxForm.zeren" clearable style="width: 100%">
            <el-option v-for="t in dicts.zeren" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="责任人"><el-input v-model="cxForm.jiashiyuan" /></el-form-item>
        <el-form-item label="金额（元）"><el-input-number v-model="cxForm.jine" :precision="2" :min="0"
          controls-position="right" style="width: 100%" /></el-form-item>
        <el-form-item label="公里"><el-input-number v-model="cxForm.gongli" :precision="0" :min="0"
          controls-position="right" style="width: 100%" /></el-form-item>
        <el-form-item label="地点" class="full"><el-input v-model="cxForm.dizhi" /></el-form-item>
        <el-form-item label="描述" class="full"><el-input v-model="cxForm.miaoshu" type="textarea" :rows="3" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="cxDialog = false">取消</el-button>
        <el-button type="primary" @click="submitCx">确定</el-button>
      </template>
    </el-dialog>

    <!-- 车辆图片 -->
    <el-dialog v-model="imageDialog" :title="`车辆图片 - ${imageCar?.chehao || ''}`" width="760px">
      <label v-if="canManage" class="upload-btn">
        选择图片上传
        <input type="file" accept=".jpg,.jpeg,.png,.gif,.bmp,.webp" multiple
          style="display: none" @change="onImagePick" />
      </label>
      <div class="img-grid">
        <div v-for="img in imageList" :key="img.id" class="img-item">
          <img v-if="img.src && !img.error" :src="img.src" @error="img.error = true" />
          <div v-else class="img-missing">历史图片文件缺失<br /><small>需从旧系统服务器拷贝 Upload 目录</small></div>
          <el-button v-if="canManage" link type="danger" size="small" @click="removeImage(img)">删除</el-button>
        </div>
      </div>
      <div v-if="!imageList.length" class="tip">暂无图片</div>
    </el-dialog>

    <!-- 出险图片 -->
    <el-dialog v-model="cxImageDialog" title="出险图片" width="700px">
      <label v-if="canManage" class="upload-btn">
        选择图片上传
        <input type="file" accept=".jpg,.jpeg,.png,.gif,.bmp,.webp" multiple
          style="display: none" @change="onCxImagePick" />
      </label>
      <div class="img-grid">
        <div v-for="img in cxImageList" :key="img.id" class="img-item">
          <img v-if="img.src && !img.error" :src="img.src" @error="img.error = true" />
          <div v-else class="img-missing">图片文件缺失</div>
          <el-button v-if="canManage" link type="danger" size="small" @click="removeCxImage(img)">删除</el-button>
        </div>
      </div>
      <div v-if="!cxImageList.length" class="tip">暂无图片</div>
    </el-dialog>

    <!-- 加油月度统计 -->
    <el-dialog v-model="oilDialog" :title="`车辆加油统计 - ${oilCar?.chehao || ''}`" width="720px">
      <div class="oil-head">
        <el-select v-model="oilYear" style="width: 110px" @change="reloadOil">
          <el-option v-for="y in dicts.years" :key="y" :label="`${y}年`" :value="y" />
        </el-select>
        <el-button size="small" @click="reloadOil">查询</el-button>
      </div>
      <el-table :data="oilData?.months || []" size="small" border>
        <el-table-column prop="month" label="月份" width="80">
          <template #default="{ row }">{{ row.month }}月</template>
        </el-table-column>
        <el-table-column prop="jine" label="加油金额(元)" width="130">
          <template #default="{ row }">{{ money(row.jine) }}</template>
        </el-table-column>
        <el-table-column prop="oill" label="加油升数(L)" width="130">
          <template #default="{ row }">{{ money(row.oill) }}</template>
        </el-table-column>
        <el-table-column prop="useCount" label="派车次数(次)" width="120" />
        <el-table-column label="油品明细">
          <template #default="{ row }">
            <span v-for="d in row.details" :key="d.lei" class="oil-tag">
              {{ d.lei }} {{ money(d.oill) }}L
            </span>
          </template>
        </el-table-column>
      </el-table>
      <div class="oil-total">
        合计金额 {{ money(oilData?.total_jine) }} 元 ·
        合计升数 {{ money(oilData?.total_oill) }} L ·
        总派车次数 {{ oilData?.total_use_count || 0 }} 次
      </div>
    </el-dialog>

    <!-- 显示列设置 -->
    <el-dialog v-model="colDialog" title="显示列设置" width="min(880px, 94vw)" top="12vh" class="col-dialog">
      <div class="col-actions">
        <div class="col-actions-btns">
          <el-button size="small" @click="colDraft = defaultCols()">全选</el-button>
          <el-button size="small" @click="colDraft = []">全不选</el-button>
        </div>
        <span>已选 {{ colDraft.length }} / {{ ALL_COLUMNS.length }}</span>
      </div>
      <el-checkbox-group v-model="colDraft" class="col-group">
        <el-checkbox v-for="c in ALL_COLUMNS" :key="c.prop" :value="c.prop">{{ c.label }}</el-checkbox>
      </el-checkbox-group>
      <template #footer>
        <el-button @click="colDialog = false">取消</el-button>
        <el-button type="primary" @click="applyCols">确定</el-button>
      </template>
    </el-dialog>

    <!-- 年检说明 -->
    <el-dialog v-model="docDialog" title="车辆年检提醒功能说明" width="680px">
      <div class="doc">
        <p><b>年检周期</b>：货车车龄 &lt; 10 年每年一检、≥ 10 年每半年一检；摩托车 ≤ 4 年每 2 年一检、&gt; 4 年每年一检；其他车辆 &lt; 10 年每 2 年一检、≥ 10 年每年一检。以「注册日期」为基准逐年推算。</p>
        <p><b>提醒级别</b>：0 未提醒（&gt; 90 天）、1 90 天提醒、2 30 天提醒、3 7 天紧急提醒、4 已过期。列表「年检剩余天数」按到期日实时计算并用进度条展示。</p>
        <p><b>标注年检</b>：登记完成后点「标记」，系统记录本次年检日期并自动推算下一次年检日；点「撤销」回退状态。支持工具栏批量标记。</p>
        <p><b>登记信息变更</b>：修改注册日期或车辆类型后，系统立即重算下次年检日；修改资料后审批状态回到「待审批」。</p>
        <p><b>与旧系统差异</b>：旧系统的定时短信提醒依赖短信网关，新系统暂未接入，界面不提供短信发送；年检倒计时与级别按到期日实时展示，不再依赖每日定时任务落库。</p>
      </div>
    </el-dialog>
  </div>
</template>

<style scoped>
.vehicle-page { display: flex; flex-direction: column; gap: 10px; }
.filter-card :deep(.el-card__body) { padding: 10px 14px; }
.filter-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 12px; }
/* 开关内文字(inline-prompt)用深灰轨道保证白字对比度 */
.filter-form :deep(.el-switch) {
  --el-switch-on-color: #409eff;
  --el-switch-off-color: #7d8590;
}
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }
/* 展开内容固定在左侧:主表横向滚动时不会被带到屏幕外 */
.sub-wrap { padding: 8px 12px 12px 46px; position: sticky; left: 0;
  width: min(1180px, calc(100vw - 280px)); overflow-x: auto; box-sizing: border-box; }
.sub-title { font-weight: 600; margin-bottom: 6px; display: flex; align-items: center; gap: 10px; }
.sub-empty { color: #909399; font-weight: 400; font-size: 12px; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 14px; }
.form-grid .full { grid-column: 1 / -1; }
.form-grid :deep(.el-form-item) { margin-bottom: 12px; }
.inspect-cell { display: flex; align-items: center; gap: 4px; }
.remind-cell { display: flex; align-items: center; gap: 6px; font-size: 12px; white-space: nowrap; }
.remind-cell :deep(.el-progress) { flex: 1; min-width: 60px; }
.link-like { color: #409eff; cursor: default; border-bottom: 1px dashed #409eff; }
.pop-title { font-weight: 600; margin-bottom: 6px; }
.pop-row { display: flex; justify-content: space-between; font-size: 12px; padding: 2px 0; }
.pop-empty { color: #909399; font-size: 12px; }
.upload-btn { display: inline-flex; align-items: center; padding: 6px 12px; margin-bottom: 10px;
  border: 1px solid #dcdfe6; border-radius: 4px; cursor: pointer; font-size: 13px; background: #f5f7fa; }
.upload-btn:hover { border-color: #409eff; color: #409eff; }
.img-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.img-item { border: 1px solid #e4e7ed; border-radius: 4px; padding: 4px; text-align: center; }
.img-item img { width: 100%; height: 110px; object-fit: cover; display: block; }
.img-missing { height: 110px; display: flex; flex-direction: column; align-items: center;
  justify-content: center; color: #b3261e; font-size: 12px; background: #fafafa; }
.tip { color: #909399; font-size: 13px; padding: 8px 0; }
.oil-head { display: flex; gap: 8px; margin-bottom: 10px; }
.oil-tag { display: inline-block; margin-right: 8px; padding: 1px 6px; border-radius: 3px;
  background: #f0f2f5; font-size: 12px; }
.oil-total { margin-top: 8px; font-weight: 600; text-align: right; }
.col-dialog :deep(.el-dialog__body) { padding: 16px 24px 20px; }
.col-actions {
  display: flex; align-items: center; justify-content: space-between;
  padding-bottom: 12px; margin-bottom: 14px; border-bottom: 1px solid #ebeef5;
  font-size: 13px; color: #909399;
}
.col-actions-btns { display: flex; gap: 8px; }
.col-group { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px 18px; }
.col-group :deep(.el-checkbox) { margin-right: 0; height: 28px; }
.col-group :deep(.el-checkbox__label) { padding-left: 8px; font-size: 13px; white-space: nowrap; }
@media (max-width: 1000px) {
  .col-group { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 700px) {
  .col-group { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
.doc p { line-height: 1.8; font-size: 13px; margin: 6px 0; }
:deep(.row-110) { background-color: #fdf6e6 !important; }
:deep(.row-chaobiao) { background-color: #f0f6e8 !important; }
</style>
