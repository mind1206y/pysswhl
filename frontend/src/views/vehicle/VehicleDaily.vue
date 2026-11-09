<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  bulkDeleteDaily, cleanDailyAbnormal, createDaily, createDailyImageToken,
  deleteDailyImage, exportDaily, exportDailyGap, exportDailyOverlap, getDaily,
  getDailyCarInfo, getDailyDicts, importDaily, listDaily, listDailyAbnormal,
  updateDaily, uploadDailyImages, extractYearMileage,
} from '@/api/vehicleDaily'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canOperate = computed(() => auth.hasPerm('vehicle:view'))
const canManage = computed(() => auth.hasPerm('vehicle:manage'))

function pad(n) { return String(n).padStart(2, '0') }
function dateStr(d) { return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` }
const today = dateStr(new Date())
const yearStart = `${new Date().getFullYear()}-01-01`

// ===== 字典 =====
const dicts = reactive({
  departments: [], cars: [], drivers: [], shiyou: [], years: [], current_year: new Date().getFullYear(),
})

// ===== 筛选与列表 =====
const filters = reactive({
  keyword: '', deptId: null, carId: null, driver: '', dateFrom: yearStart, dateTo: today,
})
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)

function buildParams() {
  const p = {
    page: page.value, size: size.value,
    date_from: filters.dateFrom || undefined,
    date_to: filters.dateTo || undefined,
  }
  if (filters.keyword) p.keyword = filters.keyword
  if (filters.deptId) p.dept_id = filters.deptId
  if (filters.carId) p.car_id = filters.carId
  if (filters.driver) p.driver = filters.driver
  return p
}
async function load() {
  loading.value = true
  try {
    const data = await listDaily(buildParams())
    rows.value = data.items
    total.value = data.total
  } finally { loading.value = false }
}
function search() { page.value = 1; load() }
function resetFilters() {
  Object.assign(filters, {
    keyword: '', deptId: null, carId: null, driver: '', dateFrom: yearStart, dateTo: today,
  })
  search()
}
function fmt(v, len = 16) { return v ? String(v).slice(0, len) : '' }
function rowClass({ row }) {
  if (row.shenQingTime && row.jsdate && row.shenQingTime > row.jsdate) return 'row-warn'
  return ''
}

const selection = ref([])
function onSelectionChange(v) { selection.value = v }
function requireOne() {
  if (selection.value.length !== 1) { ElMessage.warning('请选中且仅选中一条记录'); return null }
  return selection.value[0]
}

onMounted(async () => {
  const d = await getDailyDicts()
  Object.assign(dicts, d)
  load()
})

// ===== 新增 / 编辑 =====
const dialog = ref(false)
const editingId = ref(null)
const tab = ref('basic')
const formRef = ref()
const blankForm = () => ({
  cheid: null, ksdate: '', jsdate: '', ksgl: null, jsgl: null, didian: '',
  yuanyin: '', usercar: auth.user?.real_name || auth.user?.username || '',
  tingfang: '', shenhe: '', shenpi: '', sj: '',
})
const form = reactive(blankForm())
const rules = {
  cheid: [{ required: true, message: '请选择车号', trigger: 'change' }],
  ksdate: [{ required: true, message: '请选择开始时间', trigger: 'change' }],
  didian: [{ required: true, message: '请输入目的地', trigger: 'blur' }],
  yuanyin: [{ required: true, message: '请选择/输入事由', trigger: 'change' }],
  usercar: [{ required: true, message: '请输入用车人', trigger: 'blur' }],
}
const carInfo = reactive({ gls: 0, tingfang: '', shenhe: '', shenpi: '' })
const existingImages = ref([])
const pendingImages = ref([])

function dlgDateTime(v) { return v ? String(v).slice(0, 19) : '' }

async function openCreate() {
  editingId.value = null
  Object.assign(form, blankForm())
  carInfo.gls = 0; carInfo.tingfang = ''
  existingImages.value = []
  clearPending()
  tab.value = 'basic'
  dialog.value = true
}

async function openEdit(row) {
  if (!canOperate.value) return
  if (row.shenheqz !== '待审核' || row.bumenld !== '待审批') {
    ElMessage.warning('该记录已审核，无法编辑')
    return
  }
  if (!auth.user?.is_superuser && row.czy !== auth.user?.username) {
    ElMessage.warning('不能编辑非自己录入的信息')
    return
  }
  editingId.value = row.id
  Object.assign(form, blankForm())
  for (const k of Object.keys(form)) {
    if (row[k] !== undefined && row[k] !== null) form[k] = row[k]
  }
  form.ksdate = dlgDateTime(row.ksdate)
  form.jsdate = dlgDateTime(row.jsdate)
  carInfo.gls = row.ksgl ?? 0
  carInfo.tingfang = row.tingfang || ''
  existingImages.value = []
  clearPending()
  tab.value = 'basic'
  dialog.value = true
  loadCarInfo(row.cheid, false)
  loadExistingImages(row.id)
}

async function loadCarInfo(carId, fillMileage) {
  if (!carId) return
  try {
    const info = await getDailyCarInfo(carId)
    Object.assign(carInfo, info)
    if (fillMileage) form.ksgl = info.gls || null
    if (!form.shenhe) form.shenhe = info.shenhe || ''
    if (fillMileage && !form.tingfang) form.tingfang = info.tingfang || ''
  } catch { /* 已提示 */ }
}
function onCarChange(carId) { loadCarInfo(carId, true) }

function clearPending() {
  for (const p of pendingImages.value) URL.revokeObjectURL(p.url)
  pendingImages.value = []
}
function onPickImages(e) {
  const files = [...e.target.files]
  for (const f of files) pendingImages.value.push({ file: f, url: URL.createObjectURL(f), name: f.name })
  e.target.value = ''
}
function removePending(index) {
  URL.revokeObjectURL(pendingImages.value[index].url)
  pendingImages.value.splice(index, 1)
}
async function loadExistingImages(id) {
  const detail = await getDaily(id)
  existingImages.value = await resolveImages(detail.images || [])
}
async function resolveImages(list) {
  const out = []
  for (const img of list) {
    let src = ''
    try { src = (await createDailyImageToken(img.id)).url } catch { /* 忽略 */ }
    out.push({ ...img, src, error: false })
  }
  return out
}
async function removeExistingImage(img) {
  await ElMessageBox.confirm('确定删除这张图片？', '提示', { type: 'warning' })
  await deleteDailyImage(img.id)
  existingImages.value = existingImages.value.filter((i) => i.id !== img.id)
  ElMessage.success('已删除')
}

function buildPayload() {
  const p = { ...form }
  if (!p.jsdate) p.jsdate = null
  if (p.ksgl === '' || p.ksgl === undefined) p.ksgl = null
  if (p.jsgl === '' || p.jsgl === undefined) p.jsgl = null
  delete p.shenQingTime
  return p
}
async function submit() {
  await formRef.value.validate()
  const payload = buildPayload()
  const isNew = !editingId.value
  let id = editingId.value
  if (id) {
    await updateDaily(id, payload)
  } else {
    const res = await createDaily(payload)
    id = res.id
    editingId.value = id
  }
  if (pendingImages.value.length) {
    const fd = new FormData()
    for (const p of pendingImages.value) fd.append('files', p.file)
    await uploadDailyImages(id, fd)
    clearPending()
  }
  ElMessage.success(isNew ? '添加成功' : '保存成功')
  dialog.value = false
  load()
}

// ===== 删除 =====
async function doDelete() {
  if (!selection.value.length) { ElMessage.warning('请选择要删除的记录'); return }
  await ElMessageBox.confirm(`确定删除选中的 ${selection.value.length} 条记录？`, '提示', { type: 'warning' })
  await bulkDeleteDaily(selection.value.map((r) => r.id))
  ElMessage.success('删除成功')
  load()
}

// ===== 导出 / 导入 =====
async function doExport() { await exportDaily(buildParams()); ElMessage.success('已导出') }
async function doOverlap() { await exportDailyOverlap(buildParams()); ElMessage.success('已导出重叠里程') }
async function doGap() { await exportDailyGap(buildParams()); ElMessage.success('已导出空挡里程') }
async function doExtractMileage() {
  const year = Number((filters.dateFrom || '').slice(0, 4)) || dicts.current_year
  await ElMessageBox.confirm(`确定提取 ${year} 年整年公里数到加油统计？`, '提示', { type: 'warning' })
  const res = await extractYearMileage(year)
  ElMessage.success(`提取完成，新增 ${res.created || 0} 条`)
}

const uploadInput = ref()
const importing = ref(false)
const importResult = ref(null)
const importDialog = ref(false)
function chooseUpload() { uploadInput.value.click() }
async function onUploadChange(e) {
  const file = e.target.files?.[0]
  e.target.value = ''
  if (!file) return
  const fd = new FormData()
  fd.append('file', file)
  importing.value = true
  try {
    importResult.value = await importDaily(fd)
    importDialog.value = true
    load()
  } finally { importing.value = false }
}

// ===== 异常里程 =====
const abnormalDialog = ref(false)
const abnormalLoading = ref(false)
const abnormalRows = ref([])
const abnormalTotal = ref(0)
const abnormalPage = ref(1)
const abnormalSize = ref(20)
const abnormalSelection = ref([])
async function loadAbnormal() {
  abnormalLoading.value = true
  try {
    const data = await listDailyAbnormal({ page: abnormalPage.value, size: abnormalSize.value })
    abnormalRows.value = data.items
    abnormalTotal.value = data.total
  } finally { abnormalLoading.value = false }
}
function openAbnormal() {
  abnormalPage.value = 1
  abnormalDialog.value = true
  loadAbnormal()
}
function onAbnormalSelection(v) { abnormalSelection.value = v }
async function deleteAbnormalSelected() {
  if (!abnormalSelection.value.length) { ElMessage.warning('请选择要删除的记录'); return }
  await ElMessageBox.confirm(`确定删除选中的 ${abnormalSelection.value.length} 条异常记录？`, '提示', { type: 'warning' })
  await bulkDeleteDaily(abnormalSelection.value.map((r) => r.id))
  ElMessage.success('已删除')
  loadAbnormal(); load()
}
async function cleanAllAbnormal() {
  await ElMessageBox.confirm('将执行【物理删除】并同步删除附件，是否继续？', '清理全部异常', { type: 'warning' })
  const res = await cleanDailyAbnormal()
  ElMessage.success(`清理完成，共删除 ${res.count || 0} 条记录`)
  loadAbnormal(); load()
}

// ===== 图片查看 =====
const imageDialog = ref(false)
const imageCar = ref(null)
const imageList = ref([])
async function openImages(row) {
  imageCar.value = row
  imageList.value = await resolveImages(row.tps || [])
  imageDialog.value = true
}
</script>

<template>
  <div class="daily-page">
    <el-card shadow="never" class="filter-card">
      <div class="filter-title">日常用车登记表</div>
      <el-form inline class="filter-form">
        <el-form-item label="关键字">
          <el-input v-model="filters.keyword" placeholder="车号/地点/司机/事由" clearable
            style="width: 200px" @keyup.enter="search" />
        </el-form-item>
        <el-form-item label="用车日期">
          <el-date-picker v-model="filters.dateFrom" type="date" value-format="YYYY-MM-DD"
            placeholder="开始日期" style="width: 140px" />
          <span class="sep">至</span>
          <el-date-picker v-model="filters.dateTo" type="date" value-format="YYYY-MM-DD"
            placeholder="结束日期" style="width: 140px" />
        </el-form-item>
        <el-form-item label="部门">
          <el-select v-model="filters.deptId" placeholder="选择部门" clearable filterable style="width: 150px">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="车号">
          <el-select v-model="filters.carId" placeholder="选择车号" clearable filterable style="width: 140px">
            <el-option v-for="c in dicts.cars" :key="c.id" :label="c.chehao" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="司机">
          <el-select v-model="filters.driver" placeholder="选择司机" clearable filterable style="width: 170px">
            <el-option v-for="d in dicts.drivers" :key="d.name" :label="`${d.name}（${d.count}次）`" :value="d.name" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <div class="toolbar">
      <template v-if="canOperate">
        <el-button type="primary" size="small" @click="openCreate">添加</el-button>
        <el-button size="small" @click="() => { const r = requireOne(); if (r) openEdit(r) }">编辑</el-button>
      </template>
      <el-button v-if="canManage" size="small" type="danger" plain @click="doDelete">删除</el-button>
      <el-button size="small" @click="doExport">导出EXCEL</el-button>
      <template v-if="canManage">
        <el-button size="small" :loading="importing" @click="chooseUpload">上传派车记录</el-button>
        <input ref="uploadInput" type="file" accept=".xls,.xlsx" style="display: none" @change="onUploadChange" />
        <el-button size="small" @click="doOverlap">导出重叠里程</el-button>
        <el-button size="small" @click="doGap">导出空挡里程</el-button>
        <el-button size="small" type="warning" plain @click="openAbnormal">查找异常数据</el-button>
        <el-button size="small" @click="doExtractMileage">提取整年公里数</el-button>
      </template>
      <el-button size="small" @click="load">刷新</el-button>
      <span class="toolbar-hint">共 {{ total }} 条记录 · 双击行可编辑</span>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe size="small"
      height="calc(100vh - 300px)" row-key="id" :row-class-name="rowClass"
      @selection-change="onSelectionChange" @row-dblclick="openEdit">
      <el-table-column type="selection" width="42" fixed="left" />
      <el-table-column prop="id" label="编号" width="66" fixed="left" />
      <el-table-column prop="sj" label="司机" width="86" />
      <el-table-column prop="chehao" label="车号" width="100" fixed="left" />
      <el-table-column prop="lx" label="类型" width="120" />
      <el-table-column label="申请日期" width="100">
        <template #default="{ row }">{{ fmt(row.shenQingTime, 10) }}</template>
      </el-table-column>
      <el-table-column label="用车开始时间" width="138">
        <template #default="{ row }">{{ fmt(row.ksdate) }}</template>
      </el-table-column>
      <el-table-column label="用车结束时间" width="138">
        <template #default="{ row }">{{ fmt(row.jsdate) }}</template>
      </el-table-column>
      <el-table-column prop="ksgl" label="开始公里" width="92" />
      <el-table-column prop="jsgl" label="结束公里" width="92" />
      <el-table-column prop="gl" label="里程数" width="80" />
      <el-table-column prop="didian" label="用车地点" min-width="180" show-overflow-tooltip />
      <el-table-column prop="yuanyin" label="用车事由" min-width="180" show-overflow-tooltip />
      <el-table-column prop="usercar" label="用车人" width="100" />
      <el-table-column prop="bumen" label="车辆部门" width="110" />
      <el-table-column prop="czy" label="登记人" width="90" />
      <el-table-column label="状态" width="160">
        <template #default="{ row }">
          <el-tag size="small" :type="row.beizhu === '预登记' ? 'warning' : 'primary'">{{ row.beizhu || '-' }}</el-tag>
          <el-tag size="small" type="info" class="ml4">{{ row.shenheqz || '-' }}</el-tag>
          <el-tag size="small" type="info" class="ml4">{{ row.bumenld || '-' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="图片" width="74">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openImages(row)">
            {{ row.tps?.length || 0 }} 张
          </el-button>
        </template>
      </el-table-column>
      <el-table-column label="最后编辑日期" width="140">
        <template #default="{ row }">{{ fmt(row.cz) }}</template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[20, 60, 100]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>

    <!-- 添加 / 编辑 -->
    <el-dialog v-model="dialog" :title="editingId ? '编辑用车明细数据' : '添加用车登记'" width="760px"
      top="5vh" :close-on-click-modal="false" @closed="clearPending">
      <el-tabs v-model="tab">
        <el-tab-pane label="用车登记" name="basic">
          <el-form ref="formRef" :model="form" :rules="rules" label-width="105px" class="form-grid">
            <el-form-item label="车号" prop="cheid">
              <el-select v-model="form.cheid" filterable placeholder="请选择车号" style="width: 100%"
                @change="onCarChange">
                <el-option v-for="c in dicts.cars" :key="c.id" :label="`${c.chehao}${c.bumen ? ' · ' + c.bumen : ''}`"
                  :value="c.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="最新公里/停放">
              <span class="info-text">{{ carInfo.gls || 0 }} 公里<span class="ml8">停放在：{{ carInfo.tingfang || '-' }}</span></span>
            </el-form-item>
            <el-form-item label="用车开始时间" prop="ksdate">
              <el-date-picker v-model="form.ksdate" type="datetime" value-format="YYYY-MM-DD HH:mm:ss"
                placeholder="开始日期时间" style="width: 100%" />
            </el-form-item>
            <el-form-item label="用车结束时间">
              <el-date-picker v-model="form.jsdate" type="datetime" value-format="YYYY-MM-DD HH:mm:ss"
                placeholder="结束日期时间（预登记可空）" clearable style="width: 100%" />
            </el-form-item>
            <el-form-item label="开始公里数">
              <el-input-number v-model="form.ksgl" :precision="0" :min="0" controls-position="right"
                style="width: 100%" />
            </el-form-item>
            <el-form-item label="结束公里数">
              <el-input-number v-model="form.jsgl" :precision="0" :min="0" controls-position="right"
                style="width: 100%" />
            </el-form-item>
            <el-form-item label="目的地" prop="didian">
              <el-input v-model="form.didian" />
            </el-form-item>
            <el-form-item label="事由" prop="yuanyin">
              <el-select v-model="form.yuanyin" filterable allow-create default-first-option
                placeholder="选择或输入事由" style="width: 100%">
                <el-option v-for="s in dicts.shiyou" :key="s" :label="s" :value="s" />
              </el-select>
            </el-form-item>
            <el-form-item label="用车人" prop="usercar">
              <el-input v-model="form.usercar" />
            </el-form-item>
            <el-form-item label="司机">
              <el-select v-model="form.sj" filterable allow-create clearable default-first-option
                placeholder="选择或输入司机" style="width: 100%">
                <el-option v-for="d in dicts.drivers" :key="d.name" :label="d.name" :value="d.name" />
              </el-select>
            </el-form-item>
            <el-form-item label="回场停放点">
              <el-input v-model="form.tingfang" placeholder="下次使用便于找车，可不填" />
            </el-form-item>
            <el-form-item label="审核人">
              <el-input v-model="form.shenhe" placeholder="默认取车辆审核人" />
            </el-form-item>
            <el-form-item label="部门领导审批">
              <el-input v-model="form.shenpi" placeholder="审批人姓名" />
            </el-form-item>
            <div class="full hint">
              结束时间不填、结束时间为 00:00 或结束公里为空时，记录保存为「预登记」；否则保存为「已提交」并进入待审核/待审批。
            </div>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="图片" name="images">
          <div v-if="!editingId" class="tip">保存用车记录后即可上传图片；也可以先选择图片，保存时一并上传。</div>
          <label class="upload-btn">
            选择图片上传
            <input type="file" accept=".jpg,.jpeg,.png,.gif,.bmp,.webp" multiple
              style="display: none" @change="onPickImages" />
          </label>
          <div class="img-grid">
            <div v-for="img in existingImages" :key="'e' + img.id" class="img-item">
              <img v-if="img.src && !img.error" :src="img.src" @error="img.error = true" />
              <div v-else class="img-missing">图片文件缺失</div>
              <el-button link type="danger" size="small" @click="removeExistingImage(img)">删除</el-button>
            </div>
            <div v-for="(p, i) in pendingImages" :key="'p' + i" class="img-item">
              <img :src="p.url" />
              <el-button link type="danger" size="small" @click="removePending(i)">移除</el-button>
            </div>
            <div v-if="!existingImages.length && !pendingImages.length" class="tip">暂无图片</div>
          </div>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="submit">{{ editingId ? '确定修改' : '确定增加' }}</el-button>
      </template>
    </el-dialog>

    <!-- 导入结果 -->
    <el-dialog v-model="importDialog" title="派车记录上传结果" width="720px">
      <div v-if="importResult" class="import-summary">
        共 {{ importResult.total }} 条，成功 {{ importResult.success }} 条，失败 {{ importResult.failed }} 条
      </div>
      <el-table v-if="importResult?.errors?.length" :data="importResult.errors" border size="small" max-height="360">
        <el-table-column prop="row" label="Excel行号" width="100" />
        <el-table-column prop="reason" label="失败原因" />
      </el-table>
      <div v-if="importResult?.errors_truncated" class="tip">失败明细较多，仅显示前 500 条。</div>
      <template #footer>
        <el-button type="primary" @click="importDialog = false">知道了</el-button>
      </template>
    </el-dialog>

    <!-- 异常里程 -->
    <el-dialog v-model="abnormalDialog" title="异常里程数据" width="1080px" top="8vh">
      <div class="abnormal-toolbar">
        <el-button size="small" type="danger" plain @click="deleteAbnormalSelected">删除选中</el-button>
        <el-button size="small" type="warning" plain @click="cleanAllAbnormal">清理全部异常</el-button>
        <span class="toolbar-hint">共 {{ abnormalTotal }} 条异常</span>
      </div>
      <el-table v-loading="abnormalLoading" :data="abnormalRows" border size="small" max-height="480"
        @selection-change="onAbnormalSelection">
        <el-table-column type="selection" width="42" />
        <el-table-column prop="id" label="编号" width="70" />
        <el-table-column prop="chehao" label="车号" width="100" />
        <el-table-column prop="sj" label="司机" width="90" />
        <el-table-column prop="ksdate" label="开始时间" width="145" />
        <el-table-column prop="jsdate" label="结束时间" width="145" />
        <el-table-column prop="ksgl" label="开始公里" width="90" />
        <el-table-column prop="jsgl" label="结束公里" width="90" />
        <el-table-column prop="gl" label="里程" width="80" />
        <el-table-column prop="AbnormalReason" label="异常原因" min-width="260" show-overflow-tooltip />
      </el-table>
      <div class="pager">
        <el-pagination v-model:current-page="abnormalPage" v-model:page-size="abnormalSize"
          :total="abnormalTotal" layout="total, prev, pager, next" @current-change="loadAbnormal" />
      </div>
    </el-dialog>

    <!-- 图片查看 -->
    <el-dialog v-model="imageDialog" :title="`用车图片 - ${imageCar?.chehao || ''}`" width="760px">
      <div class="img-grid">
        <div v-for="img in imageList" :key="img.id" class="img-item">
          <img v-if="img.src && !img.error" :src="img.src" @error="img.error = true" />
          <div v-else class="img-missing">图片文件缺失</div>
        </div>
      </div>
      <div v-if="!imageList.length" class="tip">暂无图片</div>
    </el-dialog>
  </div>
</template>

<style scoped>
.daily-page { display: flex; flex-direction: column; gap: 10px; }
.filter-card :deep(.el-card__body) { padding: 10px 14px; }
.filter-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 12px; }
.sep { margin: 0 6px; color: #909399; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 2px 14px; }
.form-grid .full { grid-column: 1 / -1; }
.form-grid :deep(.el-form-item) { margin-bottom: 12px; }
.hint { color: #909399; font-size: 12px; line-height: 1.6; padding: 2px 0 4px 105px; }
.info-text { color: #606266; font-size: 13px; }
.ml4 { margin-left: 4px; }
.ml8 { margin-left: 8px; }
.upload-btn { display: inline-flex; align-items: center; padding: 6px 12px; margin-bottom: 10px;
  border: 1px solid #dcdfe6; border-radius: 4px; cursor: pointer; font-size: 13px; background: #f5f7fa; }
.upload-btn:hover { border-color: #409eff; color: #409eff; }
.img-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; }
.img-item { border: 1px solid #e4e7ed; border-radius: 4px; padding: 4px; text-align: center; }
.img-item img { width: 100%; height: 120px; object-fit: cover; display: block; }
.img-missing { height: 120px; display: flex; align-items: center; justify-content: center;
  color: #b3261e; font-size: 12px; background: #fafafa; }
.tip { color: #909399; font-size: 13px; padding: 8px 0; }
.import-summary { font-size: 14px; font-weight: 600; margin-bottom: 12px; }
.abnormal-toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
:deep(.row-warn) { background-color: #fff8dc !important; }
</style>
