<script setup>
/**
 * 工单信息录入 —— 照旧 Gongdan/Index.cshtml 1:1 复刻
 * 顶部: 标题(含记录数) + 查询带(模糊/按登记日期/重复/非重复/日期/管径/部门)
 * 中部: 5 个工具栏按钮 + 17 列主表(大管径行浅红、工单号可点开详情抽屉、关键字高亮)
 * 弹窗: 新增/编辑(两列表单、工单号失焦带出、字典可删选项、主材点击看领料明细)
 *      抢修班组名单(增删改)、领料明细、右侧工单详情抽屉(含现场图片)
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  addGongdan, addQiangxiu, deleteCaizhi, deleteGongdan, deleteNeirong,
  deleteQiangxiu, editQiangxiu, exportGongdan, getGongdanDicts, getGongdanInfo,
  getExternalImages, getExternalWorkOrder, getOrderDetails, listGongdan,
  listQiangxiu, searchCaizhi, searchNeirong, updateGongdan,
} from '@/api/gongdan'

// ==================== 字典 / 查询 ====================
const dicts = reactive({
  departments: [], banzu: [], guanjing: [], tingshui: [],
  defaultRq: '', defaultRqend: '', recordCount: 0,
  perms: { view: true, manage: false },
})
const query = reactive({
  mohu: '', rq: '', rqend: '', minPipe: null, maxPipe: null, bmid: null,
})
const flags = reactive({ byDj: false, cf: false, fcf: false })
const searchKey = ref('')
const rows = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(30)
const loading = ref(false)
const selected = ref(null)
const tableWrap = ref(null)
const tableH = ref(400)
let tableObserver = null

function buildParams() {
  // 数字参数为空时不能传 '' (后端 Optional[int] 会 422),直接不放进 params
  const p = {
    page: page.value, rows: pageSize.value,
    rq: query.rq, rqend: query.rqend, mohu: query.mohu.trim(),
    anbjriqi: flags.byDj ? 'on' : '',
    cf: flags.cf ? 'on' : '', fcf: flags.fcf ? 'on' : '',
  }
  if (query.minPipe !== null && query.minPipe !== '') p.minPipe = query.minPipe
  if (query.maxPipe !== null && query.maxPipe !== '') p.maxPipe = query.maxPipe
  if (query.bmid) p.bmid = query.bmid
  return p
}

async function load() {
  loading.value = true
  try {
    const data = await listGongdan(buildParams())
    rows.value = data.rows || []
    total.value = data.total || 0
  } finally {
    loading.value = false
  }
}

function reload(resetPage = true) {
  searchKey.value = query.mohu.trim()
  if (resetPage) page.value = 1
  load()
}

function doSearch() { reload() }
function gjSearch() { reload() }
function onFlagChange(label, on) {
  ElMessage({ message: `${label}：${on ? '已启用' : '已关闭'}`, type: 'info', duration: 1200 })
  reload()
}
function clearDept() {
  query.bmid = null
  reload()
}
function onDateChange() { reload() }
function onSizeChange(v) { pageSize.value = v; reload() }
function onPageChange(v) { page.value = v; load() }

async function loadDicts() {
  const d = await getGongdanDicts()
  Object.assign(dicts, d)
  if (!query.rq) query.rq = d.defaultRq
  if (!query.rqend) query.rqend = d.defaultRqend
}

// ==================== 关键字高亮(先转义,防存储型 XSS) ====================
function escapeHtml(v) {
  return String(v ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]))
}
function highlight(text) {
  const raw = String(text ?? '')
  const keys = [...new Set(searchKey.value.split(/[\s,，]+/).filter(Boolean))]
  if (!keys.length) return escapeHtml(raw)
  const pattern = keys.map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')
  const re = new RegExp(`(${pattern})`, 'gi')
  return raw.split(re).map((part) => (
    keys.some((k) => k.toLowerCase() === part.toLowerCase())
      ? `<span class="hl">${escapeHtml(part)}</span>` : escapeHtml(part)
  )).join('')
}
function rowClass({ row }) { return row.pipesize >= 100 ? 'gd-row-large' : '' }
function fmtDuration(minutes) {
  const m = Math.max(0, Math.floor(Number(minutes) || 0))
  const d = Math.floor(m / 1440)
  const h = Math.floor((m % 1440) / 60)
  return `${d}天 ${h}时 ${m % 60}分`
}

// 外部工单返回的时间串可能是 ISO(T) 或带毫秒,统一成 el-date-picker 的 value-format
function normalizeDt(v) {
  const txt = String(v || '').trim().replace('T', ' ')
  if (!/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(txt)) return ''
  const base = txt.slice(0, 19)
  return base.length === 16 ? `${base}:00` : base
}

// ==================== 外部工单详情抽屉(照抄 workorder/WorkOrderManage.vue) ====================
// /gongdan/by-no 与 /workorder/external/info 同一上游服务、同一返回结构;
// 差别只在权限码:这里用 gongdan:view,录入用户无需 workorder:view。
const woDrawer = ref(false)
const woInfo = reactive({
  gongdanhao: '', message: '', loading: false, data: null, images: [],
})
async function openWorkOrderDrawer(no) {
  Object.assign(woInfo, {
    gongdanhao: no || '', message: '', data: null, images: [],
  })
  woDrawer.value = true
  if (!no) {
    woInfo.message = '工单号为空'
    return
  }
  woInfo.loading = true
  try {
    const res = await getExternalWorkOrder(no)
    if (res.success && res.data) {
      woInfo.data = res.data
      try {
        const imgRes = await getExternalImages(res.data.Id || no, no)
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

// ==================== 新增 / 编辑弹窗 ====================
const dialogVisible = ref(false)
const dialogMode = ref('add')
const formRef = ref(null)
const noInput = ref(null)
const saving = ref(false)
const form = reactive({
  id: null, gongdanhao: '', neirong: '', ksriqi: '', jsriqi: '', shijian: null,
  tingshui: '', dizhi: '', caizhi: '', guanjing: '', shuiliang: null,
  cailiao: '', shuliang: '', qiangxiurenyuan: '', beizhu: '',
})
const neirongOptions = ref([])
const caizhiOptions = ref([])
let dictTimer = null

// ==================== 日期 + 时:分（照旧 Index.cshtml 的 datebox + initTimeGrid） ====================
// form.ksriqi / form.jsriqi 仍是提交用的完整值 yyyy-MM-dd HH:mm:ss;
// 日期框与时:分框分开显示,两者都有效时才合成完整值(旧 syncDt 口径)。
const dt = reactive({ ksDate: '', ksTime: '', jsDate: '', jsTime: '' })
const timePop = reactive({ ks: false, js: false })
const selHour = reactive({ ks: '', js: '' })
const hourCells = Array.from({ length: 24 }, (_, i) => String(i).padStart(2, '0'))
const minuteCells = Array.from({ length: 60 }, (_, i) => String(i).padStart(2, '0'))
const durationText = computed(() => (form.shijian === null || form.shijian === '')
  ? '格式: 天:时:分' : fmtDuration(form.shijian))

// 兼容 '9:30' / '09:30' / '930' / '0930' 四种手输
function parseTime(v) {
  const s = String(v || '').trim()
  const m = s.match(/^(\d{1,2}):(\d{1,2})$/) || s.match(/^(\d{1,2})(\d{2})$/)
  if (!m) return null
  const h = Number(m[1]); const mi = Number(m[2])
  if (h > 23 || mi > 59) return null
  return { h: String(h).padStart(2, '0'), m: String(mi).padStart(2, '0') }
}
function syncDt(p) {
  const date = dt[p + 'Date']
  const t = parseTime(dt[p + 'Time'])
  form[p + 'riqi'] = date && t ? `${date} ${t.h}:${t.m}:00` : ''
}
function normalizeTime(p) {
  const t = parseTime(dt[p + 'Time'])
  dt[p + 'Time'] = t ? `${t.h}:${t.m}` : ''
  syncDt(p)
}
function setDt(p, v) {
  const m = String(v || '').trim().replace('T', ' ').match(/^(\d{4}-\d{2}-\d{2})\s+(\d{2}):(\d{2})/)
  dt[p + 'Date'] = m ? m[1] : ''
  dt[p + 'Time'] = m ? `${m[2]}:${m[3]}` : ''
}
function openTime(p) {
  const t = parseTime(dt[p + 'Time'])
  selHour[p] = t ? t.h : ''
}
function pickHour(p, h) { selHour[p] = h }
function pickMinute(p, m) {
  const h = selHour[p] || parseTime(dt[p + 'Time'])?.h || '00'
  dt[p + 'Time'] = `${h}:${m}`
  selHour[p] = ''
  timePop[p] = false
  syncDt(p)
}

function resetForm() {
  Object.assign(form, {
    id: null, gongdanhao: '', neirong: '', ksriqi: '', jsriqi: '', shijian: null,
    tingshui: '', dizhi: '', caizhi: '', guanjing: '', shuiliang: null,
    cailiao: '', shuliang: '', qiangxiurenyuan: '', beizhu: '',
  })
  Object.assign(dt, { ksDate: '', ksTime: '', jsDate: '', jsTime: '' })
  Object.assign(timePop, { ks: false, js: false })
  Object.assign(selHour, { ks: '', js: '' })
}
function dialogTitle() { return dialogMode.value === 'add' ? '添加工单材料' : '编辑工单材料' }

async function loadDictOptions(kind, q = '') {
  try {
    if (kind === 'neirong') neirongOptions.value = await searchNeirong(q)
    else caizhiOptions.value = await searchCaizhi(q)
  } catch { /* 拦截器已提示 */ }
}
function remoteDict(kind, q) {
  clearTimeout(dictTimer)
  dictTimer = setTimeout(() => loadDictOptions(kind, q || ''), 300)
}
function refreshDicts() {
  loadDictOptions('neirong')
  loadDictOptions('caizhi')
}
async function deleteDictOption(kind, value) {
  if (!value) return
  try {
    await ElMessageBox.confirm(`确定要删除 "${value}" 吗？`, '删除字典选项', { type: 'warning' })
    if (kind === 'neirong') await deleteNeirong(value)
    else await deleteCaizhi(value)
    refreshDicts() // 旧页面添加/编辑两个材质下拉都 reload
    ElMessage.success('已删除')
  } catch { /* 取消或拦截器已提示 */ }
}

function openAdd() {
  dialogMode.value = 'add'
  resetForm()
  dialogVisible.value = true
  refreshDicts()
  nextTick(() => noInput.value?.focus())
}
function openEdit(row) {
  if (!row) { ElMessage.error('请选择要编辑的记录！'); return }
  dialogMode.value = 'edit'
  suppressCalc = true
  resetForm()
  Object.assign(form, {
    id: row.ID, gongdanhao: row.gongdanhao, neirong: row.neirong,
    ksriqi: row.ksriqi, jsriqi: row.jsriqi, shijian: row.shijian,
    tingshui: row.tingshui, dizhi: row.dizhi, caizhi: row.caizhi,
    guanjing: row.guanjing, shuiliang: row.shuiliang, cailiao: row.cailiao,
    shuliang: row.shuliang, qiangxiurenyuan: row.qiangxiurenyuan,
    beizhu: row.beizhu,
  })
  setDt('ks', row.ksriqi)
  setDt('js', row.jsriqi)
  dialogVisible.value = true
  refreshDicts()
  nextTick(() => { suppressCalc = false })
}
function closeDialog() {
  dialogVisible.value = false
  resetForm()
}

// 日期变化时自动算工时(分钟),与旧 calcMinute 一致(Math.floor)
function calcMinute() {
  const a = new Date(String(form.ksriqi || '').replace(/-/g, '/'))
  const b = new Date(String(form.jsriqi || '').replace(/-/g, '/'))
  if (isNaN(a.getTime()) || isNaN(b.getTime())) return
  const diff = Math.floor((b - a) / 60000)
  if (diff < 0) { ElMessage.warning('结束时间不能小于开始时间'); return }
  form.shijian = diff
}
let suppressCalc = false
watch(() => [form.ksriqi, form.jsriqi], () => {
  // 编辑回显时不重算工时(照旧:只在用户改动日期时算),避免保存时悄悄改掉历史 shijian
  if (suppressCalc || !dialogVisible.value) return
  calcMinute()
})

// 工单号失焦:内网工单带出开始/结束/地址/主材 + 查重提示
async function onNoBlur() {
  const no = form.gongdanhao.trim()
  if (!no) return
  try {
    const res = await getGongdanInfo(no)
    if (res.hasUsed) {
      ElMessageBox.alert('该工单号已存在记录（但可继续使用）', '提示', { type: 'info' })
    }
    const d = res.data || {}
    form.ksriqi = normalizeDt(d.ksriqi)
    form.jsriqi = normalizeDt(d.jsriqi)
    setDt('ks', form.ksriqi)
    setDt('js', form.jsriqi)
    form.dizhi = d.dizhi || ''
    form.cailiao = d.cailiao || ''
  } catch {
    form.ksriqi = ''; form.jsriqi = ''; form.dizhi = ''
    setDt('ks', ''); setDt('js', '')
    form.shijian = null
  }
}

function validateForm() {
  if (!form.gongdanhao.trim()) return '工单号为必填字段'
  if (!String(form.neirong || '').trim()) return '工作内容为必填字段'
  if (!form.ksriqi) return '开始日期为必填字段'
  if (!form.jsriqi) return '结束日期为必填字段'
  return ''
}
async function submit(continueAdding = false) {
  const err = validateForm()
  if (err) { ElMessage.error(err); return }
  saving.value = true
  try {
    const payload = { ...form }
    const keep = {
      gongdanhao: form.gongdanhao, qiangxiurenyuan: form.qiangxiurenyuan,
      neirong: form.neirong, guanjing: form.guanjing,
    }
    if (dialogMode.value === 'add') {
      await addGongdan(payload)
      ElMessage.success('添加成功！')
    } else {
      const res = await updateGongdan(payload)
      if (res.hasUsed) ElMessageBox.alert(res.message, '提示', { type: 'info' })
      else ElMessage.success('编辑成功！')
    }
    refreshDicts()
    loadDicts()
    reload()
    if (continueAdding) {
      resetForm()
      Object.assign(form, keep)
      nextTick(() => noInput.value?.focus())
    } else {
      closeDialog()
    }
  } finally {
    saving.value = false
  }
}

async function deleteRow() {
  if (!selected.value) { ElMessage.error('请选择要删除的记录！'); return }
  if (!dicts.perms.manage) { ElMessage.error('没有删除权限（需要 gongdan:manage）'); return }
  try {
    await ElMessageBox.confirm(`确定删除工单号 ${selected.value.gongdanhao} 的记录吗？`,
      '删除确认', { type: 'warning' })
    await deleteGongdan(selected.value.ID)
    ElMessage.success('删除成功')
    selected.value = null
    reload()
    loadDicts()
  } catch { /* 取消或拦截器已提示 */ }
}

async function exportRows() {
  try {
    await exportGongdan(buildParams())
    ElMessage.success('导出完成')
  } catch { /* 拦截器已提示 */ }
}

// ==================== 领料明细弹窗 ====================
const detailVisible = ref(false)
const detailNo = ref('')
const detailRows = ref([])
const detailLoading = ref(false)
async function openDetails() {
  const no = form.gongdanhao.trim()
  if (!no) { ElMessage.warning('请先填写工单号'); return }
  detailNo.value = no
  detailVisible.value = true
  detailLoading.value = true
  try {
    detailRows.value = await getOrderDetails(no)
  } finally {
    detailLoading.value = false
  }
}

// ==================== 抢修班组名单弹窗 ====================
const qxVisible = ref(false)
const qxRows = ref([])
const qxKeyword = ref('')
const qxName = ref('')
const qxSelected = ref(null)
const qxLoading = ref(false)
async function loadQx() {
  qxLoading.value = true
  try { qxRows.value = await listQiangxiu(qxKeyword.value.trim()) }
  finally { qxLoading.value = false }
}
async function openQx() {
  qxVisible.value = true
  qxKeyword.value = ''
  await loadQx()
  await loadDicts()
}
async function qxAdd() {
  if (!qxName.value.trim()) { ElMessage.warning('请输入姓名'); return }
  try {
    await addQiangxiu(qxName.value.trim())
    qxName.value = ''
    qxSelected.value = null
    await loadQx()
    await loadDicts()
    ElMessage.success('已新增')
  } catch { /* 拦截器已提示 */ }
}
async function qxEdit() {
  if (!qxSelected.value) { ElMessage.warning('请选择记录'); return }
  if (!qxName.value.trim()) { ElMessage.warning('请输入姓名'); return }
  try {
    await editQiangxiu(qxSelected.value.id, qxName.value.trim())
    qxName.value = ''
    qxSelected.value = null
    await loadQx()
    await loadDicts()
    ElMessage.success('已修改')
  } catch { /* 拦截器已提示 */ }
}
async function qxDelete() {
  if (!qxSelected.value) { ElMessage.warning('请选择记录'); return }
  try {
    await ElMessageBox.confirm('确定删除？', '删除确认', { type: 'warning' })
    await deleteQiangxiu(qxSelected.value.id)
    qxName.value = ''
    qxSelected.value = null
    await loadQx()
    await loadDicts()
    ElMessage.success('已删除')
  } catch { /* 取消或拦截器已提示 */ }
}

// ==================== 视口自适应 ====================
const winWidth = ref(window.innerWidth)
// 17 列全宽需 ~1650px;1920 以下先隐藏 3 个次要日期/登记人列,避免横向滚动条
const wide = computed(() => winWidth.value >= 1920)
function fitTable() {
  if (tableWrap.value) tableH.value = Math.max(180, tableWrap.value.clientHeight)
}
function onWindowResize() { winWidth.value = window.innerWidth; fitTable() }
onMounted(async () => {
  await loadDicts()
  await load()
  refreshDicts()
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
  clearTimeout(dictTimer)
})
</script>

<template>
  <div class="gd-page">
    <div class="gd-banner">
      工单信息录入
      <span class="gd-count">（当前筛选 {{ total }} 条 / 共 {{ dicts.recordCount }} 条记录）</span>
    </div>

    <!-- ==================== 查询带 ==================== -->
    <div class="gd-search">
      <el-input v-model="query.mohu" size="small" clearable placeholder="模糊查询" class="gd-kw"
                @keyup.enter="doSearch" @clear="doSearch">
        <template #append>
          <el-button size="small" :icon="'Search'" @click="doSearch" />
        </template>
      </el-input>
      <el-checkbox v-model="flags.byDj" size="small" @change="(v) => onFlagChange('按编辑日期筛选', v)">
        按创建日期
      </el-checkbox>
      <el-checkbox v-model="flags.cf" size="small" @change="(v) => onFlagChange('重复工单', v)">
        重复工单
      </el-checkbox>
      <el-checkbox v-model="flags.fcf" size="small" @change="(v) => onFlagChange('非重复工单', v)">
        非重复工单
      </el-checkbox>
      <span class="gd-label">开始：</span>
      <el-date-picker v-model="query.rq" type="date" size="small" value-format="YYYY-MM-DD"
                      :clearable="false" style="width: 132px" @change="onDateChange" />
      <span class="gd-label">结束：</span>
      <el-date-picker v-model="query.rqend" type="date" size="small" value-format="YYYY-MM-DD"
                      :clearable="false" style="width: 132px" @change="onDateChange" />
      <span class="gd-label">管径范围：</span>
      <el-input-number v-model="query.minPipe" size="small" :controls="false" placeholder="最小"
                       style="width: 72px" @keyup.enter="gjSearch" />
      <span class="gd-label">至</span>
      <el-input-number v-model="query.maxPipe" size="small" :controls="false" placeholder="最大"
                       style="width: 72px" @keyup.enter="gjSearch" />
      <el-select v-model="query.bmid" size="small" clearable filterable placeholder="选择部门"
                 style="width: 150px" @change="gjSearch">
        <el-option v-for="d in dicts.departments" :key="d.id" :label="d.bm" :value="d.id" />
      </el-select>
      <el-button size="small" type="primary" :icon="'Search'" @click="gjSearch">精确筛选</el-button>
      <el-button size="small" :icon="'Close'" @click="clearDept">清空部门</el-button>
    </div>

    <!-- ==================== 工具栏 ==================== -->
    <div class="gd-toolbar">
      <el-button size="small" type="primary" :icon="'Plus'" @click="openAdd">添加</el-button>
      <el-button size="small" :icon="'Download'" @click="exportRows">导出记录</el-button>
      <el-button size="small" :icon="'Edit'" @click="openEdit(selected)">编辑</el-button>
      <el-button size="small" :icon="'Delete'" @click="deleteRow">删除</el-button>
      <el-button size="small" :icon="'User'" @click="openQx">抢修班组名单</el-button>
      <span class="gd-tip">双击行可编辑；管径 ≥100 的行浅红标记；点击工单号查看工单详情</span>
    </div>

    <!-- ==================== 主表 ==================== -->
    <div ref="tableWrap" class="gd-table-wrap">
      <el-table v-loading="loading" :data="rows" size="small" border stripe :height="tableH"
                highlight-current-row :row-class-name="rowClass" row-key="ID"
                @row-click="(r) => (selected = r)" @row-dblclick="openEdit">
        <el-table-column prop="gongdanhao" label="工单号" width="106" align="center">
          <template #default="{ row }">
            <a class="gd-link" title="点击查看详情" @click.stop="openWorkOrderDrawer(row.gongdanhao)"
               v-html="highlight(row.gongdanhao)" />
          </template>
        </el-table-column>
        <el-table-column prop="ksriqi" label="开始日期" width="132" />
        <el-table-column prop="jsriqi" label="竣工日期" width="132" />
        <el-table-column prop="shijian" label="工时" width="56" align="center" />
        <el-table-column prop="dizhi" label="地址" min-width="140" show-overflow-tooltip>
          <template #default="{ row }"><span v-html="highlight(row.dizhi)" /></template>
        </el-table-column>
        <el-table-column prop="neirong" label="工作内容" width="106" show-overflow-tooltip>
          <template #default="{ row }"><span v-html="highlight(row.neirong)" /></template>
        </el-table-column>
        <el-table-column prop="caizhi" label="材质" width="66">
          <template #default="{ row }"><span v-html="highlight(row.caizhi)" /></template>
        </el-table-column>
        <el-table-column prop="guanjing" label="管径" width="66">
          <template #default="{ row }"><span v-html="highlight(row.guanjing)" /></template>
        </el-table-column>
        <el-table-column prop="tingshui" label="停水情况" width="76" />
        <el-table-column prop="shuiliang" label="漏水量" width="66" align="center" />
        <el-table-column prop="cailiao" label="主材" min-width="132" show-overflow-tooltip>
          <template #default="{ row }"><span v-html="highlight(row.cailiao)" /></template>
        </el-table-column>
        <el-table-column prop="beizhu" label="备注" width="88" show-overflow-tooltip>
          <template #default="{ row }"><span v-html="highlight(row.beizhu)" /></template>
        </el-table-column>
        <el-table-column prop="qiangxiurenyuan" label="抢修班组" width="86">
          <template #default="{ row }"><span v-html="highlight(row.qiangxiurenyuan)" /></template>
        </el-table-column>
        <el-table-column v-if="wide" prop="djriqi" label="登记日期" width="132" />
        <el-table-column v-if="wide" prop="zuihouriqi" label="最后编辑日期" width="132" />
        <el-table-column v-if="wide" prop="djren" label="登记人" width="76" />
        <el-table-column prop="ID" label="ID号" width="58" align="center" />
      </el-table>
    </div>
    <div class="gd-pager">
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize" small background
                     layout="total, sizes, prev, pager, next, jumper" :total="total"
                     :page-sizes="[30, 60, 120]" @current-change="onPageChange"
                     @size-change="onSizeChange" />
    </div>

    <!-- ==================== 新增 / 编辑弹窗（照旧 Index.cshtml #addDiv 1:1） ==================== -->
    <el-dialog v-model="dialogVisible" class="gd-dialog" :title="dialogTitle()" width="min(920px, calc(100vw - 40px))"
               top="2vh" :close-on-click-modal="false" append-to-body destroy-on-close @closed="resetForm">
      <div class="gd-card">
        <el-form ref="formRef" :model="form" label-width="72px" class="gd-form">
          <div class="gd-form-grid">
            <el-form-item label="工单号:" required>
              <el-input ref="noInput" v-model="form.gongdanhao" clearable
                        @blur="onNoBlur" @keyup.enter="$event.target.blur()" />
            </el-form-item>
            <el-form-item label="工作内容:" required>
              <el-select v-model="form.neirong" filterable remote allow-create clearable
                         default-first-option :remote-method="(q) => remoteDict('neirong', q)"
                         placeholder="请选择或输入工作内容" style="width: 100%" @focus="loadDictOptions('neirong')">
                <el-option v-for="o in neirongOptions.filter((x) => x.Text)" :key="o.Text"
                           :label="o.Text" :value="o.Text">
                  <div class="gd-option">
                    <span>{{ o.Text }}</span>
                    <span v-if="dialogMode === 'add'" class="gd-option-del" title="删除该选项"
                          @click.stop="deleteDictOption('neirong', o.Text)">✖</span>
                  </div>
                </el-option>
              </el-select>
            </el-form-item>

            <!-- 日期框 + 时:分格子（旧 datebox + initTimeGrid） -->
            <el-form-item label="开始日期:" required>
              <div class="gd-dt-row">
                <el-date-picker v-model="dt.ksDate" type="date" value-format="YYYY-MM-DD"
                                class="gd-date" placeholder="" @change="syncDt('ks')" />
                <el-popover v-model:visible="timePop.ks" placement="bottom-start" :width="300"
                            trigger="click" popper-class="gd-time-popper" :show-arrow="false"
                            @show="openTime('ks')">
                  <template #reference>
                    <input class="gd-time-input" v-model="dt.ksTime" placeholder="时:分" maxlength="5"
                           title="点击选择，也可直接输入" @input="syncDt('ks')"
                           @blur="normalizeTime('ks')" />
                  </template>
                  <div class="gd-tp">
                    <div class="gd-tp-title">小时</div>
                    <div class="gd-tp-grid">
                      <div v-for="h in hourCells" :key="h" class="gd-tp-cell"
                           :class="{ sel: selHour.ks === h }" @click="pickHour('ks', h)">{{ h }}</div>
                    </div>
                    <div class="gd-tp-title">分钟</div>
                    <div class="gd-tp-grid">
                      <div v-for="m in minuteCells" :key="m" class="gd-tp-cell"
                           :class="{ sel: parseTime(dt.ksTime)?.m === m }"
                           @click="pickMinute('ks', m)">{{ m }}</div>
                    </div>
                  </div>
                </el-popover>
              </div>
            </el-form-item>
            <el-form-item label="结束日期:" required>
              <div class="gd-dt-row">
                <el-date-picker v-model="dt.jsDate" type="date" value-format="YYYY-MM-DD"
                                class="gd-date" placeholder="" @change="syncDt('js')" />
                <el-popover v-model:visible="timePop.js" placement="bottom-start" :width="300"
                            trigger="click" popper-class="gd-time-popper" :show-arrow="false"
                            @show="openTime('js')">
                  <template #reference>
                    <input class="gd-time-input" v-model="dt.jsTime" placeholder="时:分" maxlength="5"
                           title="点击选择，也可直接输入" @input="syncDt('js')"
                           @blur="normalizeTime('js')" />
                  </template>
                  <div class="gd-tp">
                    <div class="gd-tp-title">小时</div>
                    <div class="gd-tp-grid">
                      <div v-for="h in hourCells" :key="h" class="gd-tp-cell"
                           :class="{ sel: selHour.js === h }" @click="pickHour('js', h)">{{ h }}</div>
                    </div>
                    <div class="gd-tp-title">分钟</div>
                    <div class="gd-tp-grid">
                      <div v-for="m in minuteCells" :key="m" class="gd-tp-cell"
                           :class="{ sel: parseTime(dt.jsTime)?.m === m }"
                           @click="pickMinute('js', m)">{{ m }}</div>
                    </div>
                  </div>
                </el-popover>
              </div>
            </el-form-item>

            <el-form-item label="工时(分钟):">
              <div class="gd-inline">
                <el-input-number v-model="form.shijian" :controls="false" :min="0" class="gd-minute" />
                <span class="gd-duration">{{ durationText }}</span>
              </div>
            </el-form-item>
            <el-form-item label="停水情况:">
              <el-select v-model="form.tingshui" clearable filterable allow-create
                         placeholder="请选择或输入" style="width: 100%">
                <el-option v-for="t in dicts.tingshui" :key="t" :label="t" :value="t" />
              </el-select>
            </el-form-item>
            <el-form-item class="gd-full" label="地址:">
              <el-input v-model="form.dizhi" clearable />
            </el-form-item>
            <el-form-item label="材质:">
              <el-select v-model="form.caizhi" filterable remote allow-create clearable
                         default-first-option :remote-method="(q) => remoteDict('caizhi', q)"
                         placeholder="请选择或输入材质" style="width: 100%" @focus="loadDictOptions('caizhi')">
                <el-option v-for="o in caizhiOptions.filter((x) => x.Text)" :key="o.Text"
                           :label="o.Text" :value="o.Text">
                  <div class="gd-option">
                    <span>{{ o.Text }}</span>
                    <span class="gd-option-del" title="删除该选项"
                          @click.stop="deleteDictOption('caizhi', o.Text)">✖</span>
                  </div>
                </el-option>
              </el-select>
            </el-form-item>
            <el-form-item label="管径:">
              <el-select v-model="form.guanjing" filterable clearable allow-create
                         default-first-option placeholder=" " style="width: 100%">
                <el-option v-for="g in dicts.guanjing" :key="g" :label="g" :value="g" />
              </el-select>
            </el-form-item>
            <el-form-item label="漏水量:">
              <el-input-number v-model="form.shuiliang" :controls="false" style="width: 100%" />
            </el-form-item>
            <el-form-item label="抢修班组:">
              <el-select v-model="form.qiangxiurenyuan" filterable clearable allow-create
                         default-first-option placeholder=" " style="width: 100%">
                <el-option v-for="b in dicts.banzu" :key="b.id" :label="b.name" :value="b.name" />
              </el-select>
            </el-form-item>

            <!-- 主材 / 备注：标签独占一行、紫色，textarea 通栏 -->
            <div class="gd-full gd-ta">
              <div class="gd-ta-label gd-click-label" title="点击查看领料明细"
                   @click="openDetails">主材（点击查看）:</div>
              <el-input v-model="form.cailiao" type="textarea" :rows="3" />
            </div>
            <div class="gd-full gd-ta">
              <div class="gd-ta-label">备注:</div>
              <el-input v-model="form.beizhu" type="textarea" :rows="3" />
            </div>

            <div class="gd-full gd-form-foot">
              <span class="gd-required-tip"><i class="gd-req">*</i> 为必填字段</span>
            </div>
          </div>
        </el-form>
      </div>
      <template #footer>
        <el-button type="primary" :loading="saving" @click="submit(false)">提交</el-button>
        <el-button v-if="dialogMode === 'add'" :loading="saving" @click="submit(true)">提交并继续添加</el-button>
        <el-button @click="closeDialog">取消</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 领料明细 ==================== -->
    <el-dialog v-model="detailVisible" :title="`工单号 ${detailNo} 领料明细`" width="min(1024px, calc(100vw - 40px))"
               append-to-body class="gd-sub-dialog">
      <el-table v-loading="detailLoading" :data="detailRows" size="small" border stripe height="420">
        <el-table-column prop="MaterialName" label="材料名称" min-width="180" />
        <el-table-column prop="Model" label="型号" width="110" align="center" />
        <el-table-column prop="Spec" label="规格" width="110" align="center" />
        <el-table-column label="大口径" width="90" align="center">
          <template #default="{ row }">
            <span v-if="row.dakoujing === 'on'" class="gd-badge">是</span>
          </template>
        </el-table-column>
        <el-table-column label="数量" width="90" align="center">
          <template #default="{ row }">{{ Number(row.Quantity || 0).toFixed(1) }}</template>
        </el-table-column>
        <el-table-column prop="Unit" label="单位" width="90" align="center" />
        <el-table-column prop="CreatedTime" label="创建时间" width="150" align="center" />
      </el-table>
      <template #footer><el-button size="small" @click="detailVisible = false">关闭</el-button></template>
    </el-dialog>

    <!-- ==================== 抢修班组名单 ==================== -->
    <el-dialog v-model="qxVisible" title="抢修人员编辑" width="min(600px, calc(100vw - 40px))"
               append-to-body class="gd-sub-dialog">
      <div class="gd-qx-top">
        <el-input v-model="qxKeyword" size="small" clearable placeholder="搜索姓名" style="width: 180px"
                  @keyup.enter="loadQx" />
        <el-button size="small" :icon="'Search'" @click="loadQx">搜索</el-button>
      </div>
      <el-table v-loading="qxLoading" :data="qxRows" size="small" border stripe height="320"
                highlight-current-row @row-click="(r) => { qxSelected = r; qxName = r.name }">
        <el-table-column prop="id" label="ID" width="80" align="center" />
        <el-table-column prop="name" label="姓名" min-width="200" />
        <template #empty>本部门暂无抢修人员／在下方输入姓名后点「新增」即可添加</template>
      </el-table>
      <div class="gd-qx-bottom">
        <el-input v-model="qxName" size="small" clearable placeholder="姓名" style="width: 180px" />
        <el-button size="small" type="primary" @click="qxAdd">新增</el-button>
        <el-button size="small" @click="qxEdit">修改</el-button>
        <el-button size="small" @click="qxDelete">删除</el-button>
      </div>
      <template #footer><el-button size="small" @click="qxVisible = false">关闭</el-button></template>
    </el-dialog>

    <!-- ==================== 外部工单详情抽屉(照抄 workorder) ==================== -->
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
  </div>
</template>

<style scoped>
.gd-page {
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
.gd-banner {
  flex: 0 0 auto;
  background: linear-gradient(90deg, #2c3e6b, #5645d4);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 1px;
  border-radius: 5px;
  padding: 6px 16px;
}
.gd-count { font-size: 12px; font-weight: 400; opacity: .85; letter-spacing: 0; }
.gd-search {
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
.gd-kw { width: 220px; }
.gd-label { font-size: 12px; color: #5a5752; }
.gd-toolbar { flex: 0 0 auto; display: flex; align-items: center; gap: 6px; }
.gd-tip { margin-left: auto; font-size: 12px; color: #909399; }
.gd-table-wrap { flex: 1 1 auto; min-height: 0; overflow: hidden; }
.gd-pager { flex: 0 0 auto; display: flex; justify-content: flex-end; }
.gd-page :deep(.el-table--small .el-table__cell) { padding: 2px 0; }
.gd-page :deep(.el-table .cell) { line-height: 20px; padding: 0 4px; }
.gd-page :deep(.el-table__header-wrapper th) { padding: 3px 0; }
.gd-page :deep(.gd-row-large td.el-table__cell) {
  background: #fff1f0 !important;
  color: #b3261e;
}
.gd-link { color: #5645d4; text-decoration: underline; cursor: pointer; }
.gd-page :deep(.hl) {
  background: rgba(83, 58, 253, .18);
  color: #6a4a00;
  border-radius: 2px;
  padding: 0 1px;
}
.gd-badge {
  display: inline-block; padding: 1px 8px; border-radius: 10px;
  background: #1e9fff; color: #fff; font-size: 11px;
}
.gd-qx-top, .gd-qx-bottom { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.gd-qx-bottom { margin: 10px 0 0; }
/* 工单详情抽屉:照抄 workorder/WorkOrderManage.vue 与 jcxt/JcxtManage.vue 的 .wo-* 同一套视觉 */
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
</style>

<!-- 弹窗被 teleport 到 body,scoped 选择器够不到,按项目约定用非 scoped + 类名前缀 -->
<style>
/* ===== 添加/编辑弹窗：照旧 Gongdan/Index.cshtml #addDiv（紫题头 + 灰底白卡） =====
   弹窗 append-to-body、下拉/时间格子 teleport 到 body，样式必须写在非 scoped 块并加类名前缀 */
.gd-dialog {
  padding: 0 !important; /* 去掉 el-dialog 四周 16px 内边距，题头/灰底/按钮栏全部贴边 */
  border-radius: 14px !important;
  overflow: hidden !important;
  background: #f3f2f0; /* 紫题头圆角外露出灰底，与旧图一致 */
  box-shadow: 0 16px 28px rgba(16, 24, 40, .22), 0 2px 6px rgba(16, 24, 40, .08) !important;
}
.gd-dialog .el-dialog__header {
  position: relative; /* 关闭钮 absolute 的基准，否则会相对整个弹窗定位到右侧中部 */
  height: 52px; box-sizing: border-box;
  display: flex; align-items: center; justify-content: center;
  /* dialog 已 padding:0，紫色通栏自然贴顶贴边 */
  margin: 0 !important; width: 100%; padding: 0 16px !important;
  background: #5645d4 !important;
  border-radius: 14px 14px 0 0 !important;
}
.gd-dialog .el-dialog__title {
  color: #fff; font-size: 16px; font-weight: 600; letter-spacing: 1px; line-height: 52px;
}
.gd-dialog .el-dialog__headerbtn {
  top: 50% !important; right: 10px !important; transform: translateY(-50%);
  width: 20px; height: 20px; border-radius: 50%; background: #fff;
  box-shadow: 0 1px 3px rgba(28, 30, 84, .35);
}
.gd-dialog .el-dialog__headerbtn:hover { background: #e9e4ff !important; }
.gd-dialog .el-dialog__headerbtn .el-dialog__close { color: #5645d4 !important; font-size: 12px; }
.gd-dialog .el-dialog__body { background: #f3f2f0; padding: 10px 14px 8px !important; }
.gd-dialog .el-dialog__footer {
  height: 56px; box-sizing: border-box;
  display: flex; align-items: center; justify-content: flex-end; gap: 8px;
  padding: 0 16px !important; background: #fff; border-top: 1px solid #efedea !important;
}
.gd-dialog .el-dialog__footer .el-button {
  height: 32px; margin: 0; padding: 0 12px; border-radius: 8px; font-size: 13px;
  background: #fff; border-color: #e0dcd7; color: #3d3a35;
  box-shadow: 0 1px 2px rgba(16, 24, 40, .04);
}
.gd-dialog .el-dialog__footer .el-button:hover { background: #faf9f7; border-color: #cfcabf; }
.gd-dialog .el-dialog__footer .el-button--primary,
.gd-dialog .el-dialog__footer .el-button--primary:hover {
  background: linear-gradient(135deg, #6d5ae0, #5645d4) !important;
  border-color: #4b3bc0 !important; color: #fff !important;
  box-shadow: 0 2px 8px rgba(86, 69, 212, .32);
}

/* 白色表单卡片 */
.gd-card {
  background: #fff; border: none; border-radius: 12px; padding: 14px 16px;
  box-shadow: 0 1px 2px rgba(16, 24, 40, .04), 0 4px 14px rgba(16, 24, 40, .05);
}
.gd-form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px 16px; align-content: start; }
.gd-full { grid-column: 1 / -1; }
.gd-form .el-form-item { margin-bottom: 0; align-items: center; }
.gd-form .el-form-item__label {
  flex: 0 0 72px; width: 72px; height: 32px; line-height: 32px;
  margin-right: 4px !important; padding: 0 !important;
  display: inline-flex; align-items: center; justify-content: flex-start;
  color: #5a5752; font-size: 12px; font-weight: 500; text-align: left;
}
.gd-form .el-form-item.is-required .el-form-item__label::before { color: #e23c3c; margin-right: 2px; }
.gd-form .el-form-item__content { min-width: 0; line-height: 32px; }

/* 控件：旧图输入框物理 47px ≈ 32px CSS，胶囊圆角 16px（40px 是过高版本） */
.gd-dialog .el-input__wrapper,
.gd-dialog .el-select__wrapper {
  min-height: 32px !important; height: 32px; border-radius: 16px !important;
  padding: 0 14px; background: #fff;
  box-shadow: 0 0 0 1px #ddd9d3 inset !important;
}
.gd-dialog .el-input__wrapper:hover,
.gd-dialog .el-select__wrapper:hover {
  box-shadow: 0 0 0 1px #5645d4 inset, 0 0 5px rgba(86, 69, 212, .25) !important;
}
.gd-dialog .el-input__wrapper.is-focus,
.gd-dialog .el-select__wrapper.is-focused {
  box-shadow: 0 0 0 1px #5645d4 inset, 0 0 6px rgba(86, 69, 212, .4) !important;
}
.gd-dialog .el-input__inner, .gd-dialog .el-select__placeholder {
  height: 30px; line-height: 30px; font-size: 13px; color: #1b1d21;
}
/* 已选中的值保持深色；未选值时的占位提示必须是灰色（Element Plus 的 .is-transparent） */
.gd-dialog .el-select__placeholder.is-transparent,
.gd-dialog .el-input__inner::placeholder {
  color: var(--el-text-color-placeholder, #a8abb2);
}
.gd-dialog .el-textarea__inner {
  min-height: 88px !important; border-radius: 8px !important;
  padding: 8px 10px; font-size: 13px; line-height: 1.6; color: #1b1d21;
  box-shadow: 0 0 0 1px #ddd9d3 inset !important;
}
.gd-dialog .el-textarea__inner:focus {
  box-shadow: 0 0 0 1px #5645d4 inset, 0 0 6px rgba(86, 69, 212, .4) !important;
}

/* 日期框缩短 + 日历图标靠右 + 时:分按钮 */
.gd-dt-row { display: flex; align-items: center; gap: 8px; width: 100%; }
.gd-date { flex: 1 1 0; min-width: 0; }
.gd-date .el-input__wrapper { padding: 0 30px 0 14px !important; }
.gd-date .el-input__prefix {
  position: absolute; right: 10px; left: auto !important; top: 50%;
  transform: translateY(-50%); width: 18px; color: #8a867f;
}
.gd-time-input {
  flex: 0 0 74px; width: 74px; height: 32px; box-sizing: border-box;
  text-align: center; font-size: 13px; color: #1b1d21; background: #fff;
  border: 1px solid #ddd9d3; border-radius: 8px; padding: 0 6px; outline: none;
}
.gd-time-input::placeholder { color: #8a867f; }
.gd-time-input:hover { border-color: #5645d4; box-shadow: 0 0 5px rgba(86, 69, 212, .3); }
.gd-time-input:focus { border-color: #5645d4; box-shadow: 0 0 6px rgba(86, 69, 212, .45); }
/* 时:分格子面板（照旧 tp-panel：小时 24 格 / 分钟 60 格，6 列） */
.gd-time-popper.el-popper {
  padding: 8px !important; border: 1px solid #95b8e7; border-radius: 4px;
  box-shadow: 2px 2px 10px rgba(0, 0, 0, .25);
}
.gd-tp-title { font-weight: 700; margin: 4px 0 3px; font-size: 12px; color: #0e2d5f; }
.gd-tp-grid { display: grid; grid-template-columns: repeat(6, 1fr); gap: 3px; }
.gd-tp-cell {
  text-align: center; padding: 4px 0; font-size: 13px; color: #0e2d5f;
  background: #f5f7fa; border: 1px solid #d3e0f1; border-radius: 3px;
  cursor: pointer; user-select: none;
}
.gd-tp-cell:hover { background: #e0ecff; border-color: #95b8e7; }
.gd-tp-cell.sel { background: #4db3ff; color: #fff; border-color: #2f8fe0; }

/* 工时提示 / 通栏文本域标签 / 必填说明 */
.gd-inline { display: flex; align-items: center; gap: 10px; width: 100%; }
.gd-minute { flex: 0 0 62%; }
.gd-duration {
  flex: 1; min-width: 0; text-align: center; white-space: nowrap; line-height: 1.4;
  font-size: 11px; color: #5645d4;
  background: #f2f0fd; border: 1px solid #ddd8f7; border-radius: 6px; padding: 4px 6px;
}
.gd-ta { display: flex; flex-direction: column; gap: 6px; }
.gd-ta-label { font-size: 12px; font-weight: 500; color: #5645d4; }
.gd-click-label { cursor: pointer; text-decoration: underline; }
.gd-form-foot { display: flex; align-items: center; gap: 10px; font-size: 12px; color: #8a867f; }
.gd-required-tip { margin-left: 76px; }
.gd-req { color: #e23c3c; font-weight: 700; font-style: normal; margin-right: 4px; }

/* 字典下拉选项 ✖（teleport 到 body） */
.gd-option { display: flex; align-items: center; justify-content: space-between; }
.gd-option-del { color: #e23c3c; font-size: 12px; padding: 0 4px; }
.gd-sub-dialog .el-dialog__header {
  background: linear-gradient(180deg, #fbfaff, #fff);
  border-left: 4px solid #5645d4;
  margin: 0; padding: 12px 16px;
}
.gd-sub-dialog .el-dialog__title { font-size: 14px; font-weight: 600; }
</style>
