<script setup>
/**
 * 领料申请 —— 照旧 LingLiao/Index.cshtml + Edit.cshtml 复刻
 * 顶部: 查询(单号/供应商、状态、部门)
 * 中部: 领料单列表(新增/修改/提交/审核/反审核/驳回/作废/删除/导出/附件)
 * 下部: 选中单的领料明细(审核后可改实发数量)
 */
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  auditLingliaoOrder, cancelLingliaoOrder, deleteLingliaoFile, deleteLingliaoOrder,
  exportLingliaoOrder, getLingliaoDicts, getLingliaoDetails, getLingliaoOrder,
  listLingliaoFiles, listLingliaoMaterials, listLingliaoOrders, rejectLingliaoOrder,
  reverseAuditLingliaoOrder, saveLingliaoOrder, submitLingliaoOrder,
  updateLingliaoRenum, uploadLingliaoFile, uploadLingliaoTempFile,
} from '@/api/lingliao'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const username = computed(() => auth.user?.username || '')

const STATUS_MAP = {
  0: { label: '草稿', type: 'info' },
  1: { label: '已提交', type: 'primary' },
  2: { label: '已审核', type: 'success' },
  3: { label: '已驳回', type: 'danger' },
  4: { label: '已作废', type: 'info' },
  5: { label: '部分结算', type: 'warning' },
  6: { label: '全部结算', type: 'success' },
}

const dicts = reactive({
  suppliers: [], departments: [], statuses: [], perms: { view: true, audit: false },
})
const materials = ref([])

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = reactive({ current: 1, size: 20 })
const filters = reactive({ keyword: '', shzt: '', bmid: null })

const currentRow = ref(null)
const details = ref([])
const detailLoading = ref(false)

// 页面固定一屏:表格高度用 ResizeObserver 实测父容器后传给 el-table,避免出现页面滚动条
const listWrap = ref(null)
const detailWrap = ref(null)
const listTableH = ref(300)
const detailTableH = ref(180)
let tableObserver = null

function fitTables() {
  if (listWrap.value) listTableH.value = Math.max(120, listWrap.value.clientHeight)
  if (detailWrap.value) detailTableH.value = Math.max(80, detailWrap.value.clientHeight)
}

function onWindowResize() {
  fitTables()
}

function buildParams() {
  const p = { page: page.current, size: page.size }
  if (filters.keyword) p.keyword = filters.keyword
  if (filters.shzt !== '' && filters.shzt !== null) p.shzt = filters.shzt
  if (filters.bmid) p.bmid = filters.bmid
  return p
}

async function load() {
  loading.value = true
  try {
    const res = await listLingliaoOrders(buildParams())
    rows.value = res.rows
    total.value = res.total
  } finally {
    loading.value = false
  }
}

function search() {
  page.current = 1
  currentRow.value = null
  details.value = []
  load()
}

function resetFilters() {
  Object.assign(filters, { keyword: '', shzt: '', bmid: null })
  search()
}

async function loadDicts() {
  const d = await getLingliaoDicts()
  Object.assign(dicts, d)
}

onMounted(async () => {
  await loadDicts()
  materials.value = await listLingliaoMaterials()
  load()
  window.addEventListener('resize', onWindowResize)
  fitTables()
  if (typeof ResizeObserver !== 'undefined') {
    tableObserver = new ResizeObserver(fitTables)
    if (listWrap.value) tableObserver.observe(listWrap.value)
    if (detailWrap.value) tableObserver.observe(detailWrap.value)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onWindowResize)
  if (tableObserver) {
    tableObserver.disconnect()
    tableObserver = null
  }
})

// ==================== 选中行 / 明细 ====================
async function onRowClick(row) {
  currentRow.value = row
  await loadDetails(row.id)
}

async function loadDetails(orderId) {
  detailLoading.value = true
  try {
    details.value = await getLingliaoDetails(orderId)
  } finally {
    detailLoading.value = false
  }
}

async function refreshCurrent(orderId) {
  await load()
  const row = rows.value.find((r) => r.id === orderId)
  if (row) {
    currentRow.value = row
    await loadDetails(orderId)
  } else {
    currentRow.value = null
    details.value = []
  }
}

const canEdit = computed(() => {
  const row = currentRow.value
  return row && (row.shzt === 0 || row.shzt === 3) && row.sqren === username.value
})
const canSubmit = canEdit
const canCancel = canEdit
const canDelete = computed(() => {
  const row = currentRow.value
  return row && row.shzt === 4 && row.sqren === username.value
})
const canAudit = computed(() => currentRow.value && currentRow.value.shzt === 1)
const canReverse = computed(() => currentRow.value && currentRow.value.shzt === 2)
const canReject = computed(() => {
  const row = currentRow.value
  return row && row.shzt !== 3 && row.shzt !== 4
})
const canEditRenum = computed(() => {
  const row = currentRow.value
  return row && row.shzt === 2 && row.sqren === username.value
})

// ==================== 流程动作 ====================
async function ensureSelected() {
  if (!currentRow.value) {
    ElMessage.warning('请先选择一条记录')
    return false
  }
  return true
}

async function submitOrder() {
  if (!(await ensureSelected())) return
  if (!canSubmit.value) return ElMessage.warning('只有本人草稿和驳回单据才能提交')
  await ElMessageBox.confirm('确定要提交这条领料单吗？', '确认', { type: 'warning' })
  const id = currentRow.value.id
  await submitLingliaoOrder(id)
  ElMessage.success('提交成功')
  await refreshCurrent(id)
}

async function auditOrder() {
  if (!(await ensureSelected())) return
  await ElMessageBox.confirm('确定要审核这条领料单吗？', '确认', { type: 'warning' })
  const id = currentRow.value.id
  await auditLingliaoOrder(id)
  ElMessage.success('审核成功')
  await refreshCurrent(id)
}

async function reverseAuditOrder() {
  if (!(await ensureSelected())) return
  await ElMessageBox.confirm('确定要反审核这条领料单吗？', '确认', { type: 'warning' })
  const id = currentRow.value.id
  await reverseAuditLingliaoOrder(id)
  ElMessage.success('反审核成功')
  await refreshCurrent(id)
}

async function rejectOrder() {
  if (!(await ensureSelected())) return
  await ElMessageBox.confirm('确定要驳回这条领料单吗？', '确认', { type: 'warning' })
  const id = currentRow.value.id
  await rejectLingliaoOrder(id)
  ElMessage.success('驳回成功')
  await refreshCurrent(id)
}

async function cancelOrder() {
  if (!(await ensureSelected())) return
  if (!canCancel.value) return ElMessage.warning('只有本人草稿和驳回单据才能作废')
  await ElMessageBox.confirm('作废后将不可恢复，确定作废吗？', '确认', { type: 'warning' })
  const id = currentRow.value.id
  await cancelLingliaoOrder(id)
  ElMessage.success('作废成功')
  await refreshCurrent(id)
}

async function deleteOrder() {
  if (!(await ensureSelected())) return
  if (!canDelete.value) return ElMessage.warning('只有本人已作废单据才能删除')
  await ElMessageBox.confirm('删除后将不可恢复，确定删除吗？', '确认', { type: 'warning' })
  await deleteLingliaoOrder(currentRow.value.id)
  ElMessage.success('删除成功')
  currentRow.value = null
  details.value = []
  load()
}

async function changeRenum(row) {
  if (!canEditRenum.value) return ElMessage.warning('只有申请人本人且已审核后才能修改实发数量')
  let value
  try {
    const res = await ElMessageBox.prompt(
      `申请数量 ${row.num}，已结算 ${row.jiesuannum}`,
      '修改实发数量',
      {
        inputValue: String(row.renum ?? 0),
        inputPattern: /^\d+(\.\d{1,2})?$/,
        inputErrorMessage: '请输入不小于 0 的数字(最多 2 位小数)',
      },
    )
    value = Number(res.value)
  } catch {
    return
  }
  await updateLingliaoRenum(currentRow.value.id, row.id, value)
  ElMessage.success('实发数量已更新')
  await refreshCurrent(currentRow.value.id)
}

// ==================== 编辑弹窗 ====================
const editDlg = ref(false)
const editMode = ref('add')
const editFormRef = ref()
const saving = ref(false)
const editDetails = ref([])
const editFiles = ref([])
const editForm = reactive({ id: 0, sqriqi: '', gongyingshang: '', shuoming: '', bmid: null })

function today() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function emptyDetail() {
  return {
    id: 0, MaterialId: null, materialname: '', model: '', spec: '', unit: '',
    num: 1, beizhu: '',
  }
}

function resetEditForm() {
  Object.assign(editForm, {
    id: 0, sqriqi: today(), gongyingshang: '', shuoming: '',
    bmid: dicts.departments.length === 1 ? dicts.departments[0].id : null,
  })
  editDetails.value = []
  editFiles.value = []
}

function openAdd() {
  resetEditForm()
  editMode.value = 'add'
  editDlg.value = true
}

async function openEdit(row) {
  const target = row || currentRow.value
  if (!target) return ElMessage.warning('请先选择一条记录再修改')
  if (!((target.shzt === 0 || target.shzt === 3) && target.sqren === username.value)) {
    return ElMessage.warning('只有本人草稿和已驳回单据才能修改')
  }
  const res = await getLingliaoOrder(target.id)
  Object.assign(editForm, {
    id: res.id,
    sqriqi: res.sqriqi || today(),
    gongyingshang: res.gongyingshang || '',
    shuoming: res.shuoming || '',
    bmid: res.bmid || null,
  })
  editDetails.value = (res.Details || []).map((d) => ({ ...d }))
  editFiles.value = (res.files || []).map((f) => ({ ...f, isNew: false }))
  editMode.value = 'edit'
  editDlg.value = true
}

function addDetail() {
  editDetails.value.push(emptyDetail())
}

function removeDetail(index) {
  editDetails.value.splice(index, 1)
}

function onMaterialChange(row) {
  const material = materials.value.find((m) => m.MaterialId === row.MaterialId)
  if (!material) return
  row.materialname = material.materialname
  row.model = material.model
  row.spec = material.spec
  row.unit = material.unit
}

async function handleEditUpload(options) {
  if (options.file.size > 30 * 1024 * 1024) {
    ElMessage.error('单个附件不能超过 30MB')
    options.onError(new Error('too large'))
    return
  }
  try {
    const res = await uploadLingliaoTempFile(options.file)
    editFiles.value.push({
      id: 0,
      filename: res.filename,
      filepath: res.filepath,
      filesize: res.filesize,
      filesizeStr: formatSize(res.filesize),
      downloadUrl: res.downloadUrl,
      isNew: true,
    })
    options.onSuccess(res)
  } catch (err) {
    options.onError(err)
  }
}

function removeEditFile(index) {
  editFiles.value.splice(index, 1)
}

function formatSize(size) {
  const n = Number(size || 0)
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function viewFile(url) {
  if (url) window.open(url, '_blank')
}

async function saveEdit() {
  if (!editForm.sqriqi) return ElMessage.warning('请选择申请日期')
  for (let i = 0; i < editDetails.value.length; i += 1) {
    const row = editDetails.value[i]
    if (!row.MaterialId) return ElMessage.warning(`第 ${i + 1} 行材料不能为空`)
    if (!row.num || Number(row.num) <= 0) return ElMessage.warning(`第 ${i + 1} 行申请数量必须大于 0`)
  }
  if (!editDetails.value.length) return ElMessage.warning('请至少添加一条领料明细')
  saving.value = true
  try {
    await saveLingliaoOrder({
      id: editForm.id,
      sqriqi: editForm.sqriqi,
      gongyingshang: editForm.gongyingshang,
      shuoming: editForm.shuoming,
      bmid: editForm.bmid,
      Details: editDetails.value.map((d) => ({
        id: d.id || 0,
        MaterialId: d.MaterialId,
        materialname: d.materialname,
        model: d.model,
        spec: d.spec,
        unit: d.unit,
        num: Number(d.num),
        beizhu: d.beizhu,
      })),
      files: editFiles.value.map((f) => ({
        Id: f.id || 0,
        filename: f.filename,
        filepath: f.filepath,
        filesize: f.filesize,
      })),
    })
    ElMessage.success(editMode.value === 'add' ? '保存成功' : '修改成功')
    const savedId = editForm.id
    editDlg.value = false
    if (editMode.value === 'edit') await refreshCurrent(savedId)
    else await load()
  } finally {
    saving.value = false
  }
}

// ==================== 附件弹窗(列表页) ====================
const fileDlg = ref(false)
const fileOrderId = ref(0)
const fileList = ref([])
const fileLoading = ref(false)

async function openFiles(row) {
  fileOrderId.value = row.id
  fileDlg.value = true
  await loadFiles()
}

async function loadFiles() {
  fileLoading.value = true
  try {
    fileList.value = await listLingliaoFiles(fileOrderId.value)
  } finally {
    fileLoading.value = false
  }
}

async function handleAttachUpload(options) {
  if (options.file.size > 30 * 1024 * 1024) {
    ElMessage.error('单个附件不能超过 30MB')
    options.onError(new Error('too large'))
    return
  }
  try {
    await uploadLingliaoFile(fileOrderId.value, options.file)
    ElMessage.success('上传成功')
    options.onSuccess()
    await loadFiles()
    load()
  } catch (err) {
    options.onError(err)
  }
}

async function removeAttach(row) {
  try {
    await ElMessageBox.confirm(`确定删除附件「${row.filename}」吗？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  await deleteLingliaoFile(row.id)
  ElMessage.success('已删除')
  await loadFiles()
  load()
}

async function doExport(row) {
  await exportLingliaoOrder(row.id, row.danno)
  ElMessage.success('材料需求单已导出')
}
</script>

<template>
  <div class="ll-page">
    <el-card shadow="never" class="filter-card">
      <div class="filter-title">领料申请</div>
      <el-form inline class="filter-form">
        <el-form-item label="搜索">
          <el-input v-model="filters.keyword" clearable style="width: 220px"
            placeholder="单号 / 供应商" @keyup.enter="search" @clear="search" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.shzt" clearable placeholder="全部" style="width: 130px"
            @change="search">
            <el-option v-for="s in dicts.statuses" :key="s.value" :label="s.label"
              :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="部门">
          <el-select v-model="filters.bmid" clearable filterable placeholder="选择部门"
            style="width: 160px" @change="search">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.bm" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>

      <div class="toolbar">
        <el-button type="primary" size="small" @click="openAdd">新增</el-button>
        <el-button size="small" :disabled="!canEdit" @click="openEdit()">修改</el-button>
        <el-button size="small" :disabled="!canSubmit" @click="submitOrder">提交</el-button>
        <template v-if="dicts.perms.audit">
          <el-button size="small" type="success" plain :disabled="!canAudit"
            @click="auditOrder">审核</el-button>
          <el-button size="small" type="warning" plain :disabled="!canReverse"
            @click="reverseAuditOrder">反审核</el-button>
          <el-button size="small" type="danger" plain :disabled="!canReject"
            @click="rejectOrder">驳回</el-button>
        </template>
        <el-button size="small" :disabled="!canCancel" @click="cancelOrder">作废</el-button>
        <el-button size="small" type="danger" plain :disabled="!canDelete"
          @click="deleteOrder">删除</el-button>
        <span class="toolbar-hint">共 {{ total }} 条 · 单击行查看领料明细，双击可修改</span>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <div ref="listWrap" class="ll-table-wrap">
        <el-table v-loading="loading" :data="rows" border stripe size="small"
          :max-height="listTableH" row-key="id" highlight-current-row
          @row-click="onRowClick" @row-dblclick="openEdit">
          <el-table-column prop="danno" label="单号" width="145" show-overflow-tooltip />
          <el-table-column prop="bm" label="部门" width="110" show-overflow-tooltip />
          <el-table-column prop="sqren" label="申请人" width="90" show-overflow-tooltip />
          <el-table-column prop="sqriqi" label="申请日期" width="105" />
          <el-table-column prop="shren" label="审核人" width="90" show-overflow-tooltip />
          <el-table-column prop="shriqi" label="审核/驳回日期" width="120" />
          <el-table-column prop="gongyingshang" label="供应商" min-width="130"
            show-overflow-tooltip />
          <el-table-column prop="shuoming" label="用途说明" min-width="150"
            show-overflow-tooltip />
          <el-table-column label="状态" width="95" align="center">
            <template #default="{ row }">
              <el-tag :type="STATUS_MAP[row.shzt]?.type || 'info'" size="small">
                {{ STATUS_MAP[row.shzt]?.label || row.shzt }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="下载明细" width="85" align="center">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click.stop="doExport(row)">
                导出
              </el-button>
            </template>
          </el-table-column>
          <el-table-column label="附件" width="80" align="center">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click.stop="openFiles(row)">
                附件({{ row.fileCount || 0 }})
              </el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div class="pager">
        <el-pagination v-model:current-page="page.current" v-model:page-size="page.size"
          :total="total" :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="load" @size-change="search" />
      </div>
    </el-card>

    <el-card shadow="never" class="detail-card">
      <template #header>
        <span>
          领料明细
          <template v-if="currentRow">
            · {{ currentRow.danno }}
            <el-tag :type="STATUS_MAP[currentRow.shzt]?.type || 'info'" size="small"
              class="ml6">{{ STATUS_MAP[currentRow.shzt]?.label }}</el-tag>
          </template>
        </span>
      </template>
      <div ref="detailWrap" class="ll-detail-wrap">
        <el-table v-loading="detailLoading" :data="details" border stripe size="small"
          :max-height="detailTableH" row-key="id">
          <el-table-column type="index" label="序号" width="55" align="center" />
          <el-table-column prop="llname" label="材料名称" min-width="160"
            show-overflow-tooltip />
          <el-table-column prop="model" label="型号" width="120" show-overflow-tooltip />
          <el-table-column prop="spec" label="规格" width="120" show-overflow-tooltip />
          <el-table-column prop="unit" label="单位" width="70" align="center" />
          <el-table-column prop="num" label="申请数量" width="90" align="center" />
          <el-table-column prop="renum" label="实发数量" width="90" align="center" />
          <el-table-column prop="jiesuannum" label="已结算数量" width="100" align="center" />
          <el-table-column label="结算状态" width="95" align="center">
            <template #default="{ row }">
              <span v-if="row.jiesuanzt === 0" class="text-muted">
                {{ Number(row.renum) === 0 ? '未领货' : '未结算' }}
              </span>
              <el-tag v-else-if="row.jiesuanzt === 1" type="warning" size="small">部分结算</el-tag>
              <el-tag v-else type="success" size="small">全部结算</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="beizhu" label="备注" min-width="120" show-overflow-tooltip />
          <el-table-column label="操作" width="95" align="center">
            <template #default="{ row }">
              <el-button v-if="canEditRenum" link type="primary" size="small"
                @click="changeRenum(row)">修改实发</el-button>
              <span v-else class="text-muted">-</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <!-- ==================== 新增/编辑 ==================== -->
    <el-dialog v-model="editDlg" :title="editMode === 'add' ? '新增领料单' : '编辑领料单'"
      width="min(1020px, calc(100vw - 40px))" class="jc-form-dialog"
      :close-on-click-modal="false" destroy-on-close>
      <el-form ref="editFormRef" :model="editForm" label-width="80px" size="small">
        <el-tabs>
          <el-tab-pane label="基本信息">
            <div class="form-grid">
              <el-form-item label="申请日期" required>
                <el-date-picker v-model="editForm.sqriqi" type="date" value-format="YYYY-MM-DD"
                  style="width: 100%" />
              </el-form-item>
              <el-form-item label="供应商">
                <el-select v-model="editForm.gongyingshang" filterable allow-create
                  default-first-option clearable style="width: 100%" placeholder="选择或输入供应商">
                  <el-option v-for="g in dicts.suppliers" :key="g" :label="g" :value="g" />
                </el-select>
              </el-form-item>
              <el-form-item label="领用部门">
                <el-select v-model="editForm.bmid" clearable filterable style="width: 100%"
                  placeholder="不选则取本人部门">
                  <el-option v-for="d in dicts.departments" :key="d.id" :label="d.bm"
                    :value="d.id" />
                </el-select>
              </el-form-item>
              <el-form-item label="用途说明" class="span2">
                <el-input v-model="editForm.shuoming" type="textarea" :rows="2"
                  maxlength="500" show-word-limit />
              </el-form-item>
            </div>
          </el-tab-pane>

          <el-tab-pane label="领料明细">
            <div class="detail-toolbar">
              <el-button type="primary" size="small" @click="addDetail">新增明细</el-button>
              <span class="toolbar-hint">选择材料后自动带出型号、规格、单位</span>
            </div>
            <el-table :data="editDetails" border size="small" max-height="360">
              <el-table-column label="材料名称" min-width="280">
                <template #default="{ row }">
                  <el-select v-model="row.MaterialId" filterable clearable placeholder="选择材料"
                    style="width: 100%" @change="onMaterialChange(row)">
                    <el-option v-for="m in materials" :key="m.MaterialId"
                      :label="m.materialname" :value="m.MaterialId" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="型号" width="120">
                <template #default="{ row }"><el-input v-model="row.model" /></template>
              </el-table-column>
              <el-table-column label="规格" width="120">
                <template #default="{ row }"><el-input v-model="row.spec" /></template>
              </el-table-column>
              <el-table-column label="单位" width="75">
                <template #default="{ row }"><el-input v-model="row.unit" /></template>
              </el-table-column>
              <el-table-column label="申请数量" width="130" align="center">
                <template #default="{ row }">
                  <el-input-number v-model="row.num" :min="0.01" :precision="2" :step="1"
                    controls-position="right" style="width: 110px" />
                </template>
              </el-table-column>
              <el-table-column label="备注" min-width="150">
                <template #default="{ row }"><el-input v-model="row.beizhu" /></template>
              </el-table-column>
              <el-table-column label="操作" width="65" align="center">
                <template #default="{ $index }">
                  <el-button link type="danger" size="small"
                    @click="removeDetail($index)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="附件">
            <div class="detail-toolbar">
              <el-upload :show-file-list="false" :http-request="handleEditUpload" multiple>
                <el-button type="primary" size="small">选择附件</el-button>
              </el-upload>
              <span class="toolbar-hint">支持图片/PDF/Office/压缩包，单个不超过 30MB</span>
            </div>
            <el-table :data="editFiles" border size="small" max-height="300"
              empty-text="暂无附件">
              <el-table-column prop="filename" label="文件名" min-width="260"
                show-overflow-tooltip />
              <el-table-column label="大小" width="100" align="center">
                <template #default="{ row }">
                  {{ row.filesizeStr || formatSize(row.filesize) }}
                </template>
              </el-table-column>
              <el-table-column label="操作" width="130" align="center">
                <template #default="{ row, $index }">
                  <el-button link type="primary" size="small"
                    @click="viewFile(row.downloadUrl)">查看</el-button>
                  <el-button link type="danger" size="small"
                    @click="removeEditFile($index)">删除</el-button>
                </template>
              </el-table-column>
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </el-form>
      <template #footer>
        <el-button @click="editDlg = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 附件管理(列表页) ==================== -->
    <el-dialog v-model="fileDlg" title="附件管理" width="620px" destroy-on-close>
      <div class="detail-toolbar">
        <el-upload :show-file-list="false" :http-request="handleAttachUpload" multiple>
          <el-button type="primary" size="small">选择附件</el-button>
        </el-upload>
        <span class="toolbar-hint">单个附件不超过 30MB</span>
      </div>
      <el-table v-loading="fileLoading" :data="fileList" border size="small" max-height="320"
        empty-text="暂无附件">
        <el-table-column prop="filename" label="文件名" min-width="240" show-overflow-tooltip />
        <el-table-column prop="filesizeStr" label="大小" width="90" align="center" />
        <el-table-column prop="operator_name" label="上传人" width="90" align="center" />
        <el-table-column label="操作" width="130" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small"
              @click="viewFile(row.downloadUrl)">查看</el-button>
            <el-button v-if="row.canDelete" link type="danger" size="small"
              @click="removeAttach(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="fileDlg = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.ll-page {
  box-sizing: border-box;
  height: calc(100vh - 94px);
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow: hidden;
}
.filter-card {
  flex: 0 0 auto;
}
.filter-card :deep(.el-card__body) {
  padding: 8px 12px;
}
.filter-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 6px;
}
.filter-form :deep(.el-form-item) {
  margin-bottom: 0;
  margin-right: 10px;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 4px;
}
.toolbar-hint {
  margin-left: auto;
  color: #909399;
  font-size: 12px;
}
.table-card {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.table-card :deep(.el-card__body) {
  padding: 6px 8px;
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.ll-table-wrap {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}
.pager {
  flex: 0 0 auto;
  display: flex;
  justify-content: flex-end;
  margin-top: 4px;
}
.detail-card {
  flex: 0 0 238px;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.detail-card :deep(.el-card__header) {
  padding: 6px 12px;
}
.detail-card :deep(.el-card__body) {
  padding: 6px 8px;
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.ll-detail-wrap {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}
/* 紧凑行高,避免表格内出现不必要的纵向滚动 */
.ll-page :deep(.el-table--small .el-table__cell) {
  padding: 2px 0;
}
.ll-page :deep(.el-table .cell) {
  line-height: 20px;
  padding: 0 4px;
}
.ll-page :deep(.el-table__header-wrapper th) {
  padding: 3px 0;
}
@media (max-height: 760px) {
  .ll-page {
    gap: 5px;
  }
  .detail-card {
    flex-basis: 190px;
  }
  .filter-title {
    margin-bottom: 4px;
  }
}
.ml6 {
  margin-left: 6px;
}
.text-muted {
  color: #909399;
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0 18px;
}
.form-grid .span2 {
  grid-column: span 2;
}
.detail-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
</style>
