<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  batchUpdateProgress, createRepair, deleteAttachment, deleteRepair, deletePrice,
  downloadAttachment, exportRepairs, getRepairById, getRepairDicts, listAttachments,
  listPrices, listProgress, listRepairs, getPriceOptions, updateProgress,
  updateRepair, uploadAttachment,
} from '@/api/roadrepair'

// ==================== 字典 ====================
const dicts = reactive({
  companies: [],
  progress_options: [],
  progress_colors: {},
  banzu: [],
})

const PROGRESS_COLORS = {
  已报账: '#2563eb',
  已付款: '#2e7d32',
  已完账: '#b45309',
  新建: '#6b7280',
}

// ==================== 列表 ====================
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const filters = reactive({ keyword: '', progress: '', company: '', start: '', end: '' })
const selectedRows = ref([])

function buildParams(withPage = true) {
  const p = {}
  if (withPage) { p.page = page.value; p.size = size.value }
  if (filters.keyword) p.keyword = filters.keyword
  if (filters.progress) p.progress = filters.progress
  if (filters.company) p.company = filters.company
  if (filters.start) p.start = filters.start
  if (filters.end) p.end = filters.end
  return p
}

async function load() {
  loading.value = true
  try {
    const data = await listRepairs(buildParams())
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

function resetFilters() {
  Object.assign(filters, { keyword: '', progress: '', company: '', start: '', end: '' })
  search()
}

function onSelectionChange(val) {
  selectedRows.value = val
}

function fmtMoney(v) {
  return v == null ? '0.00' : Number(v).toFixed(2)
}

async function doExport() {
  await exportRepairs(buildParams(false))
  ElMessage.success('已导出 Excel')
}

// ==================== 详情卡片 ====================
const currentRow = ref(null)
const progressList = ref([])
const detailLoading = ref(false)

async function loadDetail(row) {
  detailLoading.value = true
  try {
    // 列表行本身就是全量字段(后端 to_dict),进度历史单独拉取
    currentRow.value = row
    progressList.value = await listProgress(row.id)
  } finally {
    detailLoading.value = false
  }
}

function resetDetail() {
  currentRow.value = null
  progressList.value = []
}

async function onRowClick(row) {
  await loadDetail(row)
}

async function reloadAfterChange(id) {
  await load()
  if (id) {
    try {
      await loadDetail(await getRepairById(id))
    } catch {
      resetDetail()
    }
  }
}

async function setProgress(progress) {
  if (!currentRow.value) {
    ElMessage.warning('请先在表格中选择一条记录')
    return
  }
  try {
    await ElMessageBox.confirm(`确定要将状态更新为 “${progress}” 吗？`, '确认', { type: 'info' })
  } catch {
    return
  }
  await updateProgress(currentRow.value.id, progress)
  ElMessage.success(`状态已更新为 ${progress}`)
  await reloadAfterChange(currentRow.value.id)
}

async function doDelete(row) {
  try {
    await ElMessageBox.confirm('删除后无法恢复，确定删除？', '⚠️ 确认删除', { type: 'warning' })
  } catch {
    return
  }
  await deleteRepair(row.id)
  ElMessage.success('记录已移除')
  resetDetail()
  load()
}

// ==================== 新增 / 编辑弹窗 ====================
const dlgVisible = ref(false)
const editingId = ref(null)
const saving = ref(false)
const formRef = ref()
const form = reactive({
  address: '', company: '', banzu: '', dig_date: '', roadTypePriceId: null,
  road_type: '', area: null, final_area: null, price: null, total: null,
  reason: '', remark: '',
})
const formRules = {
  address: [{ required: true, message: '请填写地址', trigger: 'blur' }],
}

// 道路类型选项(随单位级联,公路局只取专属价,其它单位含通用价)
const roadTypeOptions = ref([])

async function refreshRoadTypeOptions(company) {
  roadTypeOptions.value = await getPriceOptions(company || '')
}

function onCompanyChange() {
  form.roadTypePriceId = null
  form.road_type = ''
  form.price = null
  form.total = null
  refreshRoadTypeOptions(form.company)
}

function onRoadTypeSelect(id) {
  const opt = roadTypeOptions.value.find((o) => o.id === id)
  if (opt) {
    form.road_type = opt.road_type
    form.price = opt.price
    calcTotal()
  }
}

function calcTotal() {
  const area = Number(form.final_area) || 0
  const price = Number(form.price) || 0
  form.total = area && price ? Number((area * price).toFixed(2)) : null
}

function openAdd() {
  editingId.value = null
  Object.assign(form, {
    address: '', company: '', banzu: '', dig_date: '', roadTypePriceId: null,
    road_type: '', area: null, final_area: null, price: null, total: null,
    reason: '', remark: '',
  })
  roadTypeOptions.value = []
  dlgVisible.value = true
}

async function openEdit(row) {
  const detail = row.address != null ? row : await getRepairById(row.id)
  editingId.value = detail.id
  Object.assign(form, {
    address: detail.address || '',
    company: detail.company || '',
    banzu: detail.banzu || '',
    dig_date: detail.dig_date || '',
    roadTypePriceId: null,
    road_type: detail.road_type || '',
    area: detail.area,
    final_area: detail.final_area,
    price: detail.price,
    total: detail.total,
    reason: detail.reason || '',
    remark: detail.remark || '',
  })
  await refreshRoadTypeOptions(form.company)
  // 照旧:按类型+单位匹配价格选项,回填单价并重算总额
  const matched = roadTypeOptions.value.find(
    (o) => o.road_type === detail.road_type
      && (o.company === (detail.company || '通用') || o.company === '通用'),
  )
  if (matched) {
    form.roadTypePriceId = matched.id
    form.price = matched.price
    calcTotal()
  }
  dlgVisible.value = true
}

async function submitForm() {
  await formRef.value.validate()
  if (saving.value) return
  saving.value = true
  try {
    const payload = {
      address: form.address,
      company: form.company || null,
      dig_date: form.dig_date || null,
      road_type: form.road_type || null,
      area: form.area,
      final_area: form.final_area,
      price: form.price,
      total: form.total,
      reason: form.reason || null,
      remark: form.remark || null,
      banzu: form.banzu || null,
    }
    if (editingId.value) {
      await updateRepair(editingId.value, payload)
      ElMessage.success('保存成功')
      dlgVisible.value = false
      await reloadAfterChange(editingId.value)
    } else {
      const res = await createRepair(payload)
      ElMessage.success('保存成功，可继续添加')
      // 照旧:连续新增,保持弹窗开启并清空表单
      const keepCompany = form.company
      Object.assign(form, {
        address: '', banzu: '', dig_date: '', roadTypePriceId: null, road_type: '',
        area: null, final_area: null, price: null, total: null, reason: '', remark: '',
      })
      form.company = keepCompany
      roadTypeOptions.value = await getPriceOptions(keepCompany || '')
      await load()
      resetDetail()
    }
  } finally {
    saving.value = false
  }
}

// ==================== 批量状态 ====================
const batchDlg = ref(false)
const batchProgress = ref('已报账')

function openBatch() {
  if (!selectedRows.value.length) {
    ElMessage.warning('请先勾选记录')
    return
  }
  batchDlg.value = true
}

async function submitBatch() {
  const ids = selectedRows.value.map((r) => r.id)
  try {
    await ElMessageBox.confirm(`确定更新 ${ids.length} 条记录？`, '确认', { type: 'info' })
  } catch {
    return
  }
  await batchUpdateProgress(ids, batchProgress.value)
  ElMessage.success('批量更新完成')
  batchDlg.value = false
  await load()
  if (currentRow.value) {
    await reloadAfterChange(currentRow.value.id)
  }
}

// ==================== 价格管理 ====================
const priceDlg = ref(false)
const priceRows = ref([])
const priceTotal = ref(0)
const pricePage = ref(1)
const priceSize = ref(20)
const priceKeyword = ref('')
const priceLoading = ref(false)

async function openPriceManager() {
  priceDlg.value = true
  priceKeyword.value = ''
  pricePage.value = 1
  await loadPrices()
}

async function loadPrices() {
  priceLoading.value = true
  try {
    const data = await listPrices({
      page: pricePage.value, size: priceSize.value,
      keyword: priceKeyword.value || undefined,
    })
    priceRows.value = data.items
    priceTotal.value = data.total
  } finally {
    priceLoading.value = false
  }
}

function searchPrices() {
  pricePage.value = 1
  loadPrices()
}

const priceEditDlg = ref(false)
const priceFormRef = ref()
const priceForm = reactive({ id: null, company: '', road_type: '', price: null })
const priceRules = {
  road_type: [{ required: true, message: '请填写路面类型', trigger: 'blur' }],
  price: [{ required: true, message: '请填写单价', trigger: 'blur' }],
}

function openPriceAdd() {
  Object.assign(priceForm, { id: null, company: '', road_type: '', price: null })
  priceEditDlg.value = true
}

function openPriceEdit(row) {
  Object.assign(priceForm, {
    id: row.id, company: row.company || '', road_type: row.road_type, price: row.price,
  })
  priceEditDlg.value = true
}

async function submitPrice() {
  await priceFormRef.value.validate()
  await savePrice({ ...priceForm, company: priceForm.company || null })
  ElMessage.success('保存成功')
  priceEditDlg.value = false
  loadPrices()
}

async function doDeletePrice(row) {
  try {
    await ElMessageBox.confirm('确定删除该价格吗？', '确认', { type: 'warning' })
  } catch {
    return
  }
  await deletePrice(row.id)
  ElMessage.success('已删除')
  loadPrices()
}

// ==================== 附件抽屉 ====================
const attDrawer = ref(false)
const attLoading = ref(false)
const attachments = ref([])
const currentRepairId = ref(0)
const fileRef = ref()

async function openDrawer(row) {
  currentRepairId.value = row.id
  attDrawer.value = true
  attLoading.value = true
  try {
    attachments.value = await listAttachments(row.id)
  } finally {
    attLoading.value = false
  }
}

function fmtSize(bytes) {
  if (!bytes) return '0 B'
  const k = 1024
  const sizes = ['B', 'KB', 'MB', 'GB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return `${parseFloat((bytes / k ** i).toFixed(2))} ${sizes[i]}`
}

async function doUpload() {
  const file = fileRef.value?.files?.[0]
  if (!file) {
    ElMessage.warning('请选择文件')
    return
  }
  try {
    await uploadAttachment(currentRepairId.value, file)
    ElMessage.success('上传成功')
    if (fileRef.value) fileRef.value.value = ''
    attachments.value = await listAttachments(currentRepairId.value)
    load()
  } catch {
    // request 拦截器已提示
  }
}

async function doDownload(att) {
  await downloadAttachment(att)
}

async function doDeleteAttachment(att) {
  try {
    await ElMessageBox.confirm('确定删除该附件吗？', '确认', { type: 'warning' })
  } catch {
    return
  }
  await deleteAttachment(att.id)
  ElMessage.success('已删除')
  attachments.value = await listAttachments(currentRepairId.value)
  load()
}

const progressTagColor = computed(() => (p) => PROGRESS_COLORS[p] || dicts.progress_colors[p] || '#6b7280')

onMounted(async () => {
  const d = await getRepairDicts()
  Object.assign(dicts, d)
  load()
})
</script>

<template>
  <div class="rr-page">
    <!-- 筛选工具栏 -->
    <el-card shadow="never" class="filter-card">
      <el-form inline class="filter-form">
        <el-form-item label="关键字">
          <el-input v-model="filters.keyword" clearable style="width: 200px"
            placeholder="地址 / 原因 / 备注" @keyup.enter="search" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.progress" clearable style="width: 120px" @change="search">
            <el-option v-for="p in ['已报账', '已付款', '已完账']" :key="p" :label="p" :value="p" />
          </el-select>
        </el-form-item>
        <el-form-item label="单位">
          <el-select v-model="filters.company" clearable style="width: 120px" @change="search">
            <el-option v-for="c in dicts.companies" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="开挖日期">
          <el-date-picker v-model="filters.start" type="date" value-format="YYYY-MM-DD"
            placeholder="从" style="width: 130px" @change="search" />
          <span class="date-sep">至</span>
          <el-date-picker v-model="filters.end" type="date" value-format="YYYY-MM-DD"
            placeholder="至" style="width: 130px" @change="search" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
      <div class="toolbar">
        <el-button type="primary" size="small" @click="openAdd">新增维修</el-button>
        <el-button type="warning" size="small" plain @click="openBatch">批量状态</el-button>
        <el-button size="small" @click="doExport">导出Excel</el-button>
        <el-button size="small" class="price-btn" @click="openPriceManager">价格管理</el-button>
        <span class="toolbar-hint">共 {{ total }} 条 · 点击行查看详情与进度</span>
      </div>
    </el-card>

    <!-- 左表格 + 右详情 -->
    <div class="main-layout">
      <div class="table-panel">
        <el-table v-loading="loading" :data="rows" border stripe size="small"
          height="100%" highlight-current-row @row-click="onRowClick"
          @selection-change="onSelectionChange">
          <el-table-column type="selection" width="40" />
          <el-table-column prop="dig_date" label="开挖日期" width="105" />
          <el-table-column prop="address" label="地址" min-width="200" show-overflow-tooltip />
          <el-table-column prop="company" label="单位" width="90" align="center" />
          <el-table-column label="总额(元)" width="100" align="right">
            <template #default="{ row }">{{ fmtMoney(row.total) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="90" align="center">
            <template #default="{ row }">
              <span class="progress-tag"
                :style="{ color: progressTagColor(row.current_progress) }">
                {{ row.current_progress || '待处理' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="附件" width="70" align="center">
            <template #default="{ row }">
              <el-badge :value="row.attachment_count || ''" :hidden="!row.attachment_count"
                class="att-badge">
                <el-button link type="primary" size="small" @click.stop="openDrawer(row)">
                  查看
                </el-button>
              </el-badge>
            </template>
          </el-table-column>
        </el-table>
        <div class="pager">
          <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
            :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" small
            @current-change="load" @size-change="search" />
        </div>
      </div>

      <div v-loading="detailLoading" class="card-panel">
        <template v-if="currentRow">
          <div class="detail-card">
            <h3>🛣️ {{ currentRow.address || '未命名路段' }}</h3>
            <div class="info-grid">
              <div class="info-col">
                <div class="info-row"><span class="info-label">🏷️ 地址</span>
                  <span>{{ currentRow.address || '—' }}</span></div>
                <div class="info-row"><span class="info-label">🏢 单位</span>
                  <span>{{ currentRow.company || '—' }}</span></div>
                <div class="info-row"><span class="info-label">📅 开挖日期</span>
                  <span>{{ currentRow.dig_date || '—' }}</span></div>
                <div class="info-row"><span class="info-label">🛤️ 道路类型</span>
                  <span>{{ currentRow.road_type || '—' }}</span></div>
                <div class="info-row"><span class="info-label">📐 面积(㎡)</span>
                  <span>{{ currentRow.area ?? 0 }}</span></div>
                <div class="info-row"><span class="info-label">📏 决算面积</span>
                  <span>{{ currentRow.final_area ?? 0 }}</span></div>
                <div class="info-row"><span class="info-label">📝 维修原因</span>
                  <span>{{ currentRow.reason || '无' }}</span></div>
              </div>
              <div class="info-col">
                <div class="info-row"><span class="info-label">💰 单价(元)</span>
                  <span>{{ currentRow.price ?? 0 }}</span></div>
                <div class="info-row"><span class="info-label">💵 总额</span>
                  <span class="highlight-total">¥ {{ fmtMoney(currentRow.total) }}</span></div>
                <div class="info-row"><span class="info-label">⚙️ 状态</span>
                  <span class="progress-tag"
                    :style="{ color: progressTagColor(currentRow.current_progress) }">
                    {{ currentRow.current_progress || '待处理' }}</span></div>
                <div class="info-row"><span class="info-label">👤 操作员</span>
                  <span>{{ currentRow.operator_name || '—' }}</span></div>
                <div class="info-row"><span class="info-label">🕒 操作时间</span>
                  <span>{{ (currentRow.operate_time || '—').slice(0, 16) }}</span></div>
                <div class="info-row"><span class="info-label">👥 班组</span>
                  <span>{{ currentRow.banzu || '—' }}</span></div>
                <div class="info-row"><span class="info-label">📌 备注</span>
                  <span>{{ currentRow.remark || '无' }}</span></div>
              </div>
            </div>

            <el-divider />
            <h4 class="timeline-title">📋 进度时间线</h4>
            <template v-if="progressList.length">
              <div v-for="item in progressList" :key="item.id" class="timeline">
                <span class="timeline-badge"
                  :style="{ background: progressTagColor(item.progress) }">
                  {{ item.progress }}
                </span>
                <small class="timeline-meta">
                  {{ (item.progress_date || '').slice(0, 16) }} — {{ item.operator_name || '系统' }}
                </small>
              </div>
            </template>
            <div v-else class="placeholder-text">暂无进度历史</div>

            <div class="progress-buttons">
              <el-button type="primary" size="small" @click="setProgress('已报账')">
                📑 已报账
              </el-button>
              <el-button type="success" size="small" @click="setProgress('已付款')">
                ✅ 已付款
              </el-button>
              <el-button type="warning" size="small" @click="setProgress('已完账')">
                🏁 已完账
              </el-button>
              <el-divider style="margin: 12px 0; width: 100%" />
              <el-button type="primary" size="small" @click="openEdit(currentRow)">
                编辑
              </el-button>
              <el-button type="danger" size="small" @click="doDelete(currentRow)">
                删除
              </el-button>
            </div>
          </div>
        </template>
        <div v-else class="placeholder-block">
          <div class="placeholder-icon">🛣️</div>
          <div>点击左侧记录查看完整详情</div>
          <div>及进度管理</div>
        </div>
      </div>
    </div>

    <!-- 新增/编辑弹窗 -->
    <el-dialog v-model="dlgVisible"
      :title="editingId ? '✏️ 编辑维修记录' : '➕ 新增维修记录'"
      width="620px" :close-on-click-modal="false">
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="100px">
        <el-form-item label="📍 地址" prop="address">
          <el-input v-model="form.address" />
        </el-form-item>
        <el-form-item label="🏢 单位">
          <el-select v-model="form.company" clearable style="width: 100%"
            @change="onCompanyChange">
            <el-option v-for="c in dicts.companies" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="👥 班组">
          <el-select v-model="form.banzu" clearable filterable style="width: 100%">
            <el-option v-for="b in dicts.banzu" :key="b" :label="b" :value="b" />
          </el-select>
        </el-form-item>
        <el-form-item label="📅 开挖日期">
          <el-date-picker v-model="form.dig_date" type="date" value-format="YYYY-MM-DD"
            style="width: 100%" />
        </el-form-item>
        <el-form-item label="🛤️ 道路类型">
          <el-select v-model="form.roadTypePriceId" clearable filterable style="width: 100%"
            placeholder="先选单位,再选类型(带通用价)" @change="onRoadTypeSelect">
            <el-option v-for="o in roadTypeOptions" :key="o.id" :label="o.display"
              :value="o.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="📐 面积(㎡)">
          <el-input-number v-model="form.area" :precision="3" :min="0" :controls="false"
            style="width: 100%" />
        </el-form-item>
        <el-form-item label="📏 决算面积">
          <el-input-number v-model="form.final_area" :precision="3" :min="0" :controls="false"
            style="width: 100%" @change="calcTotal" />
        </el-form-item>
        <el-form-item label="💰 单价(元)">
          <el-input-number v-model="form.price" :precision="2" :min="0" :controls="false"
            style="width: 100%" @change="calcTotal" />
        </el-form-item>
        <el-form-item label="💵 总额">
          <el-input-number v-model="form.total" :precision="2" :min="0" :controls="false"
            style="width: 100%" />
        </el-form-item>
        <el-form-item label="📝 维修原因">
          <el-input v-model="form.reason" />
        </el-form-item>
        <el-form-item label="📌 备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dlgVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>

    <!-- 批量更新进度 -->
    <el-dialog v-model="batchDlg" title="批量更新进度" width="320px" :close-on-click-modal="false">
      <el-select v-model="batchProgress" style="width: 100%">
        <el-option label="已报账" value="已报账" />
        <el-option label="已付款" value="已付款" />
        <el-option label="已完账" value="已完账" />
      </el-select>
      <template #footer>
        <el-button @click="batchDlg = false">取消</el-button>
        <el-button type="primary" @click="submitBatch">确定</el-button>
      </template>
    </el-dialog>

    <!-- 价格管理 -->
    <el-dialog v-model="priceDlg" title="路面类型价格管理" width="700px">
      <div class="price-toolbar">
        <el-input v-model="priceKeyword" clearable style="width: 220px"
          placeholder="搜索路面类型..." @keyup.enter="searchPrices" @clear="searchPrices" />
        <el-button type="primary" size="small" @click="searchPrices">搜索</el-button>
        <el-button type="primary" size="small" plain @click="openPriceAdd">新增价格</el-button>
        <span class="toolbar-hint">点击行可编辑</span>
      </div>
      <el-table v-loading="priceLoading" :data="priceRows" border stripe size="small"
        height="480" highlight-current-row @row-click="openPriceEdit">
        <el-table-column prop="company" label="适用单位" width="180">
          <template #default="{ row }">{{ row.company || '通用' }}</template>
        </el-table-column>
        <el-table-column prop="road_type" label="路面类型" min-width="240" />
        <el-table-column label="单价 (元)" width="120" align="right">
          <template #default="{ row }">{{ fmtMoney(row.price) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="70" align="center">
          <template #default="{ row }">
            <el-button link type="danger" size="small" @click.stop="doDeletePrice(row)">
              删除
            </el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-pagination v-model:current-page="pricePage" v-model:page-size="priceSize"
          :total="priceTotal" :page-sizes="[10, 20, 50]" layout="total, prev, pager, next" small
          @current-change="loadPrices" @size-change="searchPrices" />
      </div>
    </el-dialog>

    <!-- 价格编辑 -->
    <el-dialog v-model="priceEditDlg" :title="priceForm.id ? '编辑价格' : '新增价格'"
      width="350px" :close-on-click-modal="false" append-to-body>
      <el-form ref="priceFormRef" :model="priceForm" :rules="priceRules" label-width="80px">
        <el-form-item label="适用单位">
          <el-select v-model="priceForm.company" clearable filterable allow-create
            default-first-option style="width: 100%" placeholder="留空 = 通用">
            <el-option v-for="c in dicts.companies" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
        <el-form-item label="路面类型" prop="road_type">
          <el-input v-model="priceForm.road_type" />
        </el-form-item>
        <el-form-item label="单价 (元)" prop="price">
          <el-input-number v-model="priceForm.price" :precision="2" :min="0" :controls="false"
            style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="priceEditDlg = false">取消</el-button>
        <el-button type="primary" @click="submitPrice">保存</el-button>
      </template>
    </el-dialog>

    <!-- 附件抽屉 -->
    <el-drawer v-model="attDrawer" title="📎 附件管理" size="420px">
      <div v-loading="attLoading">
        <template v-if="attachments.length">
          <div v-for="att in attachments" :key="att.id" class="attachment-item">
            <span class="attachment-name" :title="att.file_name">{{ att.file_name }}</span>
            <span class="file-size">{{ fmtSize(att.file_size) }}</span>
            <el-button link type="primary" size="small" @click="doDownload(att)">下载</el-button>
            <el-button link type="danger" size="small" @click="doDeleteAttachment(att)">
              删除
            </el-button>
          </div>
        </template>
        <div v-else class="placeholder-text">暂无附件</div>
        <div class="upload-area">
          <input ref="fileRef" type="file" />
          <el-button type="primary" size="small" @click="doUpload">上传附件</el-button>
        </div>
        <div class="upload-hint">最大 10MB,不允许 exe/脚本/网页类文件</div>
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.rr-page {
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: calc(100vh - 84px);
}
.filter-card :deep(.el-card__body) {
  padding: 10px 14px 8px;
}
.filter-form :deep(.el-form-item) {
  margin-bottom: 6px;
  margin-right: 12px;
}
.date-sep {
  margin: 0 4px;
  color: #909399;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.price-btn {
  margin-left: auto;
}
.toolbar-hint {
  margin-left: 12px;
  color: #909399;
  font-size: 12px;
}
.main-layout {
  flex: 1;
  display: flex;
  min-height: 0;
  gap: 10px;
}
.table-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.pager {
  display: flex;
  justify-content: flex-end;
}
.card-panel {
  width: 520px;
  flex-shrink: 0;
  overflow-y: auto;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 4px;
  background: var(--el-fill-color-lighter);
}
.detail-card {
  padding: 16px;
}
.detail-card h3 {
  margin: 0 0 16px;
  font-size: 16px;
  font-weight: 600;
  border-left: 4px solid var(--el-color-primary);
  padding-left: 10px;
}
.info-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 0 16px;
}
.info-col {
  flex: 1;
  min-width: 220px;
}
.info-row {
  display: flex;
  align-items: baseline;
  margin-bottom: 10px;
  font-size: 13px;
}
.info-label {
  width: 88px;
  flex-shrink: 0;
  color: var(--el-text-color-secondary);
  font-weight: 600;
}
.highlight-total {
  color: var(--el-color-warning-dark-2);
  font-weight: bold;
}
.progress-tag {
  font-weight: bold;
}
.timeline-title {
  margin: 0 0 10px;
  color: var(--el-text-color-regular);
}
.timeline {
  border-left: 2px solid var(--el-color-primary);
  background: var(--el-fill-color);
  margin-bottom: 10px;
  padding: 8px 14px;
  border-radius: 0 10px 10px 0;
}
.timeline-badge {
  display: inline-block;
  color: #fff;
  padding: 3px 12px;
  border-radius: 5px;
  font-weight: bold;
  font-size: 13px;
}
.timeline-meta {
  display: block;
  margin-top: 6px;
  color: var(--el-text-color-secondary);
}
.progress-buttons {
  margin-top: 16px;
  display: flex;
  flex-wrap: wrap;
}
.placeholder-block {
  text-align: center;
  padding: 80px 20px;
  color: var(--el-text-color-placeholder);
}
.placeholder-icon {
  font-size: 44px;
  margin-bottom: 12px;
}
.placeholder-text {
  padding: 8px;
  color: var(--el-text-color-placeholder);
}
.price-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}
.attachment-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}
.attachment-name {
  flex: 1;
  color: var(--el-color-primary);
  font-weight: 500;
  word-break: break-all;
  font-size: 13px;
}
.file-size {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  flex-shrink: 0;
}
.upload-area {
  margin-top: 20px;
  padding: 14px;
  border: 1px dashed var(--el-border-color);
  border-radius: 8px;
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}
.upload-hint {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-placeholder);
}
.att-badge :deep(.el-badge__content) {
  transform: translate(100%, -40%);
}
</style>
