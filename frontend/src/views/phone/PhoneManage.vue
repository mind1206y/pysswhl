<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  batchAddPhones, batchDeletePhones, batchUpdateDept, batchUpdateLiyou,
  batchUpdateStatus, createHuishou, deleteHuishou, deletePhoneAttachment,
  exportPhones, getAttachmentToken, getHuishouList, getPhoneAttachments,
  getPhoneDicts, getPhoneHistory, getPhoneYears,
  listPhones, lookupPhoneDetail, lookupPhones, savePhoneRemark, scrapConfirm,
  updatePhoneInfo, uploadPhoneAttachment,
} from '@/api/phone'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const canManage = computed(() => auth.hasPerm('phone:manage'))
const canHuishou = computed(() => auth.hasPerm('phone:huishou'))

const dicts = reactive({
  departments: [], status: [], yongtu: [], liyou: [],
})
const years = ref([])

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(25)
const selected = ref([])
const filters = reactive({ keyword: '', bmid: null, years: [] })
const activeStatus = ref(['正常使用', '待领用'])

const showConfirmCols = computed(
  () => canManage.value && activeStatus.value.includes('已回收'),
)

function onSelectionChange(v) {
  selected.value = v
}

function toggleStatus(zt) {
  const idx = activeStatus.value.indexOf(zt)
  if (idx >= 0) activeStatus.value.splice(idx, 1)
  else activeStatus.value.push(zt)
  search()
}

function buildParams(withPage = true) {
  const p = {}
  if (withPage) {
    p.page = page.value
    p.size = size.value
  }
  if (filters.keyword) p.keyword = filters.keyword
  if (filters.bmid) p.bmid = filters.bmid
  if (filters.years.length) p.rq = filters.years.join(',')
  p.zts = activeStatus.value.join(',')
  return p
}

async function load() {
  loading.value = true
  try {
    const data = await listPhones(buildParams())
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
  Object.assign(filters, { keyword: '', bmid: null, years: [] })
  activeStatus.value = ['正常使用', '待领用']
  search()
}

function day(v) {
  return v ? String(v).slice(0, 10) : ''
}

function statusType(zt) {
  if (zt === '正常使用') return 'success'
  if (zt === '待领用') return 'warning'
  if (zt === '确认报废') return 'danger'
  return 'info'
}

async function loadDicts() {
  const [d, y] = await Promise.all([getPhoneDicts(), getPhoneYears()])
  Object.assign(dicts, d)
  years.value = y
}

onMounted(async () => {
  await loadDicts()
  load()
})

// ===== 批量添加 =====
const addVisible = ref(false)
const addFormRef = ref()
const today = () => {
  const d = new Date()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}
const blankAdd = () => ({
  start_num: null, end_num: null, qiyongdate: today(),
  pinpai: '', guige: '', jiage: null, bmid: null, bz: '',
})
const addForm = reactive(blankAdd())
const addRules = {
  start_num: [{ required: true, message: '请输入起始编号', trigger: 'blur' }],
  end_num: [{ required: true, message: '请输入结束编号', trigger: 'blur' }],
  qiyongdate: [{ required: true, message: '请选择启用日期', trigger: 'change' }],
  pinpai: [{ required: true, message: '请输入品牌', trigger: 'blur' }],
}
const addCount = computed(() => {
  const s = Number(addForm.start_num)
  const e = Number(addForm.end_num)
  if (!Number.isFinite(s) || !Number.isFinite(e)) return 0
  return Math.abs(e - s) + 1
})

function openAdd() {
  Object.assign(addForm, blankAdd())
  addVisible.value = true
}

async function submitAdd() {
  await addFormRef.value.validate()
  const res = await batchAddPhones({
    ...addForm,
    start_num: Number(addForm.start_num),
    end_num: Number(addForm.end_num),
  })
  ElMessage.success(`成功添加 ${res.count} 台手机`)
  addVisible.value = false
  load()
}

// ===== 批量修改部门 =====
const deptVisible = ref(false)
const deptForm = reactive({ new_dept_id: null })
function openBatchDept() {
  if (!selected.value.length) {
    ElMessage.warning('请先选择要修改的记录')
    return
  }
  deptForm.new_dept_id = null
  deptVisible.value = true
}
async function submitBatchDept() {
  if (!deptForm.new_dept_id) {
    ElMessage.warning('请选择新部门')
    return
  }
  const res = await batchUpdateDept({
    ids: selected.value.map((r) => r.id),
    new_dept_id: deptForm.new_dept_id,
  })
  ElMessage.success(`成功更新 ${res.count} 条记录`)
  deptVisible.value = false
  load()
}

// ===== 批量更新状态 =====
const statusVisible = ref(false)
const statusForm = reactive({ status: '' })
const statusOptions = computed(() => {
  const act = activeStatus.value
  const scrapView = (act.includes('确认报废') || act.includes('已回收'))
    && !act.includes('正常使用') && !act.includes('待领用')
  if (scrapView) {
    const opts = ['正常使用']
    if (canHuishou.value) opts.push('已回收')
    return opts
  }
  return ['正常使用', '待领用', '确认报废']
})
function openBatchStatus() {
  if (!selected.value.length) {
    ElMessage.warning('请先选择要更新的记录')
    return
  }
  statusForm.status = ''
  statusVisible.value = true
}
async function submitBatchStatus() {
  if (!statusForm.status) {
    ElMessage.warning('请选择状态')
    return
  }
  await batchUpdateStatus({
    ids: selected.value.map((r) => r.id),
    status: statusForm.status,
  })
  ElMessage.success('状态更新成功')
  statusVisible.value = false
  load()
}

// ===== 批量更新购置原因 =====
const liyouVisible = ref(false)
const liyouForm = reactive({ liyou: '' })
function openLiyou() {
  if (!selected.value.length) {
    ElMessage.warning('请先选择要更新的记录')
    return
  }
  liyouForm.liyou = ''
  liyouVisible.value = true
}
async function submitLiyou() {
  if (!liyouForm.liyou) {
    ElMessage.warning('请选择购置原因')
    return
  }
  await batchUpdateLiyou({
    ids: selected.value.map((r) => r.id),
    liyou: liyouForm.liyou,
  })
  ElMessage.success('购置原因更新成功')
  liyouVisible.value = false
  load()
}

// ===== 批量删除 / 确认报废 =====
async function doBatchDelete() {
  if (!selected.value.length) {
    ElMessage.warning('请先选择要删除的记录')
    return
  }
  await ElMessageBox.confirm(`确定删除选中的 ${selected.value.length} 条记录？`, '提示', {
    type: 'warning',
  })
  const res = await batchDeletePhones({ ids: selected.value.map((r) => r.id) })
  ElMessage.success(`已删除 ${res.count} 条`)
  selected.value = []
  load()
}

async function doScrapConfirm() {
  if (!selected.value.length) {
    ElMessage.warning('请先选择要确认报废的记录')
    return
  }
  await ElMessageBox.confirm(`确定将选中的 ${selected.value.length} 条记录标记为确认报废？`, '提示', {
    type: 'warning',
  })
  for (const row of selected.value) await scrapConfirm(row.id)
  ElMessage.success('已确认报废')
  load()
}

async function doExport() {
  await exportPhones(buildParams(false))
  ElMessage.success('已导出')
}

// ===== 编辑领用信息 =====
const editVisible = ref(false)
const editFormRef = ref()
const editingId = ref(null)
const editForm = reactive({ shiyongren: '', haoma: '', yongtu: '', bz: '' })
const editRules = {
  shiyongren: [{ required: true, message: '请输入使用人', trigger: 'blur' }],
}
const phoneOptions = ref([])
const phoneDetail = ref(null)

async function remotePhones(q) {
  const list = await lookupPhones(q || '')
  phoneOptions.value = list
}
async function onPhoneChange(value) {
  if (!value) {
    phoneDetail.value = null
    return
  }
  try {
    phoneDetail.value = await lookupPhoneDetail(value)
  } catch {
    phoneDetail.value = null
  }
}
async function openEdit(row) {
  editingId.value = row.id
  Object.assign(editForm, {
    shiyongren: row.shiyongren || '',
    haoma: row.haoma || '',
    yongtu: row.yongtu || '',
    bz: row.bz || '',
  })
  phoneDetail.value = null
  phoneOptions.value = row.haoma ? [{ value: row.haoma, text: row.haoma }] : []
  editVisible.value = true
  if (row.haoma) onPhoneChange(row.haoma)
}
async function submitEdit() {
  await editFormRef.value.validate()
  await updatePhoneInfo(editingId.value, { ...editForm })
  ElMessage.success('手机信息已更新')
  editVisible.value = false
  load()
}

// ===== 备注编辑 =====
const remarkVisible = ref(false)
const remarkForm = reactive({ id: null, remark: '' })
function openRemark(row) {
  remarkForm.id = row.id
  remarkForm.remark = row.bz || ''
  remarkVisible.value = true
}
async function submitRemark() {
  await savePhoneRemark(remarkForm.id, remarkForm.remark)
  ElMessage.success('备注已保存')
  remarkVisible.value = false
  load()
}

// ===== 历史 =====
const historyVisible = ref(false)
const historyTitle = ref('')
const historyRows = ref([])
async function openHistory(row) {
  historyTitle.value = `字段变更记录 - ${row.bh || ''}`
  historyRows.value = await getPhoneHistory(row.id)
  historyVisible.value = true
}

// ===== 号码悬浮卡 =====
const phoneNotesLoading = reactive({})
const phoneNotes = reactive({})
async function loadPhoneNote(haoma) {
  if (!haoma || phoneNotes[haoma] || phoneNotesLoading[haoma]) return
  phoneNotesLoading[haoma] = true
  try {
    phoneNotes[haoma] = await lookupPhoneDetail(haoma)
  } finally {
    phoneNotesLoading[haoma] = false
  }
}
function noteRows(note) {
  if (!note) return []
  return [
    ['号码', note.kahao],
    ['使用人', note.shiyongren],
    ['用途', note.yongtu],
    ['地点', note.didian],
    ['登记日期', note.dengjiriqi],
    ['状态', note.zt],
    ['所属部门', note.suoshubumen],
    ['APN', note.apn],
    ['运营商', note.yunyingshang],
    ['套餐', note.taocan],
    ['管理人', note.guanliren],
  ].filter(([, v]) => v)
}

// ===== 附件 =====
const attVisible = ref(false)
const attRecord = ref(null)
const attRows = ref([])
const attLoading = ref(false)
const attInput = ref()
const previewVisible = ref(false)
const previewUrl = ref('')

async function loadAttachments() {
  if (!attRecord.value) return
  attLoading.value = true
  try {
    const data = await getPhoneAttachments(attRecord.value.id)
    attRows.value = data.items
  } finally {
    attLoading.value = false
  }
}
function openAttachments(row) {
  attRecord.value = row
  attRows.value = []
  attVisible.value = true
  loadAttachments()
}
async function onAttFiles(e) {
  const files = Array.from(e.target.files || [])
  e.target.value = ''
  for (const file of files) {
    if (file.size > 30 * 1024 * 1024) {
      ElMessage.error(`${file.name} 超过30MB`)
      continue
    }
    const fd = new FormData()
    fd.append('file', file)
    try {
      await uploadPhoneAttachment(attRecord.value.id, fd)
    } catch {
      // 错误提示由 request 拦截器统一处理
    }
  }
  await loadAttachments()
  load()
}
async function attachmentUrl(id) {
  const data = await getAttachmentToken(id)
  return data.url
}
async function downloadAttachment(row) {
  const url = await attachmentUrl(row.id)
  const a = document.createElement('a')
  a.href = url
  a.download = row.file_name
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}
async function previewAttachment(row) {
  previewUrl.value = await attachmentUrl(row.id)
  previewVisible.value = true
}
async function removeAttachment(row) {
  await ElMessageBox.confirm(`确定删除附件 ${row.file_name}？`, '提示', { type: 'warning' })
  await deletePhoneAttachment(row.id)
  ElMessage.success('已删除')
  await loadAttachments()
  load()
}

// ===== 回收登记 =====
const hsVisible = ref(false)
const hsRows = ref([])
const hsTotal = ref(0)
const hsPage = ref(1)
const hsSize = ref(10)
const hsLoading = ref(false)
const hsForm = reactive({
  huishoudate: today(), bmid: null, huishouren: '', shuliang: null, shuoming: '',
})
async function loadHuishou() {
  hsLoading.value = true
  try {
    const data = await getHuishouList({ page: hsPage.value, size: hsSize.value })
    hsRows.value = data.items
    hsTotal.value = data.total
  } finally {
    hsLoading.value = false
  }
}
function openHuishou() {
  Object.assign(hsForm, {
    huishoudate: today(), bmid: null, huishouren: '', shuliang: null, shuoming: '',
  })
  hsPage.value = 1
  hsVisible.value = true
  loadHuishou()
}
async function submitHuishou() {
  if (!hsForm.huishoudate) { ElMessage.warning('请选择回收日期'); return }
  if (!hsForm.huishouren) { ElMessage.warning('请填写回收人'); return }
  if (!hsForm.shuliang || hsForm.shuliang <= 0) { ElMessage.warning('请填写数量'); return }
  await createHuishou({ ...hsForm })
  ElMessage.success('回收记录已登记')
  Object.assign(hsForm, {
    huishoudate: today(), bmid: null, huishouren: '', shuliang: null, shuoming: '',
  })
  loadHuishou()
}
async function removeHuishou(row) {
  await ElMessageBox.confirm('确定删除该条回收记录？', '提示', { type: 'warning' })
  await deleteHuishou(row.id)
  ElMessage.success('已删除')
  loadHuishou()
}

// ===== 打印签收单 =====
function printReceipt(row) {
  window.open(`/phone/print?id=${row.id}`, '_blank')
}
</script>

<template>
  <div class="phone-page">
    <el-card shadow="never" class="filter-card">
      <div class="filter-title">手机管理</div>
      <el-form inline class="filter-form">
        <el-form-item label="模糊查询">
          <el-input v-model="filters.keyword" placeholder="使用人/号码/编号/用途/品牌/备注"
            clearable style="width: 260px" @keyup.enter="search" />
        </el-form-item>
        <el-form-item label="部门">
          <el-select v-model="filters.bmid" placeholder="选择部门" clearable filterable
            style="width: 160px">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="年度">
          <el-select v-model="filters.years" multiple collapse-tags placeholder="选择年度"
            clearable style="width: 190px">
            <el-option v-for="y in years" :key="y" :label="`${y}年`" :value="String(y)" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <div class="status-seg">
            <span v-for="s in ['正常使用', '待领用', '确认报废', '已回收']" :key="s"
              class="status-btn" :class="{ active: activeStatus.includes(s) }"
              :data-zt="s" @click="toggleStatus(s)">{{ s }}</span>
          </div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <div class="toolbar">
      <el-button type="primary" size="small" @click="openAdd">批量添加</el-button>
      <el-button size="small" @click="openBatchDept">批量修改部门</el-button>
      <el-button size="small" @click="openBatchStatus">批量更新状态</el-button>
      <el-button size="small" @click="openLiyou">批量更新购置原因</el-button>
      <el-button size="small" @click="doExport">导出记录</el-button>
      <el-button size="small" @click="openHuishou">回收登记</el-button>
      <el-button v-if="canManage" size="small" type="danger" @click="doBatchDelete">
        批量删除
      </el-button>
      <el-button v-if="showConfirmCols" size="small" type="warning" @click="doScrapConfirm">
        确认报废
      </el-button>
      <span class="toolbar-hint">共 {{ total }} 台 · 双击行编辑领用信息 · 点击号码查看卡信息</span>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe size="small"
      height="calc(100vh - 330px)" highlight-current-row row-key="id"
      @selection-change="onSelectionChange" @row-dblclick="openEdit">
      <el-table-column type="selection" width="42" align="center" fixed="left" />
      <el-table-column label="签收单" width="70" align="center" fixed="left">
        <template #default="{ row }">
          <el-button link type="primary" @click="printReceipt(row)">打印</el-button>
        </template>
      </el-table-column>
      <el-table-column label="附件" width="76" align="center">
        <template #default="{ row }">
          <el-button link type="primary" @click="openAttachments(row)">
            附件<span v-if="row.att_count">({{ row.att_count }})</span>
          </el-button>
        </template>
      </el-table-column>
      <el-table-column label="历史" width="58" align="center">
        <template #default="{ row }">
          <el-button link type="primary" @click="openHistory(row)">历史</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="bm" label="部门" width="100" show-overflow-tooltip />
      <el-table-column prop="bh" label="手机编号" width="88" align="center" />
      <el-table-column prop="liyou" label="购置原因" width="82" align="center" />
      <el-table-column label="启用日期" width="98" align="center">
        <template #default="{ row }">{{ day(row.qiyongdate) }}</template>
      </el-table-column>
      <el-table-column prop="pinpai" label="品牌" width="70" align="center" />
      <el-table-column prop="guige" label="规格" width="150" show-overflow-tooltip />
      <el-table-column label="状态" width="88" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.zt" :type="statusType(row.zt)" size="small">{{ row.zt }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="价格" width="70" align="right">
        <template #default="{ row }">{{ row.jiage ?? '' }}</template>
      </el-table-column>
      <el-table-column label="备注" min-width="130" show-overflow-tooltip>
        <template #default="{ row }">
          <span>{{ row.bz }}</span>
          <el-button link type="primary" size="small" class="remark-btn" @click="openRemark(row)">
            编辑
          </el-button>
        </template>
      </el-table-column>
      <el-table-column prop="djuser" label="登记人" width="70" align="center" />
      <el-table-column label="登记日期" width="98" align="center">
        <template #default="{ row }">{{ day(row.djtime) }}</template>
      </el-table-column>
      <el-table-column prop="yongtu" label="用途" width="80" align="center" />
      <el-table-column prop="shiyongren" label="使用人" width="80" align="center" />
      <el-table-column label="号码" width="118" align="center">
        <template #default="{ row }">
          <el-popover v-if="row.haoma" placement="bottom" width="280" trigger="hover"
            @show="loadPhoneNote(row.haoma)">
            <template #reference>
              <span class="phone-link">{{ row.haoma }}</span>
            </template>
            <div class="phone-note">
              <div v-if="phoneNotesLoading[row.haoma]">加载中...</div>
              <template v-else-if="phoneNotes[row.haoma]">
                <div v-for="[label, value] in noteRows(phoneNotes[row.haoma])" :key="label"
                  class="note-row">
                  <span class="note-label">{{ label }}：</span>
                  <span>{{ value }}</span>
                </div>
              </template>
              <div v-else>未找到该号码信息</div>
            </div>
          </el-popover>
        </template>
      </el-table-column>
      <el-table-column prop="caozuo" label="编辑人" width="70" align="center" />
      <el-table-column label="编辑日期" width="98" align="center">
        <template #default="{ row }">{{ day(row.caozuotime) }}</template>
      </el-table-column>
      <el-table-column v-if="showConfirmCols" prop="querenuser" label="确认报废"
        width="82" align="center" />
      <el-table-column v-if="showConfirmCols" label="确认日期" width="98" align="center">
        <template #default="{ row }">{{ day(row.querendate) }}</template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[25, 50, 100]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>

    <!-- 批量添加 -->
    <el-dialog v-model="addVisible" title="批量添加手机" width="520px">
      <el-form ref="addFormRef" :model="addForm" :rules="addRules" label-width="90px">
        <el-form-item label="编号范围" prop="start_num">
          <div class="range-box">
            <span class="range-prefix">PDA</span>
            <el-input-number v-model="addForm.start_num" :min="1" :precision="0"
              controls-position="right" style="width: 130px" />
            <span>至</span>
            <span class="range-prefix">PDA</span>
            <el-input-number v-model="addForm.end_num" :min="1" :precision="0"
              controls-position="right" style="width: 130px" />
          </div>
          <div class="tip" v-if="addCount">
            将生成 <b>{{ addCount }}</b> 台设备：PDA{{ Math.min(Number(addForm.start_num), Number(addForm.end_num)) }}
            ~ PDA{{ Math.max(Number(addForm.start_num), Number(addForm.end_num)) }}
          </div>
        </el-form-item>
        <el-form-item label="启用日期" prop="qiyongdate">
          <el-date-picker v-model="addForm.qiyongdate" type="date" value-format="YYYY-MM-DD"
            style="width: 100%" />
        </el-form-item>
        <el-form-item label="品牌" prop="pinpai">
          <el-input v-model="addForm.pinpai" />
        </el-form-item>
        <el-form-item label="规格">
          <el-input v-model="addForm.guige" />
        </el-form-item>
        <el-form-item label="价格">
          <el-input-number v-model="addForm.jiage" :precision="2" :min="0"
            controls-position="right" style="width: 100%" />
        </el-form-item>
        <el-form-item label="部门">
          <el-select v-model="addForm.bmid" clearable filterable placeholder="选择部门"
            style="width: 100%">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="addForm.bz" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button type="primary" @click="submitAdd">保存</el-button>
      </template>
    </el-dialog>

    <!-- 批量修改部门 -->
    <el-dialog v-model="deptVisible" title="批量修改部门" width="420px">
      <el-form label-width="90px">
        <el-form-item label="新部门" required>
          <el-select v-model="deptForm.new_dept_id" filterable placeholder="选择新部门"
            style="width: 100%">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="tip">将修改 {{ selected.length }} 条记录的部门</div>
      <template #footer>
        <el-button @click="deptVisible = false">取消</el-button>
        <el-button type="primary" @click="submitBatchDept">保存</el-button>
      </template>
    </el-dialog>

    <!-- 批量更新状态 -->
    <el-dialog v-model="statusVisible" title="批量更新状态" width="380px">
      <el-form label-width="90px">
        <el-form-item label="新状态" required>
          <el-select v-model="statusForm.status" placeholder="请选择状态" style="width: 100%">
            <el-option v-for="s in statusOptions" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="tip">将更新 {{ selected.length }} 条记录</div>
      <template #footer>
        <el-button @click="statusVisible = false">取消</el-button>
        <el-button type="primary" @click="submitBatchStatus">确定</el-button>
      </template>
    </el-dialog>

    <!-- 批量更新购置原因 -->
    <el-dialog v-model="liyouVisible" title="购置原因" width="360px">
      <el-form label-width="90px">
        <el-form-item label="购置原因" required>
          <el-select v-model="liyouForm.liyou" placeholder="请选择购置原因" style="width: 100%">
            <el-option v-for="l in dicts.liyou" :key="l" :label="l" :value="l" />
          </el-select>
        </el-form-item>
      </el-form>
      <div class="tip">将更新 {{ selected.length }} 条记录</div>
      <template #footer>
        <el-button @click="liyouVisible = false">取消</el-button>
        <el-button type="primary" @click="submitLiyou">确定</el-button>
      </template>
    </el-dialog>

    <!-- 编辑领用信息 -->
    <el-dialog v-model="editVisible" title="编辑手机信息" width="480px">
      <el-form ref="editFormRef" :model="editForm" :rules="editRules" label-width="80px">
        <el-form-item label="使用人" prop="shiyongren">
          <el-input v-model="editForm.shiyongren" placeholder="请输入使用人姓名" />
        </el-form-item>
        <el-form-item label="号码">
          <el-select v-model="editForm.haoma" filterable remote clearable
            :remote-method="remotePhones" placeholder="输入手机号（可模糊匹配）"
            style="width: 100%" @change="onPhoneChange" @focus="remotePhones('')">
            <el-option v-for="p in phoneOptions" :key="p.value" :label="p.text" :value="p.value" />
          </el-select>
          <div class="tip" v-if="phoneDetail && phoneDetail.shiyongren">
            使用人：{{ phoneDetail.shiyongren }}
          </div>
        </el-form-item>
        <el-form-item label="用途">
          <el-select v-model="editForm.yongtu" clearable placeholder="选择用途" style="width: 100%">
            <el-option v-for="y in dicts.yongtu" :key="y" :label="y" :value="y" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="editForm.bz" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 编辑备注 -->
    <el-dialog v-model="remarkVisible" title="编辑备注" width="440px">
      <el-input v-model="remarkForm.remark" type="textarea" :rows="5" />
      <template #footer>
        <el-button @click="remarkVisible = false">取消</el-button>
        <el-button type="primary" @click="submitRemark">保存</el-button>
      </template>
    </el-dialog>

    <!-- 字段变更历史 -->
    <el-dialog v-model="historyVisible" :title="historyTitle" width="760px">
      <el-table :data="historyRows" size="small" border max-height="440">
        <el-table-column prop="edit_time" label="时间" width="160" />
        <el-table-column prop="edit_user" label="操作人" width="100" align="center" />
        <el-table-column prop="field_name" label="字段" width="100" align="center" />
        <el-table-column label="变更内容" min-width="300">
          <template #default="{ row }">
            <span class="hist-old">{{ row.old_value || '(空)' }}</span>
            <span> → </span>
            <span class="hist-new">{{ row.new_value || '(空)' }}</span>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="historyVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 附件抽屉 -->
    <el-drawer v-model="attVisible" :title="`手机附件 - ${attRecord?.bh || ''}`" size="62%">
      <input ref="attInput" type="file" style="display: none" multiple
        accept=".pdf,.jpg,.jpeg,.png,.gif,.bmp" @change="onAttFiles" />
      <div class="att-upload">
        <el-button type="primary" size="small" @click="attInput.click()">选择文件</el-button>
        <span class="tip">支持 PDF、图片，单文件 ≤ 30MB</span>
      </div>
      <el-table v-loading="attLoading" :data="attRows" size="small" border>
        <el-table-column label="预览" width="90" align="center">
          <template #default="{ row }">
            <span v-if="row.is_image" class="att-file-icon" @click="previewAttachment(row)">
              图片
            </span>
            <span v-else class="att-file-icon" @click="downloadAttachment(row)">PDF</span>
          </template>
        </el-table-column>
        <el-table-column label="附件名称" min-width="220">
          <template #default="{ row }">
            <el-button link type="primary" @click="downloadAttachment(row)">
              {{ row.file_name }}
            </el-button>
          </template>
        </el-table-column>
        <el-table-column prop="file_size_str" label="大小" width="100" align="center" />
        <el-table-column prop="upload_time" label="上传时间" width="160" align="center" />
        <el-table-column prop="operator_name" label="上传人" width="90" align="center" />
        <el-table-column label="操作" width="80" align="center">
          <template #default="{ row }">
            <el-button v-if="row.can_delete" link type="danger"
              @click="removeAttachment(row)">删除</el-button>
            <span v-else class="muted">-</span>
          </template>
        </el-table-column>
      </el-table>
    </el-drawer>

    <!-- 图片预览 -->
    <el-dialog v-model="previewVisible" title="图片预览" width="860px">
      <div class="preview-box">
        <img :src="previewUrl" alt="附件预览" />
      </div>
    </el-dialog>

    <!-- 回收登记抽屉 -->
    <el-drawer v-model="hsVisible" title="回收登记" size="60%">
      <el-form :model="hsForm" label-width="110px" class="hs-form">
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="回收日期" required>
              <el-date-picker v-model="hsForm.huishoudate" type="date"
                value-format="YYYY-MM-DD" style="width: 100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="营业所">
              <el-select v-model="hsForm.bmid" clearable filterable placeholder="可选"
                style="width: 100%">
                <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name"
                  :value="d.id" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="回收人" required>
              <el-input v-model="hsForm.huishouren" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="数量" required>
              <el-input-number v-model="hsForm.shuliang" :min="1" :precision="0"
                controls-position="right" style="width: 100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="说明">
          <el-input v-model="hsForm.shuoming" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="submitHuishou">保存登记</el-button>
          <span class="tip">登记人/登记时间保存时自动记录</span>
        </el-form-item>
      </el-form>

      <div class="hs-title">回收记录</div>
      <el-table v-loading="hsLoading" :data="hsRows" size="small" border>
        <el-table-column label="日期" width="110" align="center">
          <template #default="{ row }">{{ day(row.huishoudate) }}</template>
        </el-table-column>
        <el-table-column prop="bm" label="营业所" width="130" show-overflow-tooltip />
        <el-table-column prop="huishouren" label="回收人" width="100" />
        <el-table-column prop="shuliang" label="数量" width="70" align="center" />
        <el-table-column prop="shuoming" label="说明" min-width="160" show-overflow-tooltip />
        <el-table-column prop="djuser" label="登记人" width="90" align="center" />
        <el-table-column label="登记日期" width="160" align="center">
          <template #default="{ row }">{{ row.djtime }}</template>
        </el-table-column>
        <el-table-column label="操作" width="80" align="center">
          <template #default="{ row }">
            <el-button v-if="row.can_delete" link type="danger"
              @click="removeHuishou(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <div class="pager">
        <el-pagination v-model:current-page="hsPage" v-model:page-size="hsSize"
          :total="hsTotal" :page-sizes="[10, 20, 50]" layout="total, sizes, prev, pager, next"
          @current-change="loadHuishou" @size-change="loadHuishou" />
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.phone-page { display: flex; flex-direction: column; gap: 10px; }
.filter-card :deep(.el-card__body) { padding: 10px 14px; }
.filter-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 10px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }
.status-seg { display: inline-flex; vertical-align: middle; }
.status-btn {
  display: inline-block; padding: 4px 12px; font-size: 13px; line-height: 20px;
  cursor: pointer; user-select: none; white-space: nowrap; color: #303133;
  background: #fff; border: 1px solid #dcdfe6; margin-left: -1px; transition: all .15s;
}
.status-btn:first-child { border-radius: 6px 0 0 6px; margin-left: 0; }
.status-btn:last-child { border-radius: 0 6px 6px 0; }
.status-btn:hover { color: #1c1e54; background: #f5f7fa; }
.status-btn.active { position: relative; z-index: 2; color: #fff; font-weight: 600; }
.status-btn.active[data-zt="正常使用"] { background: #67c23a; border-color: #529b2e; }
.status-btn.active[data-zt="待领用"] { background: #c9881f; border-color: #b0781a; }
.status-btn.active[data-zt="确认报废"] { background: #f56c6c; border-color: #d94a4a; }
.status-btn.active[data-zt="已回收"] { background: #909399; border-color: #73767a; }
.tip { color: #909399; font-size: 12px; margin-top: 4px; }
.range-box { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.range-prefix {
  background: #f5f7fa; padding: 0 8px; height: 32px; line-height: 32px;
  border: 1px solid #dcdfe6; border-radius: 4px; color: #606266;
}
.remark-btn { margin-left: 4px; }
.phone-link { color: #409eff; cursor: pointer; }
.phone-note { font-size: 13px; }
.note-row { display: flex; margin-bottom: 3px; }
.note-label { color: #909399; min-width: 70px; }
.hist-old { color: #a08652; }
.hist-new { color: #303133; font-weight: 600; }
.att-upload { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.att-thumb { width: 60px; height: 45px; border-radius: 3px; cursor: pointer; }
.att-file-icon {
  display: inline-block; width: 60px; height: 45px; line-height: 45px; text-align: center;
  background: #f5f7fa; border-radius: 3px; cursor: pointer; color: #606266; font-size: 12px;
}
.preview-box { display: flex; justify-content: center; align-items: center; }
.preview-box img { max-width: 100%; max-height: 70vh; }
.muted { color: #c0c4cc; }
.hs-form { margin-bottom: 6px; }
.hs-title { font-weight: 600; color: #303133; margin: 8px 0; }
</style>
