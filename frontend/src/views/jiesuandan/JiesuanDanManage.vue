<script setup>
/**
 * 领料结算 —— 照旧 Views/jiesuandan/Index.cshtml 1:1 复刻
 * 上部: 结算单列表(新增/编辑/删除/导出结算表/采购单据/附件)
 * 下部: 选中结算单的结算明细(编辑数量单价/删除)
 * 双击结算单行: 选择可结算的领料明细,按供应商过滤
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  addJiesuanDetails, deleteJiesuanAttachment, deleteJiesuanDetail, deleteJiesuanOrder,
  exportJiesuanCg, exportJiesuanDetail, getJiesuanCreateInit, getJiesuanDetails,
  getJiesuanDicts, getJiesuanOrder, listJiesuanAttachments, listJiesuanCandidates,
  listJiesuanOrders, saveJiesuanOrder, updateJiesuanDetail, uploadJiesuanAttachment,
} from '@/api/jiesuandan'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const router = useRouter()
const username = computed(() => auth.user?.username || '')
const isSuperuser = computed(() => !!auth.user?.is_superuser)

const dicts = reactive({ suppliers: [], departments: [], perms: { view: true, manage: false }, userBm: '' })

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = reactive({ current: 1, size: 20 })
const filters = reactive({ keyword: '', bmid: null })

const currentRow = ref(null)
const details = ref([])
const detailLoading = ref(false)

const canEdit = computed(() => {
  const row = currentRow.value
  if (!row) return false
  return isSuperuser.value || row.createuser === username.value
})

// ==================== 页面高度自适应 ====================
const listWrap = ref(null)
const detailWrap = ref(null)
const listTableH = ref(320)
const detailTableH = ref(210)
let observer = null

function fitTables() {
  if (listWrap.value) listTableH.value = Math.max(140, listWrap.value.clientHeight)
  if (detailWrap.value) detailTableH.value = Math.max(100, detailWrap.value.clientHeight)
}
function onResize() { fitTables() }

onMounted(async () => {
  await loadDicts()
  await load()
  window.addEventListener('resize', onResize)
  fitTables()
  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(fitTables)
    if (listWrap.value) observer.observe(listWrap.value)
    if (detailWrap.value) observer.observe(detailWrap.value)
  }
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  if (observer) { observer.disconnect(); observer = null }
})

function money(v) {
  return Number(v || 0).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
function numText(v) {
  const n = Number(v || 0)
  return Number.isInteger(n) ? String(n) : String(Number(n.toFixed(4)))
}

// ==================== 列表 ====================
async function loadDicts() {
  Object.assign(dicts, await getJiesuanDicts())
}

function buildParams() {
  const p = { page: page.current, size: page.size }
  if (filters.keyword) p.keyword = filters.keyword
  if (filters.bmid) p.bmid = filters.bmid
  return p
}

async function load() {
  loading.value = true
  try {
    const res = await listJiesuanOrders(buildParams())
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
  Object.assign(filters, { keyword: '', bmid: null })
  search()
}

async function onRowClick(row) {
  currentRow.value = row
  await loadDetails(row.id)
}

async function loadDetails(orderId) {
  detailLoading.value = true
  try {
    details.value = await getJiesuanDetails(orderId)
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

// ==================== 新增/编辑结算单 ====================
const saveDlg = ref(false)
const saveMode = ref('add')
const saving = ref(false)
const saveForm = reactive({ id: 0, jiesuandanno: '', gongyingshang: '', jiesuanriqi: '', beizhu: '', createuser: '' })

function today() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

async function openAdd() {
  Object.assign(saveForm, {
    id: 0, jiesuandanno: '', gongyingshang: '', jiesuanriqi: today(), beizhu: '', createuser: '',
  })
  saveMode.value = 'add'
  saveDlg.value = true
  try {
    const res = await getJiesuanCreateInit()
    saveForm.jiesuandanno = res.jiesuandanno
    saveForm.createuser = res.createuser
  } catch { /* 初始化失败时允许手工填单号 */ }
}

async function openEdit(row) {
  const target = row || currentRow.value
  if (!target) return ElMessage.warning('请先选择一行')
  if (!(isSuperuser.value || target.createuser === username.value)) {
    return ElMessage.warning('您不是创建人,不能编辑此结算单')
  }
  const res = await getJiesuanOrder(target.id)
  Object.assign(saveForm, {
    id: res.id,
    jiesuandanno: res.jiesuandanno || '',
    gongyingshang: res.gongyingshang || '',
    jiesuanriqi: res.jiesuanriqi || today(),
    beizhu: res.beizhu || '',
    createuser: res.createuser || '',
  })
  saveMode.value = 'edit'
  saveDlg.value = true
}

async function submitSave() {
  if (!saveForm.jiesuanriqi) return ElMessage.warning('请选择结算日期')
  saving.value = true
  try {
    const res = await saveJiesuanOrder({
      id: saveForm.id,
      jiesuandanno: saveForm.jiesuandanno,
      gongyingshang: saveForm.gongyingshang,
      jiesuanriqi: saveForm.jiesuanriqi,
      beizhu: saveForm.beizhu,
    })
    ElMessage.success(saveMode.value === 'add' ? '添加成功' : '修改成功')
    saveDlg.value = false
    if (saveMode.value === 'edit' && res.id) await refreshCurrent(res.id)
    else await load()
  } finally {
    saving.value = false
  }
}

async function removeOrder() {
  if (!currentRow.value) return ElMessage.warning('请先选择要删除的结算单')
  if (!canEdit.value) return ElMessage.warning('您不是创建人,不能删除此结算单')
  try {
    await ElMessageBox.confirm(
      `确定要删除单号：${currentRow.value.jiesuandanno} 吗？`, '确认', { type: 'warning' },
    )
  } catch { return }
  await deleteJiesuanOrder(currentRow.value.id)
  ElMessage.success('删除成功')
  currentRow.value = null
  details.value = []
  await load()
}

// ==================== 结算明细 ====================
const editingId = ref(0)
const editDetail = reactive({ num: 0, danjia: 0 })

function startEditDetail(row) {
  editingId.value = row.id
  editDetail.num = Number(row.num || 0)
  editDetail.danjia = Number(row.danjia || 0)
}

function cancelEditDetail() {
  editingId.value = 0
}

async function saveDetail(row) {
  if (!editDetail.num || editDetail.num <= 0) return ElMessage.warning('数量不能为0或空')
  if (!editDetail.danjia || editDetail.danjia <= 0) return ElMessage.warning('单价不能为0或空')
  await updateJiesuanDetail(row.id, { num: editDetail.num, danjia: editDetail.danjia })
  ElMessage.success('明细已保存')
  editingId.value = 0
  await load()
  await loadDetails(currentRow.value.id)
}

async function removeDetail(row) {
  try {
    await ElMessageBox.confirm('确定删除该明细吗？', '确认', { type: 'warning' })
  } catch { return }
  await deleteJiesuanDetail(row.id)
  ElMessage.success('明细已删除')
  await load()
  await loadDetails(currentRow.value.id)
}

// ==================== 选择领料明细 ====================
const cand = reactive({
  dlg: false, orderId: 0, supplier: '', keyword: '', loading: false,
  rows: [], total: 0, page: 1, size: 20,
  selected: {}, edits: {},
})
const candTable = ref(null)
let restoring = false

function candidateQuery() {
  const p = { page: cand.page, size: cand.size }
  if (cand.keyword) p.keyword = cand.keyword
  if (cand.supplier) p.gongyingshang = cand.supplier
  return p
}

async function loadCandidates() {
  cand.loading = true
  try {
    const res = await listJiesuanCandidates(candidateQuery())
    cand.total = res.total
    cand.rows = res.rows.map((row) => {
      const edited = cand.edits[row.id]
      return { ...row, danjia: edited?.danjia ?? row.danjia, thisnum: edited?.thisnum ?? row.thisnum }
    })
    await nextTick()
    restoring = true
    for (const row of cand.rows) {
      if (cand.selected[row.id]) candTable.value?.toggleRowSelection(row, true)
    }
    restoring = false
  } finally {
    cand.loading = false
  }
}

async function openCandidates() {
  if (!currentRow.value) return ElMessage.warning('请先选择一个结算单')
  if (!canEdit.value) return ElMessage.warning('您不是创建人,不能编辑此结算单明细')
  cand.orderId = currentRow.value.id
  cand.supplier = currentRow.value.gongyingshang || ''
  cand.keyword = ''
  cand.page = 1
  cand.selected = {}
  cand.edits = {}
  cand.dlg = true
  await loadCandidates()
}

function onCandPageChange(p) {
  cand.page = p
  loadCandidates()
}

function onCandSizeChange(size) {
  cand.size = size
  cand.page = 1
  loadCandidates()
}

function handleSelect(selection, row) {
  if (restoring) return
  if (selection.some((r) => r.id === row.id)) cand.selected[row.id] = row
  else delete cand.selected[row.id]
}

function handleSelectAll(selection) {
  if (restoring) return
  const ids = new Set(selection.map((r) => r.id))
  for (const row of cand.rows) {
    if (ids.has(row.id)) cand.selected[row.id] = row
    else delete cand.selected[row.id]
  }
}

function onCandEdit(row) {
  cand.edits[row.id] = { thisnum: Number(row.thisnum || 0), danjia: Number(row.danjia || 0) }
}

const candTotal = computed(() => {
  let sum = 0
  for (const id of Object.keys(cand.selected)) {
    const row = cand.selected[id]
    const edited = cand.edits[id] || {}
    const num = Number(edited.thisnum ?? row.thisnum ?? 0)
    const price = Number(edited.danjia ?? row.danjia ?? 0)
    sum += num * price
  }
  return sum
})

async function addSelectedCandidates() {
  const ids = Object.keys(cand.selected)
  if (!ids.length) return ElMessage.warning('请选择明细')
  const list = []
  for (const id of ids) {
    const row = cand.selected[id]
    const edited = cand.edits[id] || {}
    const num = Number(edited.thisnum ?? row.thisnum ?? 0)
    const price = Number(edited.danjia ?? row.danjia ?? 0)
    if (!(num > 0)) {
      return ElMessage.warning(`材料【${row.llname || id}】本次结算数量必须大于0,请填写"本次结算"列`)
    }
    if (num > Number(row.shengyu || 0)) {
      return ElMessage.warning(`材料【${row.llname || id}】结算数量(${num})超出剩余可结算(${row.shengyu})`)
    }
    list.push({ LingliaoDetailId: Number(id), Num: num, Danjia: price })
  }
  await addJiesuanDetails(cand.orderId, list)
  ElMessage.success('结算明细保存成功')
  cand.dlg = false
  cand.selected = {}
  cand.edits = {}
  await refreshCurrent(cand.orderId)
}

// ==================== 采购单据 ====================
const cgDlg = ref(false)
const cgOrder = ref(null)
const cgSgbm = ref('')
const cgSgyy = ref('')

function openCgDlg(row) {
  cgOrder.value = row
  cgSgbm.value = ''
  cgSgyy.value = ''
  cgDlg.value = true
}

async function downloadCg(type) {
  if (!cgOrder.value) return
  await exportJiesuanCg(cgOrder.value.id, type, cgSgbm.value, cgSgyy.value, cgOrder.value.jiesuandanno)
  ElMessage.success(type === 2 ? '验收单已下载' : '申请单已下载')
}

function openPrint() {
  if (!cgOrder.value) return
  const href = router.resolve({
    path: '/jiesuandan/print',
    query: { id: cgOrder.value.id, sgbm: cgSgbm.value, sgyy: cgSgyy.value },
  }).href
  window.open(href, '_blank')
}

// ==================== 附件 ====================
const attDlg = ref(false)
const attOrder = ref(null)
const attList = ref([])
const attLoading = ref(false)

async function openAttachments(row) {
  attOrder.value = row
  attDlg.value = true
  await loadAttachments()
}

async function loadAttachments() {
  if (!attOrder.value) return
  attLoading.value = true
  try {
    attList.value = await listJiesuanAttachments(attOrder.value.id)
  } finally {
    attLoading.value = false
  }
}

async function handleAttachUpload(options) {
  if (options.file.size > 30 * 1024 * 1024) {
    ElMessage.error('单个文件不能超过30MB')
    options.onError(new Error('too large'))
    return
  }
  try {
    await uploadJiesuanAttachment(attOrder.value.id, options.file)
    ElMessage.success('上传成功')
    options.onSuccess()
    await loadAttachments()
    await load()
  } catch (err) {
    options.onError(err)
  }
}

async function removeAttachment(row) {
  try {
    await ElMessageBox.confirm(`确定删除附件「${row.filename}」吗？`, '提示', { type: 'warning' })
  } catch { return }
  await deleteJiesuanAttachment(row.id)
  ElMessage.success('已删除')
  await loadAttachments()
  await load()
}

function viewFile(url) {
  if (url) window.open(url, '_blank')
}

async function doExportDetail(row) {
  await exportJiesuanDetail(row.id, row.jiesuandanno)
  ElMessage.success('销售结算表已导出')
}
</script>

<template>
  <div class="jsd-page">
    <el-card shadow="never" class="filter-card">
      <div class="filter-title">领料结算</div>
      <el-form inline class="filter-form">
        <el-form-item label="搜索">
          <el-input v-model="filters.keyword" clearable style="width: 220px"
            placeholder="单号 / 供应商" @keyup.enter="search" @clear="search" />
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
        <el-button type="primary" size="small" @click="openAdd">添加结算单</el-button>
        <el-button size="small" :disabled="!canEdit" @click="openEdit()">编辑结算单</el-button>
        <el-button size="small" type="danger" plain :disabled="!canEdit" @click="removeOrder">
          删除结算单
        </el-button>
        <span class="toolbar-hint">共 {{ total }} 条 · 单击行查看结算明细,双击行编辑明细</span>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <div ref="listWrap" class="jsd-table-wrap">
        <el-table v-loading="loading" :data="rows" border stripe size="small"
          :max-height="listTableH" row-key="id" highlight-current-row
          @row-click="onRowClick" @row-dblclick="openCandidates">
          <el-table-column prop="jiesuandanno" label="单号" width="160" show-overflow-tooltip />
          <el-table-column prop="gongyingshang" label="供应商" min-width="180"
            show-overflow-tooltip />
          <el-table-column prop="jiesuanriqi" label="结算日期" width="105" />
          <el-table-column label="结算总额" width="120" align="right">
            <template #default="{ row }">{{ money(row.zonge) }}</template>
          </el-table-column>
          <el-table-column prop="createuser" label="用户名" width="100" show-overflow-tooltip />
          <el-table-column prop="beizhu" label="备注" min-width="140" show-overflow-tooltip />
          <el-table-column label="下载明细" width="90" align="center">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click.stop="doExportDetail(row)">
                导出
              </el-button>
            </template>
          </el-table-column>
          <el-table-column label="采购单据" width="90" align="center">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click.stop="openCgDlg(row)">
                采购单据
              </el-button>
            </template>
          </el-table-column>
          <el-table-column label="附件" width="80" align="center">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click.stop="openAttachments(row)">
                附件({{ row.fujianCount || 0 }})
              </el-button>
            </template>
          </el-table-column>
          <el-table-column prop="shriqi" label="操作日期" width="150" />
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
          结算明细
          <template v-if="currentRow">
            · {{ currentRow.jiesuandanno }} · 供应商：{{ currentRow.gongyingshang || '—' }}
          </template>
        </span>
      </template>
      <div ref="detailWrap" class="jsd-detail-wrap">
        <el-table v-loading="detailLoading" :data="details" border stripe size="small"
          :max-height="detailTableH" row-key="id">
          <el-table-column prop="id" label="ID" width="60" align="center" />
          <el-table-column prop="danno" label="领料单号" width="150" show-overflow-tooltip />
          <el-table-column prop="gongyingshang" label="领料单供应商" min-width="150"
            show-overflow-tooltip />
          <el-table-column prop="MaterialId" label="材料ID" width="75" align="center" />
          <el-table-column prop="llname" label="材料名称" min-width="150" show-overflow-tooltip />
          <el-table-column prop="model" label="型号" width="110" show-overflow-tooltip />
          <el-table-column prop="spec" label="规格" width="110" show-overflow-tooltip />
          <el-table-column prop="unit" label="单位" width="65" align="center" />
          <el-table-column label="数量" width="120" align="center">
            <template #default="{ row }">
              <el-input-number v-if="editingId === row.id" v-model="editDetail.num" :min="0.01"
                :precision="2" :step="1" controls-position="right" size="small"
                style="width: 105px" />
              <span v-else>{{ numText(row.num) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="单价" width="120" align="center">
            <template #default="{ row }">
              <el-input-number v-if="editingId === row.id" v-model="editDetail.danjia" :min="0.01"
                :precision="2" :step="1" controls-position="right" size="small"
                style="width: 105px" />
              <span v-else>{{ numText(row.danjia) }}</span>
            </template>
          </el-table-column>
          <el-table-column label="金额" width="110" align="right">
            <template #default="{ row }">
              {{ editingId === row.id
                ? money(Number(editDetail.num || 0) * Number(editDetail.danjia || 0))
                : money(row.jine) }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="150" align="center">
            <template #default="{ row }">
              <template v-if="editingId === row.id">
                <el-button link type="primary" size="small" @click="saveDetail(row)">保存</el-button>
                <el-button link size="small" @click="cancelEditDetail">取消</el-button>
              </template>
              <template v-else-if="canEdit">
                <el-button link type="primary" size="small" @click="startEditDetail(row)">
                  编辑
                </el-button>
                <el-button link type="danger" size="small" @click="removeDetail(row)">删除</el-button>
              </template>
              <span v-else class="text-muted">-</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </el-card>

    <!-- ==================== 新增/编辑结算单 ==================== -->
    <el-dialog v-model="saveDlg" :title="saveMode === 'add' ? '新增结算单' : '编辑结算单'"
      width="620px" class="std-dialog" :close-on-click-modal="false" destroy-on-close>
      <el-form :model="saveForm" label-width="90px" size="small">
        <el-form-item label="结算单号">
          <el-input v-model="saveForm.jiesuandanno" readonly />
        </el-form-item>
        <el-form-item label="供应商">
          <el-select v-model="saveForm.gongyingshang" filterable allow-create default-first-option
            clearable style="width: 100%" placeholder="选择或输入供应商">
            <el-option v-for="g in dicts.suppliers" :key="g" :label="g" :value="g" />
          </el-select>
        </el-form-item>
        <el-form-item label="结算日期">
          <el-date-picker v-model="saveForm.jiesuanriqi" type="date" value-format="YYYY-MM-DD"
            style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="saveForm.beizhu" type="textarea" :rows="4" maxlength="850"
            show-word-limit />
        </el-form-item>
        <el-form-item label="创建人">
          <el-input v-model="saveForm.createuser" readonly />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="saveDlg = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitSave">保存</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 选择领料明细 ==================== -->
    <el-dialog v-model="cand.dlg" class="std-dialog" width="min(1300px, calc(100vw - 60px))"
      :title="'选择领料明细' + (cand.supplier ? '（供应商：' + cand.supplier + '）' : '')"
      :close-on-click-modal="false" destroy-on-close>
      <div class="cand-toolbar">
        <el-input v-model="cand.keyword" clearable style="width: 300px"
          placeholder="搜索供应商或材料名称" @keyup.enter="cand.page = 1; loadCandidates()"
          @clear="cand.page = 1; loadCandidates()" />
        <el-button type="primary" @click="cand.page = 1; loadCandidates()">搜索</el-button>
        <el-button @click="cand.keyword = ''; cand.page = 1; loadCandidates()">清空</el-button>
        <span class="cand-total">合计金额：<b>{{ money(candTotal) }}</b></span>
      </div>
      <el-table ref="candTable" v-loading="cand.loading" :data="cand.rows" border size="small"
        row-key="id" max-height="440" @select="handleSelect" @select-all="handleSelectAll">
        <el-table-column type="selection" width="45" reserve-selection />
        <el-table-column prop="danno" label="领料单号" width="150" show-overflow-tooltip />
        <el-table-column prop="cailiaoID" label="材料ID" width="70" align="center" />
        <el-table-column prop="llname" label="材料名称" min-width="130" show-overflow-tooltip />
        <el-table-column prop="gongyingshang" label="供应商" min-width="150"
          show-overflow-tooltip />
        <el-table-column prop="model" label="型号" width="90" show-overflow-tooltip />
        <el-table-column prop="spec" label="规格" width="90" show-overflow-tooltip />
        <el-table-column prop="unit" label="单位" width="60" align="center" />
        <el-table-column prop="renum" label="可结算" width="80" align="center" />
        <el-table-column prop="jiesuannum" label="已结算" width="80" align="center" />
        <el-table-column prop="shengyu" label="剩余数" width="80" align="center" />
        <el-table-column label="单价" width="115" align="center">
          <template #default="{ row }">
            <el-input-number v-model="row.danjia" :min="0" :precision="2" :step="1"
              controls-position="right" size="small" style="width: 100px"
              @change="onCandEdit(row)" />
          </template>
        </el-table-column>
        <el-table-column label="本次结算" width="115" align="center">
          <template #default="{ row }">
            <el-input-number v-model="row.thisnum" :min="0" :precision="2" :step="1"
              controls-position="right" size="small" style="width: 100px"
              @change="onCandEdit(row)" />
          </template>
        </el-table-column>
        <el-table-column label="金额" width="100" align="right">
          <template #default="{ row }">
            {{ money(Number(row.thisnum || 0) * Number(row.danjia || 0)) }}
          </template>
        </el-table-column>
      </el-table>
      <div class="pager cand-pager">
        <el-pagination v-model:current-page="cand.page" v-model:page-size="cand.size"
          :total="cand.total" :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="onCandPageChange" @size-change="onCandSizeChange" />
      </div>
      <template #footer>
        <el-button @click="cand.dlg = false">取消</el-button>
        <el-button type="primary" @click="addSelectedCandidates">添加到结算明细</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 采购申请单/验收单 ==================== -->
    <el-dialog v-model="cgDlg" title="下载/打印采购单据" width="560px" class="std-dialog"
      :close-on-click-modal="false" destroy-on-close>
      <el-form label-width="90px" size="small">
        <el-form-item label="申请部门">
          <el-input v-model="cgSgbm" placeholder="打印到单据标题及「申请部门/部门名称」栏" />
        </el-form-item>
        <el-form-item label="申购原因">
          <el-input v-model="cgSgyy" type="textarea" :rows="3"
            placeholder="打印到申请单「申购原因」栏，可为空" />
        </el-form-item>
        <el-form-item label="说明">
          <div class="cg-tip">
            单据明细取自当前结算单的结算明细,行数不限;<br>
            「下载」分别生成申请单 / 验收单 Excel;「打印」两张单分两页输出。
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="cgDlg = false">取消</el-button>
        <el-button type="primary" @click="downloadCg(1)">下载申请单</el-button>
        <el-button type="primary" @click="downloadCg(2)">下载验收单</el-button>
        <el-button type="primary" @click="openPrint">直接打印</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 附件管理 ==================== -->
    <el-dialog v-model="attDlg" title="附件管理" width="700px" class="std-dialog"
      :close-on-click-modal="false" destroy-on-close>
      <div class="cand-toolbar">
        <el-upload :show-file-list="false" :http-request="handleAttachUpload" multiple>
          <el-button type="primary" size="small">上传附件</el-button>
        </el-upload>
        <span class="toolbar-hint">每个文件不大于30MB</span>
      </div>
      <el-table v-loading="attLoading" :data="attList" border size="small" max-height="320"
        empty-text="暂无附件">
        <el-table-column type="index" label="序号" width="55" align="center" />
        <el-table-column prop="filename" label="文件名" min-width="260" show-overflow-tooltip />
        <el-table-column prop="filesizeStr" label="大小" width="90" align="center" />
        <el-table-column prop="uploadtime" label="上传时间" width="150" align="center" />
        <el-table-column label="操作" width="130" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="viewFile(row.downloadUrl)">
              查看
            </el-button>
            <el-button v-if="row.canDelete" link type="danger" size="small"
              @click="removeAttachment(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="attDlg = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.jsd-page {
  box-sizing: border-box;
  height: calc(100vh - 94px);
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow: hidden;
}
.filter-card { flex: 0 0 auto; }
.filter-card :deep(.el-card__body) { padding: 8px 12px; }
.filter-title { font-size: 15px; font-weight: 600; margin-bottom: 6px; }
.filter-form :deep(.el-form-item) { margin-bottom: 0; margin-right: 10px; }
.toolbar {
  display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-top: 4px;
}
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.table-card { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
.table-card :deep(.el-card__body) {
  padding: 6px 8px; flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column;
}
.jsd-table-wrap { flex: 1 1 auto; min-height: 0; overflow: hidden; }
.pager { flex: 0 0 auto; display: flex; justify-content: flex-end; margin-top: 4px; }
.detail-card { flex: 0 0 286px; min-height: 0; display: flex; flex-direction: column; }
.detail-card :deep(.el-card__header) { padding: 6px 12px; }
.detail-card :deep(.el-card__body) {
  padding: 6px 8px; flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column;
}
.jsd-detail-wrap { flex: 1 1 auto; min-height: 0; overflow: hidden; }
.jsd-page :deep(.el-table--small .el-table__cell) { padding: 2px 0; }
.jsd-page :deep(.el-table .cell) { line-height: 20px; padding: 0 4px; }
.jsd-page :deep(.el-table__header-wrapper th) { padding: 3px 0; }
.text-muted { color: #909399; }
.cand-toolbar {
  display: flex; align-items: center; gap: 10px; margin-bottom: 8px;
}
.cand-total { margin-left: auto; font-size: 14px; color: #1c1e54; }
.cand-total b { color: #533afd; font-size: 16px; }
.cand-pager { margin-top: 8px; }
.cg-tip { font-size: 12px; color: #64748d; line-height: 1.7; }
@media (max-height: 760px) {
  .jsd-page { gap: 5px; }
  .detail-card { flex-basis: 230px; }
  .filter-title { margin-bottom: 4px; }
}
</style>
