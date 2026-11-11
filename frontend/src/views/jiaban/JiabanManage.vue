<script setup>
/**
 * 维抢修加班 —— 照旧 Jiaban/Index.cshtml 1:1 复刻
 * 顶部: 标题 + 查询带(模糊/周期下拉/指定日期/部门类别多选/统计方式) + 合计显示
 * 中部: 8 个工具栏按钮 + 14 列主表(工单号可点开详情抽屉,双击行编辑)
 * 弹窗: 添加/编辑工单加班(人员多选、工单号带出、内容历史气泡、跨天自动算时长)
 *      加班人员管理、导出备注、右侧工单详情抽屉(含现场图片)、附件抽屉
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  addJiaban, addRenyuan, deleteAttachment, deleteJiaban, deleteRenyuan,
  exportByAddress, exportByName, exportForOvertime, exportSummary,
  getBmlbOptions, getExternalImages, getExternalWorkOrder, getJiabanGongdanInfo,
  listAttachments, listJiaban, listRenyuan, listRenyuanAll, updateJiaban, updateRenyuan,
  uploadAttachment,
} from '@/api/jiaban'

// ==================== 查询(周期口径照旧 computeDateRange) ====================
const PERIODS = [
  { value: 'month', text: '本月' },
  { value: 'quarter', text: '本季度' },
  { value: 'halfYear', text: '本半年' },
  { value: 'year', text: '本年' },
  { value: 'lastMonth', text: '上个月' },
  { value: 'lastQuarter', text: '上季度' },
  { value: 'lastYear', text: '上一年' },
  { value: 'all', text: '全部' },
  { value: 'custom', text: '指定日期' },
]
const query = reactive({
  mohu: '', periodType: 'month', startDate: '', endDate: '', bmlb: [], leiType: 'all',
})
const totals = reactive({ totalShijian: '0.00', totalZongshu: '0' })
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(25)
const loading = ref(false)
const selected = ref(null)
const tableWrap = ref(null)
const tableH = ref(400)
let tableObserver = null

function fmtDate(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function computeDateRange(type) {
  const now = new Date()
  const y = now.getFullYear()
  const m = now.getMonth()
  let startDate
  let endDate
  switch (type) {
    case 'month':
      startDate = new Date(y, m - 1, 21); endDate = new Date(y, m, 20); break
    case 'lastMonth':
      startDate = new Date(y, m - 2, 21); endDate = new Date(y, m - 1, 20); break
    case 'quarter': {
      const qStart = Math.floor(m / 3) * 3
      let lastQEnd = qStart - 1
      let lastYear = y
      if (lastQEnd < 0) { lastQEnd += 12; lastYear = y - 1 }
      startDate = new Date(lastYear, lastQEnd, 21); endDate = new Date(y, qStart + 2, 20)
      break
    }
    case 'lastQuarter': {
      const qStart = Math.floor(m / 3) * 3
      let startYear = y
      let endYear = y
      let startMonth = qStart - 4
      if (startMonth < 0) { startMonth += 12; startYear = y - 1 }
      let endMonth = qStart - 1
      if (endMonth < 0) { endMonth += 12; endYear = y - 1 }
      startDate = new Date(startYear, startMonth, 21); endDate = new Date(endYear, endMonth, 20)
      break
    }
    case 'halfYear':
      if (m < 6) { startDate = new Date(y - 1, 11, 21); endDate = new Date(y, 5, 20) }
      else { startDate = new Date(y, 5, 21); endDate = new Date(y, 11, 20) }
      break
    case 'year':
      startDate = new Date(y - 1, 11, 21); endDate = new Date(y, 11, 20); break
    case 'lastYear':
      startDate = new Date(y - 2, 11, 21); endDate = new Date(y - 1, 11, 20); break
    case 'all':
      return { startDate: null, endDate: null }
    case 'custom':
      if (!query.startDate || !query.endDate) {
        ElMessage.warning('请先选择完整的自定义日期范围')
        return null
      }
      return { startDate: query.startDate, endDate: query.endDate }
    default:
      return null
  }
  return { startDate: fmtDate(startDate), endDate: fmtDate(endDate) }
}

function currentRange() {
  const r = computeDateRange(query.periodType)
  if (!r) return null
  return { startDate: r.startDate || '', endDate: r.endDate || '' }
}

function buildParams() {
  const r = currentRange() || { startDate: '', endDate: '' }
  return {
    page: page.value, rows: pageSize.value,
    startDate: r.startDate, endDate: r.endDate,
    mohu: query.mohu.trim(),
    bmlb: query.bmlb.join(','),
    leiType: query.leiType || 'all',
  }
}

async function load() {
  loading.value = true
  try {
    const data = await listJiaban(buildParams())
    rows.value = data.rows || []
    total.value = data.total || 0
    totals.totalShijian = Number(data.totalShijian || 0).toFixed(2)
    totals.totalZongshu = data.totalZongshu ?? 0
  } finally {
    loading.value = false
  }
}

function reload(resetPage = true) {
  if (resetPage) page.value = 1
  load()
}

function doSearch() { reload() }
function onPeriodChange(v) {
  if (v !== 'custom') { query.startDate = ''; query.endDate = '' }
  reload()
}
function onCustomDateChange() {
  if (query.startDate && query.endDate) reload()
}
function onBmlbChange() { reload() }
function onLeiTypeChange() { reload() }
function onSizeChange(v) { pageSize.value = v; reload() }
function onPageChange(v) { page.value = v; load() }

async function loadOptions() {
  bmlbOptions.value = await getBmlbOptions()
}
const bmlbOptions = ref([])

// ==================== 关键字高亮(先转义,防存储型 XSS) ====================
const searchKey = ref('')
function escapeHtml(v) {
  return String(v ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]))
}
function highlight(text) {
  const raw = String(text ?? '')
  const keys = [searchKey.value].filter(Boolean)
  if (!keys.length) return escapeHtml(raw)
  const pattern = keys.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')
  const re = new RegExp(`(${pattern})`, 'gi')
  return raw.split(re).map((part) => (
    keys.some((k) => k.toLowerCase() === part.toLowerCase())
      ? `<span class="hl">${escapeHtml(part)}</span>` : escapeHtml(part)
  )).join('')
}
function leiText(v) {
  if (v === true) return '是'
  if (v === null || v === undefined) return '未定'
  return '否'
}

// ==================== 外部工单详情抽屉(照抄 gongdan/workorder) ====================
const woDrawer = ref(false)
const woInfo = reactive({ gongdanhao: '', message: '', loading: false, data: null, images: [] })
async function openWorkOrderDrawer(no) {
  Object.assign(woInfo, { gongdanhao: no || '', message: '', data: null, images: [] })
  woDrawer.value = true
  if (!no) { woInfo.message = '工单号为空'; return }
  woInfo.loading = true
  try {
    const res = await getExternalWorkOrder(no)
    if (res.success && res.data) {
      woInfo.data = res.data
      try {
        const imgRes = await getExternalImages(res.data.Id || no)
        if (imgRes.success) woInfo.images = imgRes.images || []
      } catch { /* 图片失败不影响信息展示 */ }
    } else {
      woInfo.message = res.message || '未获取到工单信息'
    }
  } catch {
    woInfo.message = '接口调用失败'
  } finally {
    woInfo.loading = false
  }
}

// ==================== 添加 / 编辑弹窗 ====================
const dialogVisible = ref(false)
const dialogMode = ref('add')
const saving = ref(false)
const form = reactive({
  id: null, nameids: [], gongdanNo: '', riqi: '', dizhi: '', neirong: '',
  kssj: '', jssj: '', shijian: null, beishu: 1.5, zongshu: null, lei: false,
  qzriqi: '',
})
const personOptions = ref([])
let lastAutoBeishuDate = ''

async function loadPersons() {
  personOptions.value = await listRenyuanAll()
}

function autoSetBeishu(dateStr) {
  if (!dateStr || dateStr === lastAutoBeishuDate) return
  lastAutoBeishuDate = dateStr
  const d = new Date(String(dateStr).replace(/-/g, '/'))
  if (isNaN(d.getTime())) return
  form.beishu = (d.getDay() === 0 || d.getDay() === 6) ? 2 : 1.5
  updateZongshu()
}

// 0900 → 09:00(照旧 fmtTimeInput,中文冒号也转)
function parseTime(v) {
  const s = String(v || '').trim().replace(/：/g, ':')
  const m = s.match(/^(\d{1,2}):(\d{1,2})$/) || s.match(/^(\d{1,2})(\d{2})$/)
  if (!m) return null
  const h = Number(m[1]); const mi = Number(m[2])
  if (h > 23 || mi > 59) return null
  return `${String(h).padStart(2, '0')}:${String(mi).padStart(2, '0')}`
}
function fmtTime(p) {
  const t = parseTime(form[p])
  if (t && t !== form[p]) form[p] = t
  autoCalcShijian()
}
function autoCalcShijian() {
  const ks = parseTime(form.kssj)
  const js = parseTime(form.jssj)
  if (!ks || !js) return
  const [kh, km] = ks.split(':').map(Number)
  const [jh, jm] = js.split(':').map(Number)
  let ksMin = kh * 60 + km
  let jsMin = jh * 60 + jm
  if (jsMin <= ksMin) jsMin += 24 * 60
  form.shijian = Number(((jsMin - ksMin) / 60).toFixed(2))
  updateZongshu()
}
function updateZongshu() {
  if (form.shijian > 0 && form.beishu > 0) {
    form.zongshu = Number((form.shijian * form.beishu).toFixed(2))
  } else {
    form.zongshu = null
  }
}
function onRiqiChange(v) { autoSetBeishu(v) }
function onBeishuChange() { updateZongshu() }

// 工单号失焦:外部工单带出 地址/日期/起止 + 查重 + 工单历史记录
const gdRecords = ref([])
async function onNoBlur() {
  const no = form.gongdanNo.trim()
  if (!no) {
    form.dizhi = ''; form.riqi = ''; form.qzriqi = ''; gdRecords.value = []
    lastAutoBeishuDate = ''
    form.beishu = 1.5
    return
  }
  const nameid = dialogMode.value === 'edit' ? form.nameids[0]
    : (form.nameids[0] || undefined)
  try {
    const res = await getJiabanGongdanInfo(no, nameid)
    if (!res.success) {
      ElMessage.warning(res.msg || '未找到工单信息')
      return
    }
    gdRecords.value = res.records || []
    form.dizhi = res.dizhi || ''
    const create = String(res.riqi || '').replace('T', ' ')
    if (/^\d{4}-\d{2}-\d{2}/.test(create)) {
      form.riqi = create.slice(0, 10)
      autoSetBeishu(form.riqi)
      const end = String(res.jsriqi || '').replace('T', ' ')
      if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(create) && /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(end)) {
        form.qzriqi = `${create.slice(11, 16)}-${end.slice(11, 16)}`
      }
    }
    if (dialogMode.value === 'add' && res.duplicate) {
      ElMessage.warning(res.duplicateMsg || '此工单号已为该人员录入')
    }
  } catch { /* 拦截器已提示 */ }
}

// 内容历史气泡(localStorage,先进先出 + 单条删除,与加班申请模块存储键互不干扰)
const NR_KEY = 'sswhl-jiaban-neirong-history'
const NR_MAX = 12
const nrHistory = ref([])
const nrPop = ref(false)
function nrLoad() {
  try {
    const arr = JSON.parse(localStorage.getItem(NR_KEY) || '[]')
    nrHistory.value = Array.isArray(arr) ? arr : []
  } catch { nrHistory.value = [] }
}
function nrPush(text) {
  const t = String(text || '').trim()
  if (!t) return
  nrLoad()
  const arr = nrHistory.value.filter((x) => x !== t)
  arr.unshift(t)
  if (arr.length > NR_MAX) arr.length = NR_MAX
  nrHistory.value = arr
  try { localStorage.setItem(NR_KEY, JSON.stringify(arr)) } catch { /* 忽略 */ }
}
function nrRemove(text) {
  nrLoad()
  nrHistory.value = nrHistory.value.filter((x) => x !== text)
  try { localStorage.setItem(NR_KEY, JSON.stringify(nrHistory.value)) } catch { /* 忽略 */ }
  ElMessage.success('已删除该历史项')
}
function nrPick(text) {
  form.neirong = text
  nrPop.value = false
}

function resetForm() {
  Object.assign(form, {
    id: null, nameids: [], gongdanNo: '', riqi: '', dizhi: '', neirong: '',
    kssj: '', jssj: '', shijian: null, beishu: 1.5, zongshu: null, lei: false,
    qzriqi: '',
  })
  gdRecords.value = []
  lastAutoBeishuDate = ''
  nrPop.value = false
}

function openAdd() {
  dialogMode.value = 'add'
  resetForm()
  dialogVisible.value = true
  loadPersons()
  nrLoad()
}
function openEdit(row) {
  if (!row) { ElMessage.warning('请先选择一条加班记录'); return }
  dialogMode.value = 'edit'
  lastAutoBeishuDate = String(row.riqi || '')
  resetForm()
  Object.assign(form, {
    id: row.ID,
    nameids: [row.nameid],
    gongdanNo: row.gongdanNo,
    riqi: row.riqi,
    dizhi: row.dizhi,
    neirong: row.neirong,
    shijian: row.shijian,
    beishu: row.beishu,
    zongshu: row.zongshu,
    lei: row.lei === true,
    qzriqi: '',
  })
  if (row.kjshijian) {
    const arr = String(row.kjshijian).split('-')
    form.kssj = arr[0] || ''
    form.jssj = arr[1] || ''
  }
  dialogVisible.value = true
  loadPersons()
  nrLoad()
  // 照旧:编辑打开时触发工单号带出,加载工单历史记录
  nextTick(() => { if (form.gongdanNo) onNoBlur() })
}

function validateForm() {
  if (!form.nameids.length) return '请选择人员'
  if (!form.gongdanNo.trim()) return '请填写工单号'
  if (!form.riqi) return '请选择日期'
  if (!String(form.dizhi || '').trim()) return '请填写地址'
  if (!String(form.neirong || '').trim()) return '请填写内容'
  if (!parseTime(form.kssj)) return '开始时间格式为 HH:mm（如 14:30）'
  if (!parseTime(form.jssj)) return '结束时间格式为 HH:mm（如 14:30）'
  if (form.shijian === null || form.shijian === '') return '请填写时长'
  return ''
}

async function submit() {
  const err = validateForm()
  if (err) { ElMessage.warning(err); return }
  saving.value = true
  try {
    const ks = parseTime(form.kssj)
    const js = parseTime(form.jssj)
    if (dialogMode.value === 'add') {
      const res = await addJiaban({
        nameids: form.nameids.join(','),
        gongdanNo: form.gongdanNo.trim(), riqi: form.riqi,
        dizhi: form.dizhi, neirong: form.neirong,
        kssj: ks, jssj: js,
        shijian: form.shijian, beishu: form.beishu,
        zongshu: form.zongshu, lei: form.lei,
      })
      nrPush(form.neirong)
      if (res.successCount > 0) {
        ElMessage.success(res.msg || '保存成功')
        if (res.errors?.length) {
          ElMessageBox.alert(res.errors.join('<br/>'), '部分失败', { type: 'warning', dangerouslyUseHTMLString: true })
        }
        resetForm()
        lastAutoBeishuDate = ''
        form.beishu = 1.5
      } else {
        ElMessageBox.alert(res.errors?.join('<br/>') || res.msg || '保存失败', '错误',
          { type: 'error', dangerouslyUseHTMLString: true })
      }
    } else {
      await updateJiaban({
        id: form.id, nameid: form.nameids[0],
        gongdanNo: form.gongdanNo.trim(), riqi: form.riqi,
        dizhi: form.dizhi, neirong: form.neirong,
        kssj: ks, jssj: js,
        shijian: form.shijian, beishu: form.beishu,
        zongshu: form.zongshu, lei: form.lei,
      })
      nrPush(form.neirong)
      ElMessage.success('更新成功')
      dialogVisible.value = false
    }
    reload(false)
  } finally {
    saving.value = false
  }
}

async function deleteRow() {
  if (!selected.value) { ElMessage.warning('请先选择一条加班记录'); return }
  try {
    await ElMessageBox.confirm('确定删除该加班记录吗？', '确认', { type: 'warning' })
    const res = await deleteJiaban(selected.value.ID)
    if (res.success === false) { ElMessage.error(res.msg || '删除失败'); return }
    ElMessage.success('删除成功')
    selected.value = null
    reload(false)
  } catch { /* 取消或拦截器已提示 */ }
}

// ==================== 导出 ====================
const exportDialogVisible = ref(false)
const exportMode = ref('excel') // excel | address
const exportRemark = ref('')
function openExportDialog(mode) {
  exportMode.value = mode
  exportRemark.value = ''
  exportDialogVisible.value = true
}
async function confirmExportDialog() {
  if (exportRemark.value.length > 200) {
    ElMessage.warning('备注不能超过200个字')
    return
  }
  const r = currentRange()
  if (!r) return
  const params = {
    ...r, mohu: query.mohu.trim(), bmlb: query.bmlb.join(','),
    leiType: query.leiType || 'all', remark: exportRemark.value,
  }
  exportDialogVisible.value = false
  if (exportMode.value === 'address') await exportByAddress(params)
  else await exportByName(params)
  ElMessage.success('导出完成')
}
async function doExportSummary() {
  const r = currentRange()
  if (!r) return
  await exportSummary({ ...r, mohu: query.mohu.trim(), bmlb: query.bmlb.join(','), leiType: query.leiType || 'all' })
  ElMessage.success('导出完成')
}
async function doExportForOvertime() {
  const r = currentRange()
  if (!r) return
  try {
    await ElMessageBox.confirm(
      '将按当前筛选条件导出Excel（格式匹配"加班申请管理→我的加班→批量导入"），'
      + '加班类别固定为"维抢修加班"。确认导出？', '确认', { type: 'info' })
  } catch { return }
  await exportForOvertime({ ...r, mohu: query.mohu.trim(), bmlb: query.bmlb.join(','), leiType: query.leiType || 'all' })
  ElMessage.success('导出完成')
}

// ==================== 加班人员管理弹窗 ====================
const renVisible = ref(false)
const renRows = ref([])
const renTotal = ref(0)
const renPage = ref(1)
const renPageSize = ref(10)
const renKeyword = ref('')
const renLoading = ref(false)
const renForm = reactive({ id: null, name: '', gonghao: '', bmlb: '', danjia: null })
const renSaving = ref(false)

async function loadRenyuan() {
  renLoading.value = true
  try {
    const data = await listRenyuan({
      search: renKeyword.value.trim(), page: renPage.value, rows: renPageSize.value,
    })
    renRows.value = data.rows || []
    renTotal.value = data.total || 0
  } finally {
    renLoading.value = false
  }
}
async function openRenyuan() {
  renKeyword.value = ''
  renPage.value = 1
  resetRenForm()
  renVisible.value = true
  await loadRenyuan()
}
function resetRenForm() {
  Object.assign(renForm, { id: null, name: '', gonghao: '', bmlb: '', danjia: null })
}
function renEdit(row) {
  Object.assign(renForm, {
    id: row.id, name: row.name, gonghao: row.gonghao,
    bmlb: row.bmlb, danjia: row.danjia,
  })
}
function renSearch() { renPage.value = 1; loadRenyuan() }
function renPageChange(v) { renPage.value = v; loadRenyuan() }
function renSizeChange(v) { renPageSize.value = v; renPage.value = 1; loadRenyuan() }
async function renSave() {
  if (!renForm.name.trim() || !renForm.bmlb.trim()) {
    ElMessage.warning('姓名和部门类别不能为空')
    return
  }
  renSaving.value = true
  try {
    if (renForm.id) {
      await updateRenyuan({ ...renForm, name: renForm.name.trim(), bmlb: renForm.bmlb.trim() })
      ElMessage.success('更新成功')
    } else {
      await addRenyuan({ ...renForm, name: renForm.name.trim(), bmlb: renForm.bmlb.trim() })
      ElMessage.success('添加成功')
    }
    resetRenForm()
    await loadRenyuan()
  } catch { /* 拦截器已提示(重名等) */ } finally {
    renSaving.value = false
  }
}
async function renDelete(row) {
  try {
    await ElMessageBox.confirm('确定要删除该人员吗？', '确认删除', { type: 'warning' })
    await deleteRenyuan(row.id)
    ElMessage.success('删除成功')
    if (renForm.id === row.id) resetRenForm()
    await loadRenyuan()
  } catch { /* 取消或拦截器已提示 */ }
}

// ==================== 附件抽屉 ====================
const attVisible = ref(false)
const attMonth = ref('')
const attRows = ref([])
const attTotal = ref(0)
const attPage = ref(1)
const attPageSize = ref(25)
const attLoading = ref(false)
const attQueue = ref([])
const attUploading = ref(false)
const attInput = ref(null)

async function loadAttachments() {
  attLoading.value = true
  try {
    const params = { page: attPage.value, rows: attPageSize.value }
    if (attMonth.value) {
      const [y, m] = attMonth.value.split('-').map(Number)
      params.year = y
      params.month = m
    }
    const data = await listAttachments(params)
    attRows.value = data.rows || []
    attTotal.value = data.total || 0
  } finally {
    attLoading.value = false
  }
}
function openAttachments() {
  attVisible.value = true
  attMonth.value = `${new Date().getFullYear()}-${String(new Date().getMonth() + 1).padStart(2, '0')}`
  attPage.value = 1
  loadAttachments()
}
function attMonthChange() { attPage.value = 1; loadAttachments() }
function attPageChange(v) { attPage.value = v; loadAttachments() }
function attSizeChange(v) { attPageSize.value = v; attPage.value = 1; loadAttachments() }

async function onAttFilesSelected(e) {
  const files = [...(e.target.files || [])]
  e.target.value = ''
  if (!files.length) return
  const maxSize = 50 * 1024 * 1024
  const ok = files.filter((f) => f.size <= maxSize)
  const oversize = files.filter((f) => f.size > maxSize)
  if (oversize.length) {
    ElMessage.warning(`以下文件超过50MB限制，已跳过：\n${oversize.map((f) => f.name).join('\n')}`)
  }
  if (!ok.length) return
  if (!attMonth.value) { ElMessage.warning('请先选择年月份'); return }
  const [y, m] = attMonth.value.split('-').map(Number)
  for (const f of ok) {
    const item = reactive({ name: f.name, size: f.size, pct: 0, status: 'uploading', err: '' })
    attQueue.value.push(item)
    try {
      await uploadAttachment(y, m, f, (pct) => { item.pct = pct })
      item.status = 'done'
    } catch (err) {
      item.status = 'fail'
      item.err = err?.response?.data?.detail || '上传失败'
    }
  }
  attUploading.value = false
  ElMessage.success('上传完成')
  await loadAttachments()
  setTimeout(() => { attQueue.value = [] }, 1500)
}
async function attDelete(row) {
  try {
    await ElMessageBox.confirm('确定删除该附件吗？', '确认', { type: 'warning' })
    const res = await deleteAttachment(row.id)
    if (res.success === false) { ElMessage.error(res.msg || '删除失败'); return }
    ElMessage.success('删除成功')
    await loadAttachments()
  } catch { /* 取消或拦截器已提示 */ }
}
function attDownload(row) {
  if (row.downloadUrl) window.open(row.downloadUrl, '_blank')
}

// ==================== 当月图片浏览窗(滚轮翻页) ====================
const IMG_RE = /\.(jpg|jpeg|png|gif|bmp)$/i
const viewerVisible = ref(false)
const viewerLoading = ref(false)
const viewerImages = ref([])
const viewerIndex = ref(0)
const viewerErr = ref(false)
const curImage = computed(() => viewerImages.value[viewerIndex.value] || null)

async function openImageViewer(row) {
  viewerVisible.value = true
  viewerLoading.value = true
  viewerErr.value = false
  try {
    // 拉取所选月份全部附件,筛出图片(1 页取 500 条足够)
    const params = { page: 1, rows: 500 }
    if (attMonth.value) {
      const [y, m] = attMonth.value.split('-').map(Number)
      params.year = y
      params.month = m
    }
    const data = await listAttachments(params)
    const imgs = (data.rows || []).filter((r) => IMG_RE.test(r.file_name || ''))
    viewerImages.value = imgs.map((r) => ({
      id: r.id,
      name: r.file_name,
      url: `${r.downloadUrl}&inline=1`,
    }))
    // 从点击的附件开始浏览
    const idx = viewerImages.value.findIndex((it) => it.id === row.id)
    viewerIndex.value = idx > 0 ? idx : 0
  } finally {
    viewerLoading.value = false
  }
}
function viewerStep(delta) {
  if (!viewerImages.value.length) return
  const next = viewerIndex.value + delta
  if (next < 0 || next >= viewerImages.value.length) return
  viewerIndex.value = next
  viewerErr.value = false
}
function onViewerWheel(e) {
  viewerStep(e.deltaY > 0 ? 1 : -1)
}
function onViewerKey(e) {
  if (e.key === 'Escape') viewerVisible.value = false
  else if (e.key === 'ArrowLeft') viewerStep(-1)
  else if (e.key === 'ArrowRight') viewerStep(1)
}
watch(viewerVisible, (v) => {
  if (v) window.addEventListener('keydown', onViewerKey)
  else window.removeEventListener('keydown', onViewerKey)
})
onBeforeUnmount(() => window.removeEventListener('keydown', onViewerKey))

// 附件名称点击:图片 → 浏览窗,PDF → 下载
function attClick(row) {
  if (IMG_RE.test(row.file_name || '')) openImageViewer(row)
  else attDownload(row)
}

// ==================== 视口自适应 ====================
const winWidth = ref(window.innerWidth)
const wide = computed(() => winWidth.value >= 1500)
function fitTable() {
  if (tableWrap.value) tableH.value = Math.max(180, tableWrap.value.clientHeight)
}
function onWindowResize() { winWidth.value = window.innerWidth; fitTable() }

onMounted(async () => {
  // 默认日期:上月21日 ~ 本月20日(照旧初始化,再由 periodType=month 覆盖)
  const now = new Date()
  query.startDate = fmtDate(new Date(now.getFullYear(), now.getMonth() - 1, 21))
  query.endDate = fmtDate(new Date(now.getFullYear(), now.getMonth(), 20))
  await loadOptions()
  await load()
  await nextTick()
  if (tableWrap.value) {
    tableObserver = new ResizeObserver(fitTable)
    tableObserver.observe(tableWrap.value)
  }
  window.addEventListener('resize', onWindowResize)
  fitTable()
})
onBeforeUnmount(() => {
  tableObserver?.disconnect()
  window.removeEventListener('resize', onWindowResize)
})
</script>

<template>
  <div class="jb-page">
    <div class="jb-banner">维抢修加班管理</div>

    <!-- ==================== 查询带 ==================== -->
    <div class="jb-search">
      <el-input v-model="query.mohu" size="default" clearable placeholder="模糊查询(姓名/工单号/地址)"
                class="jb-kw" @keyup.enter="doSearch" @clear="doSearch">
        <template #append>
          <el-button size="default" :icon="'Search'" @click="doSearch" />
        </template>
      </el-input>
      <el-select v-model="query.periodType" size="default" style="width: 110px"
                 @change="onPeriodChange">
        <el-option v-for="p in PERIODS" :key="p.value" :label="p.text" :value="p.value" />
      </el-select>
      <span v-if="query.periodType === 'custom'" class="jb-custom">
        <el-date-picker v-model="query.startDate" type="date" size="default"
                        value-format="YYYY-MM-DD" style="width: 130px"
                        @change="onCustomDateChange" />
        <span class="jb-label">至</span>
        <el-date-picker v-model="query.endDate" type="date" size="default"
                        value-format="YYYY-MM-DD" style="width: 130px"
                        @change="onCustomDateChange" />
      </span>
      <el-select v-model="query.bmlb" size="default" multiple collapse-tags
                 clearable placeholder="选择部门类别" style="width: 160px"
                 @change="onBmlbChange">
        <el-option v-for="o in bmlbOptions" :key="o.id" :label="o.text" :value="o.id" />
      </el-select>
      <el-select v-model="query.leiType" size="default" style="width: 130px"
                 @change="onLeiTypeChange">
        <el-option label="全部" value="all" />
        <el-option label="以地址统计" value="address" />
        <el-option label="非地址统计" value="nonaddress" />
      </el-select>
      <span class="jb-summary">
        <b>{{ totals.totalShijian }}</b> 小时 (总时长)&nbsp;&nbsp;
        <b>{{ totals.totalZongshu }}</b> (总时间数)
      </span>
    </div>

    <!-- ==================== 工具栏 ==================== -->
    <div class="jb-toolbar">
      <el-button size="default" type="primary" :icon="'Plus'" @click="openAdd">添加</el-button>
      <el-button size="default" :icon="'Delete'" @click="deleteRow">删除</el-button>
      <el-button size="default" :icon="'User'" @click="openRenyuan">加班人员</el-button>
      <el-button size="default" :icon="'Download'" @click="openExportDialog('excel')">导出 Excel</el-button>
      <el-button size="default" :icon="'Download'" @click="doExportSummary">导出汇总Excel</el-button>
      <el-button size="default" :icon="'Download'" @click="openExportDialog('address')">按地址导出</el-button>
      <el-button size="default" :icon="'Download'" @click="doExportForOvertime">导出给加班申请</el-button>
      <el-button size="default" :icon="'FolderOpened'" @click="openAttachments">附件</el-button>
      <span class="jb-tip">双击行可编辑；点击工单号查看工单详情</span>
    </div>

    <!-- ==================== 主表 ==================== -->
    <div ref="tableWrap" class="jb-table-wrap">
      <el-table v-loading="loading" :data="rows" size="default" border stripe :height="tableH"
                highlight-current-row row-key="ID"
                @row-click="(r) => (selected = r)" @row-dblclick="openEdit">
        <el-table-column prop="name" label="姓名" width="90" align="center" />
        <el-table-column prop="bm" label="部门类别" min-width="130" align="center"
                         show-overflow-tooltip />
        <el-table-column prop="riqi" label="工单日期" width="100" align="center" />
        <el-table-column prop="gongdanNo" label="工单号" width="110" align="center">
          <template #default="{ row }">
            <a v-if="row.gongdanNo" class="jb-link"
               @click.stop="openWorkOrderDrawer(row.gongdanNo)">{{ row.gongdanNo }}</a>
          </template>
        </el-table-column>
        <el-table-column prop="dizhi" label="地址" min-width="180" show-overflow-tooltip>
          <template #default="{ row }"><span v-html="highlight(row.dizhi)" /></template>
        </el-table-column>
        <el-table-column prop="neirong" label="工作内容" min-width="140" show-overflow-tooltip>
          <template #default="{ row }"><span v-html="highlight(row.neirong)" /></template>
        </el-table-column>
        <el-table-column prop="kjshijian" label="起止至竣工时间" width="130" align="center" />
        <el-table-column prop="shijian" label="加班时长" width="90" align="center" />
        <el-table-column prop="beishu" label="倍数" width="70" align="center" />
        <el-table-column prop="zongshu" label="加班时间总数" width="110" align="center" />
        <el-table-column label="是否以地址统计" width="120" align="center">
          <template #default="{ row }">{{ leiText(row.lei) }}</template>
        </el-table-column>
        <el-table-column prop="username" label="创建人" width="90" align="center" />
        <el-table-column v-if="wide" prop="createtime" label="操作日期" width="150" align="center" />
        <el-table-column prop="ID" label="ID号" width="70" align="center" />
      </el-table>
    </div>
    <div class="jb-pager">
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize" small background
                     layout="total, sizes, prev, pager, next, jumper" :total="total"
                     :page-sizes="[25, 50, 100]" @current-change="onPageChange"
                     @size-change="onSizeChange" />
    </div>

    <!-- ==================== 添加 / 编辑弹窗 ==================== -->
    <el-dialog v-model="dialogVisible" class="std-dialog"
               :title="dialogMode === 'add' ? '添加工单加班记录' : '编辑加班记录'"
               width="min(980px, calc(100vw - 40px))" top="2vh"
               :close-on-click-modal="false" append-to-body destroy-on-close @closed="resetForm">
      <el-form label-width="72px" class="jb-form">
        <div class="jb-grid">
          <el-form-item label="人员:" required>
            <div class="jb-person">
              <el-select v-model="form.nameids" :multiple="dialogMode === 'add'"
                         filterable collapse-tags :collapse-tags-tooltip="true"
                         placeholder="选择加班人员" style="flex: 1" @visible-change="(v) => { if (v) loadPersons() }">
                <el-option v-for="p in personOptions" :key="p.id"
                           :label="dialogMode === 'add' ? p.name : `${p.name}（${p.bmlb}）`"
                           :value="p.id" />
              </el-select>
              <span class="jb-name-count">已选 {{ form.nameids.length }} 个</span>
            </div>
          </el-form-item>
          <el-form-item label="工单号:" required>
            <el-input v-model="form.gongdanNo" clearable @blur="onNoBlur"
                      @keyup.enter="$event.target.blur()" />
          </el-form-item>

          <el-form-item label="日期:" required>
            <el-date-picker v-model="form.riqi" type="date" value-format="YYYY-MM-DD"
                            style="width: 100%" @change="onRiqiChange" />
          </el-form-item>
          <el-form-item label="地址:" required>
            <el-input v-model="form.dizhi" clearable />
          </el-form-item>

          <el-form-item label="内容:" required>
            <el-popover v-model:visible="nrPop" placement="bottom-start" :width="360"
                        trigger="click" popper-class="jb-nr-popper">
              <template #reference>
                <el-input v-model="form.neirong" clearable
                          placeholder="点此可选历史内容" @click="nrPop = !nrPop" />
              </template>
              <div class="jb-nr">
                <div class="jb-nr-title">
                  历史工作内容
                  <span v-if="nrHistory.length" class="jb-nr-count">{{ nrHistory.length }}/{{ NR_MAX }}</span>
                </div>
                <div class="jb-nr-tags">
                  <template v-if="nrHistory.length">
                    <span v-for="t in nrHistory" :key="t" class="jb-nr-tag"
                          :title="t" @click="nrPick(t)">
                      <span class="jb-nr-tag-txt">{{ t }}</span>
                      <span class="jb-nr-del" title="删除" @click.stop="nrRemove(t)">×</span>
                    </span>
                  </template>
                  <div v-else class="jb-nr-empty">暂无历史记录，保存一条后会记住</div>
                </div>
                <div class="jb-nr-foot">点击标签填入，标签上的 × 可删除</div>
              </div>
            </el-popover>
          </el-form-item>
          <el-form-item label="起止:">
            <el-input v-model="form.qzriqi" readonly placeholder="工单带出的起止时间" />
          </el-form-item>

          <el-form-item label="开始:" required>
            <el-input v-model="form.kssj" placeholder="0900自动转09:00" maxlength="5"
                      @input="fmtTime('kssj')" />
          </el-form-item>
          <el-form-item label="结束:" required>
            <el-input v-model="form.jssj" placeholder="0900自动转09:00" maxlength="5"
                      @input="fmtTime('jssj')" />
          </el-form-item>

          <el-form-item label="时长:">
            <el-input-number v-model="form.shijian" :controls="false" :min="0" :precision="2"
                             style="width: 100%" @change="updateZongshu" />
          </el-form-item>
          <el-form-item label="倍数:">
            <el-input-number v-model="form.beishu" :controls="false" :min="0" :precision="1"
                             style="width: 100%" @change="onBeishuChange" />
          </el-form-item>
        </div>

        <div class="jb-result">
          <span class="jb-result-label">总时长</span>
          <el-input-number v-model="form.zongshu" readonly :controls="false" :precision="2"
                           class="jb-result-input" />
          <span class="jb-result-label lei">统计方式:</span>
          <el-radio-group v-model="form.lei">
            <el-radio :value="true">以地址统计</el-radio>
            <el-radio :value="false">非地址统计</el-radio>
          </el-radio-group>
        </div>

        <div class="jb-records">
          <el-table :data="gdRecords" size="small" border stripe max-height="180">
            <el-table-column prop="gongdanhao" label="工单号" width="110" align="center" />
            <el-table-column prop="ksriqi" label="开始时间" width="150" align="center" />
            <el-table-column prop="jsriqi" label="结束时间" width="150" align="center" />
            <el-table-column prop="shijian" label="时长" width="70" align="center" />
            <el-table-column prop="qiangxiurenyuan" label="抢修人员" width="110" align="center" />
            <el-table-column prop="djren" label="登记人" width="90" align="center" />
            <el-table-column prop="djriqi" label="登记日期" width="150" align="center" />
            <el-table-column prop="beizhu" label="备注" min-width="140" show-overflow-tooltip />
          </el-table>
        </div>
      </el-form>
      <template #footer>
        <div class="jb-dialog-foot">
          <el-button type="primary" :loading="saving" @click="submit">保存</el-button>
          <el-button @click="dialogVisible = false">取消</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- ==================== 加班人员管理弹窗 ==================== -->
    <el-dialog v-model="renVisible" class="std-dialog" title="加班人员管理"
               width="min(900px, calc(100vw - 40px))" top="6vh"
               append-to-body destroy-on-close>
      <div class="jb-ren-top">
        <el-form inline class="jb-ren-form" @submit.prevent="renSave">
          <el-form-item label="姓名:">
            <el-input v-model="renForm.name" style="width: 140px" />
          </el-form-item>
          <el-form-item label="工号:">
            <el-input v-model="renForm.gonghao" style="width: 140px" />
          </el-form-item>
          <el-form-item label="部门类别:">
            <el-input v-model="renForm.bmlb" style="width: 140px" />
          </el-form-item>
          <el-form-item label="单价:">
            <el-input-number v-model="renForm.danjia" :controls="false" :min="0" :precision="2"
                             style="width: 110px" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :loading="renSaving" @click="renSave">
              {{ renForm.id ? '更新' : '保存' }}
            </el-button>
            <el-button @click="resetRenForm">重置</el-button>
          </el-form-item>
        </el-form>
        <el-input v-model="renKeyword" size="small" clearable placeholder="姓名/部门类别/工号模糊搜索"
                  style="width: 220px" @keyup.enter="renSearch" @clear="renSearch">
          <template #append>
            <el-button size="small" :icon="'Search'" @click="renSearch" />
          </template>
        </el-input>
      </div>
      <el-table v-loading="renLoading" :data="renRows" size="small" border stripe
                height="340" highlight-current-row>
        <el-table-column prop="name" label="姓名" width="110" align="center" />
        <el-table-column prop="gonghao" label="工号" width="130" align="center" />
        <el-table-column prop="bmlb" label="部门类别" min-width="150" align="center" />
        <el-table-column prop="danjia" label="单价(元)" width="110" align="right">
          <template #default="{ row }">¥{{ Number(row.danjia || 0).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="120" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="renEdit(row)">编辑</el-button>
            <el-button link type="danger" size="small" @click="renDelete(row)">删除</el-button>
          </template>
        </el-table-column>
        <template #empty>暂无加班人员</template>
      </el-table>
      <div class="jb-ren-pager">
        <el-pagination v-model:current-page="renPage" v-model:page-size="renPageSize" small
                       background layout="total, sizes, prev, pager, next" :total="renTotal"
                       :page-sizes="[10, 20, 30]" @current-change="renPageChange"
                       @size-change="renSizeChange" />
      </div>
    </el-dialog>

    <!-- ==================== 导出备注弹窗 ==================== -->
    <el-dialog v-model="exportDialogVisible" class="std-dialog"
               :title="exportMode === 'address' ? '按地址导出 - 填写备注' : '导出 Excel - 填写备注'"
               width="min(480px, calc(100vw - 40px))" append-to-body destroy-on-close>
      <el-input v-model="exportRemark" type="textarea" :rows="4" maxlength="200"
                placeholder="填写每个表格底部备注字段内容" />
      <div class="jb-export-tip">填写每个表格底部备注字段内容</div>
      <template #footer>
        <div class="jb-dialog-foot">
          <el-button type="primary" @click="confirmExportDialog">确定</el-button>
          <el-button @click="exportDialogVisible = false">取消</el-button>
        </div>
      </template>
    </el-dialog>

    <!-- ==================== 外部工单详情抽屉(照抄 gongdan) ==================== -->
    <el-drawer v-model="woDrawer" :title="`工单详情 ${woInfo.gongdanhao}`" size="46%">
      <div v-loading="woInfo.loading" class="wo-body">
        <template v-if="woInfo.data">
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="工单号">
              {{ woInfo.data.Id || woInfo.gongdanhao }}
            </el-descriptions-item>
            <el-descriptions-item label="创建时间">
              {{ woInfo.data.createTime || '暂无数据' }}
            </el-descriptions-item>
            <el-descriptions-item label="结束时间">
              {{ woInfo.data.updateTime || '暂无数据' }}
            </el-descriptions-item>
            <el-descriptions-item label="地址">
              {{ woInfo.data.addressStr || '暂无数据' }}
            </el-descriptions-item>
            <el-descriptions-item label="问题描述">
              {{ woInfo.data.problem || '暂无数据' }}
            </el-descriptions-item>
            <el-descriptions-item label="备注">
              {{ woInfo.data.otherDemand || '暂无数据' }}
            </el-descriptions-item>
            <el-descriptions-item label="漏水损坏类型">
              {{ woInfo.data.damageType || '暂无数据' }}
            </el-descriptions-item>
            <el-descriptions-item label="漏水口径">
              {{ woInfo.data.leakageType || '暂无数据' }}
            </el-descriptions-item>
            <el-descriptions-item label="关闭阀门">
              {{ woInfo.data.closeValve || '暂无数据' }}
            </el-descriptions-item>
            <el-descriptions-item label="状态">
              <span :class="woInfo.data.status == 1 ? 'wo-done' : 'wo-doing'">
                {{ woInfo.data.status == 1 ? '已处理' : '处理中' }}
              </span>
            </el-descriptions-item>
          </el-descriptions>
          <div class="wo-image-title">现场图片</div>
          <div v-if="woInfo.images.length" class="wo-image-grid">
            <div v-for="img in woInfo.images" :key="img.kind" class="wo-image-slot">
              <el-image v-if="img.token_url" :src="img.token_url"
                        :preview-src-list="[img.token_url]" fit="cover" class="wo-image" />
              <div v-else class="wo-image wo-image-empty">暂无图片</div>
              <span class="wo-image-label">{{ img.label }}</span>
            </div>
          </div>
          <el-empty v-else :image-size="60" description="暂无现场图片" />
        </template>
        <el-empty v-else :description="woInfo.message || '暂无数据'" />
      </div>
    </el-drawer>

    <!-- ==================== 附件抽屉 ==================== -->
    <el-drawer v-model="attVisible" title="加班附件" size="56%">
      <div class="jb-att">
        <div class="jb-att-filter">
          <span class="jb-label">年月份:</span>
          <el-date-picker v-model="attMonth" type="month" value-format="YYYY-MM"
                          :clearable="false" style="width: 140px" @change="attMonthChange" />
          <el-button size="small" :icon="'Picture'" @click="openImageViewer({ id: 0 })">图片浏览</el-button>
          <span class="jb-att-tip">支持 PDF、图片，单文件 ≤ 50MB；点击图片名可翻看当月图片</span>
        </div>
        <div class="jb-att-upload">
          <el-button size="small" type="primary" :loading="attUploading"
                     @click="attInput?.click()">选择文件</el-button>
          <input ref="attInput" type="file" multiple style="display: none"
                 accept=".pdf,.jpg,.jpeg,.png,.gif,.bmp" @change="onAttFilesSelected" />
        </div>
        <div v-if="attQueue.length" class="jb-att-queue">
          <div v-for="f in attQueue" :key="f.name" class="jb-att-queue-item">
            <span class="jb-att-q-name" :title="f.name">{{ f.name }}</span>
            <span class="jb-att-q-size">{{ f.size < 1024 * 1024
              ? `${(f.size / 1024).toFixed(1)} KB` : `${(f.size / 1024 / 1024).toFixed(1)} MB` }}</span>
            <span class="jb-att-q-status">
              <template v-if="f.status === 'done'"><span class="jb-ok">上传成功</span></template>
              <template v-else-if="f.status === 'fail'"><span class="jb-err">{{ f.err }}</span></template>
              <template v-else>
                <el-progress :percentage="f.pct" :stroke-width="6" style="width: 120px" />
              </template>
            </span>
          </div>
        </div>
        <el-table v-loading="attLoading" :data="attRows" size="small" border
                  max-height="calc(100vh - 320px)">
          <el-table-column prop="jiabanDate" label="年月份" width="90" align="center" />
          <el-table-column prop="file_name" label="附件名称" min-width="220">
            <template #default="{ row }">
              <a class="jb-link" @click="attClick(row)">{{ row.file_name }}</a>
            </template>
          </el-table-column>
          <el-table-column prop="uploadTime" label="上传日期" width="160" align="center" />
          <el-table-column prop="operator_name" label="上传人" width="100" align="center" />
          <el-table-column prop="fileSizeStr" label="文件大小" width="100" align="center" />
          <el-table-column label="操作" width="80" align="center">
            <template #default="{ row }">
              <el-button v-if="row.canDelete" link type="danger" size="small"
                         @click="attDelete(row)">删除</el-button>
              <span v-else class="jb-muted">-</span>
            </template>
          </el-table-column>
        </el-table>
        <div class="jb-att-pager">
          <el-pagination v-model:current-page="attPage" v-model:page-size="attPageSize" small
                         background layout="total, sizes, prev, pager, next" :total="attTotal"
                         :page-sizes="[25, 50, 100]" @current-change="attPageChange"
                         @size-change="attSizeChange" />
        </div>
      </div>
    </el-drawer>

    <!-- ==================== 当月图片浏览窗(滚轮翻页) ==================== -->
    <teleport to="body">
      <div v-if="viewerVisible" class="jb-iv" @wheel.prevent="onViewerWheel">
        <div class="jb-iv-head">
          <span class="jb-iv-count">
            {{ viewerImages.length ? `${viewerIndex + 1} / ${viewerImages.length}` : '0 / 0' }}
          </span>
          <span class="jb-iv-name" :title="curImage?.name">{{ curImage?.name || '' }}</span>
          <span class="jb-iv-hint">滚轮 / ← → 翻页，Esc 关闭</span>
          <span class="jb-iv-close" title="关闭" @click="viewerVisible = false">✕</span>
        </div>
        <div class="jb-iv-body">
          <span v-if="viewerLoading" class="jb-iv-text">加载中…</span>
          <span v-else-if="!curImage" class="jb-iv-text">当月没有可预览的图片</span>
          <template v-else>
            <img v-if="!viewerErr" :key="curImage.url" :src="curImage.url" :alt="curImage.name"
                 draggable="false" @error="viewerErr = true" />
            <span v-else class="jb-iv-text">该文件已被删除，无法预览</span>
          </template>
        </div>
        <template v-if="!viewerLoading && curImage">
          <span v-if="viewerIndex > 0" class="jb-iv-nav prev" @click="viewerStep(-1)">‹</span>
          <span v-if="viewerIndex < viewerImages.length - 1" class="jb-iv-nav next"
                @click="viewerStep(1)">›</span>
        </template>
      </div>
    </teleport>
  </div>
</template>

<style scoped>
.jb-page {
  box-sizing: border-box;
  height: calc(100vh - 94px);
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow: hidden;
  background: #fff;
  border-radius: 6px;
  padding: 8px 12px;
}
.jb-banner {
  flex: 0 0 auto;
  background: linear-gradient(90deg, #2c3e6b, #5645d4);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 1px;
  border-radius: 5px;
  padding: 6px 16px;
}
.jb-search {
  flex: 0 0 auto;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border: 1px solid #e4e7ed;
  border-bottom: 2px solid #5645d4;
  border-radius: 6px;
  background: linear-gradient(145deg, #f7f6ff, #eeecfb);
}
.jb-kw { width: 240px; }
.jb-custom { display: inline-flex; align-items: center; gap: 6px; }
.jb-label { font-size: 12px; color: #5a5752; }
.jb-summary { margin-left: auto; font-size: 13px; color: #3d3a35; }
.jb-summary b { color: #5645d4; }
.jb-toolbar { flex: 0 0 auto; display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.jb-tip { margin-left: auto; font-size: 12px; color: #909399; }
.jb-table-wrap { flex: 1 1 auto; min-height: 0; overflow: hidden; }
.jb-pager { flex: 0 0 auto; display: flex; justify-content: flex-end; }
.jb-page :deep(.el-table--small .el-table__cell) { padding: 2px 0; }
.jb-page :deep(.el-table .cell) { line-height: 20px; padding: 0 4px; }
.jb-page :deep(.el-table__header-wrapper th) { padding: 3px 0; }
.jb-link { color: #5645d4; text-decoration: underline; cursor: pointer; }
.jb-page :deep(.hl) {
  background: rgba(83, 58, 253, .18);
  color: #6a4a00;
  border-radius: 2px;
  padding: 0 1px;
}
/* 工单详情抽屉:照抄 gongdan/workorder 的 .wo-* 同一套视觉 */
.wo-body { min-height: 220px; }
.wo-image-title { margin: 16px 0 8px; font-weight: 600; }
.wo-image-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.wo-image-slot { display: flex; flex-direction: column; align-items: center; gap: 6px; }
.wo-image {
  width: 100%; aspect-ratio: 1; border-radius: 6px;
  border: 1px solid var(--el-border-color);
}
.wo-image-empty {
  display: flex; align-items: center; justify-content: center;
  background: var(--el-fill-color-lighter);
  color: var(--el-text-color-secondary); font-size: 12px;
}
.wo-image-label { font-size: 12px; color: var(--el-text-color-regular); }
.wo-done { color: var(--el-color-success); font-weight: 600; }
.wo-doing { color: var(--el-color-warning); font-weight: 600; }
/* 附件抽屉 */
.jb-att { display: flex; flex-direction: column; gap: 10px; }
.jb-att-filter { display: flex; align-items: center; gap: 8px; }
.jb-att-tip { font-size: 12px; color: #909399; }
.jb-att-queue { border: 1px solid var(--el-border-color-lighter); border-radius: 6px; padding: 8px; }
.jb-att-queue-item { display: flex; align-items: center; gap: 10px; padding: 4px 0; }
.jb-att-q-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.jb-att-q-size { flex: 0 0 70px; text-align: right; font-size: 12px; color: #909399; }
.jb-att-q-status { flex: 0 0 140px; text-align: right; font-size: 12px; }
.jb-ok { color: var(--el-color-success); }
.jb-err { color: var(--el-color-danger); }
.jb-muted { color: #c0c4cc; }
.jb-att-pager { display: flex; justify-content: flex-end; }
</style>

<!-- 弹窗被 teleport 到 body,scoped 选择器够不到,按项目约定用非 scoped + 类名前缀 -->
<style>
/* ===== 添加/编辑弹窗内部布局(std-dialog 已含紫题头/灰底/按钮基类,这里只补结构) ===== */
.jb-form .jb-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 12px 16px; align-content: start;
}
.jb-form .el-form-item { margin-bottom: 0; align-items: center; }
.jb-form .el-form-item__label {
  flex: 0 0 72px; width: 72px; height: 32px; line-height: 32px;
  margin-right: 4px !important; padding: 0 !important;
  display: inline-flex; align-items: center; justify-content: flex-start;
  color: #5a5752; font-size: 12px; font-weight: 500;
}
.jb-form .el-form-item__content { min-width: 0; line-height: 32px; }
.jb-person { display: flex; align-items: center; gap: 8px; width: 100%; }
.jb-name-count {
  flex: 0 0 auto; font-size: 12px; color: #fff; background: #5645d4;
  padding: 2px 10px; border-radius: 10px; white-space: nowrap;
}
.jb-result {
  display: flex; align-items: center; gap: 10px; margin-top: 14px;
  background: #fff; border-radius: 10px; padding: 10px 14px;
  border: 1px solid #e6e2fb;
  box-shadow: 0 1px 2px rgba(16, 24, 40, .04);
}
.jb-result-label { font-weight: 600; color: #5a5752; font-size: 13px; white-space: nowrap; }
.jb-result-label.lei { margin-left: 8px; }
.jb-result-input { flex: 0 0 200px; }
.jb-records { margin-top: 12px; }
.jb-dialog-foot { display: flex; justify-content: flex-end; gap: 8px; width: 100%; }

/* 内容历史气泡(照旧 rh-bubble 风格) */
.jb-nr-popper.el-popper { padding: 10px !important; }
.jb-nr-title { font-weight: 600; font-size: 13px; color: #3d3a35; margin-bottom: 8px; }
.jb-nr-count { margin-left: 6px; font-weight: 400; font-size: 12px; color: #909399; }

/* ===== 当月图片浏览窗(全屏遮罩,滚轮翻页) ===== */
.jb-iv {
  position: fixed; inset: 0; z-index: 3000;
  background: rgba(17, 18, 22, .92);
  display: flex; flex-direction: column;
}
.jb-iv-head {
  flex: 0 0 48px; display: flex; align-items: center; gap: 12px;
  padding: 0 16px; color: #e8e8ea; font-size: 13px;
}
.jb-iv-count { color: #fff; font-weight: 600; white-space: nowrap; }
.jb-iv-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.jb-iv-hint { color: rgba(255, 255, 255, .45); font-size: 12px; white-space: nowrap; }
.jb-iv-close {
  flex: 0 0 28px; width: 28px; height: 28px; border-radius: 6px;
  display: flex; align-items: center; justify-content: center;
  color: #fff; font-size: 16px; cursor: pointer; user-select: none;
}
.jb-iv-close:hover { background: rgba(255, 255, 255, .15); }
.jb-iv-body {
  flex: 1; min-height: 0; padding: 0 64px 16px;
  display: flex; align-items: center; justify-content: center;
}
.jb-iv-body img {
  max-width: 100%; max-height: 100%; object-fit: contain;
  box-shadow: 0 4px 24px rgba(0, 0, 0, .5); user-select: none;
}
.jb-iv-text { color: rgba(255, 255, 255, .7); font-size: 14px; }
.jb-iv-nav {
  position: absolute; top: 50%; transform: translateY(-50%);
  width: 44px; height: 44px; border-radius: 50%;
  background: rgba(255, 255, 255, .12); color: #fff; font-size: 26px;
  display: flex; align-items: center; justify-content: center;
  cursor: pointer; user-select: none;
}
.jb-iv-nav:hover { background: rgba(255, 255, 255, .25); }
.jb-iv-nav.prev { left: 16px; }
.jb-iv-nav.next { right: 16px; }
.jb-nr-tags { display: flex; flex-wrap: wrap; gap: 6px; max-height: 180px; overflow-y: auto; }
.jb-nr-empty { font-size: 12px; color: #909399; padding: 12px 0; }
.jb-nr-tag {
  display: inline-flex; align-items: center; gap: 4px; max-width: 100%;
  background: #f2f0fd; border: 1px solid #ddd8f7; border-radius: 12px;
  padding: 2px 8px; font-size: 12px; color: #4b3bc0; cursor: pointer;
}
.jb-nr-tag:hover { background: #e9e4ff; }
.jb-nr-tag-txt { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 260px; }
.jb-nr-del { color: #b1a8ee; font-size: 14px; padding: 0 2px; }
.jb-nr-del:hover { color: #e23c3c; }
.jb-nr-foot { margin-top: 8px; font-size: 11px; color: #a8abb2; }

/* 加班人员管理弹窗 */
.jb-ren-top {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 12px; margin-bottom: 10px; flex-wrap: wrap;
}
.jb-ren-form .el-form-item { margin-bottom: 6px; margin-right: 10px; }
.jb-ren-pager { display: flex; justify-content: flex-end; margin-top: 10px; }

/* 导出备注弹窗 */
.jb-export-tip { text-align: right; color: #9ca3af; margin-top: 6px; font-size: 12px; }
</style>
