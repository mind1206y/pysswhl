<script setup>
/** 稽查系统(照旧 jcxt/Index.cshtml + addFrmShow.cshtml 1:1 复刻) */
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts'
import {
  addJcxx, deleteJcImage, deleteJcxx, downloadJcTemplate, exportJcAll,
  exportJcMe, exportJcReward, getExportColumns, getJcImageToken, getJcxxDetail,
  getJcxxDicts, getPie, getGongdanImages, getGongdanInfo, importJcReport, linkJcdan,
  listJcxx, listJcdanForJcxx, recallJcxxOne, recallJcxxRows, selectAllExportColumns,
  selectExportColumn, deleteExportColumn, submitJcxxOne, submitJcxxRows,
  suggestWeizhangren, unlinkJcdan, updateJcxx, uploadJcImage,
} from '@/api/jcxt'

// ==================== 筛选 ====================
const filters = reactive({
  sousou: '', filterType: 'custom', selectedMonth: '', rq: firstOfMonth(),
  rqend: today(), rqsx: '', lbid: '', jblb: '', guanjing: '', bmid: null,
  tijiao: false, px: false, dg: false, taoyi: false, nongcun: false,
})
const dicts = reactive({
  departments: [], wzleibie: [], jubaoleibie: [], zhuijiaobm: [], zhuangtai: [],
  zhixingqingkuang: [], xinxilaiyuan: [], nongcunjicha: [], guancai: [],
  guanjing: [], danjia: [], rqsx: [], export_fields: [], export_cols: [],
  default_bmid: null, show_jl: false,
})
const resetting = ref(false)

function firstOfMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}
function today() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// ==================== 列表 ====================
const tableRef = ref()
const rows = ref([])
const total = ref(0)
const footer = ref(null)
const page = reactive({ current: 1, size: 30 })
const loading = ref(false)
const searchKey = ref('')

const allColumns = [
  { field: 'spurl', title: '提交', width: 44 },
  { field: 'gongdanhao', title: '工单号', width: 80 },
  { field: 'weizhangriqi', title: '违章日期', width: 90 },
  { field: 'weizhangren', title: '违章单位', width: 170, min: true },
  { field: 'weizhangdianhua', title: '违章电话', width: 100 },
  { field: 'wzleibie', title: '违章类别', width: 120 },
  { field: 'weizhangdizhi', title: '违章地点', width: 180, min: true },
  { field: 'weizhangneirong', title: '违章内容', width: 240, min: true },
  { field: 'guanjing', title: '管径', width: 70 },
  { field: 'chuliriqi', title: '处理日期', width: 90 },
  { field: 'zhuijiaoshuiliang', title: '追缴水量', width: 85 },
  { field: 'zhuijiaoshuifei', title: '追缴水费', width: 85 },
  { field: 'zhuijiaogongliaofei', title: '追缴工料费', width: 90 },
  { field: 'ze', title: '追缴总额', width: 85 },
  { field: 'zhuijiaobm', title: '追缴人', width: 70 },
  { field: 'peibiaofei', title: '赔表费', width: 70 },
  { field: 'nongcunjicha', title: '农村稽查', width: 80 },
  { field: 'zhixingqingkuang', title: '是否逃逸', width: 75 },
  { field: 'zhuangtai', title: '处理状态', width: 80 },
  { field: 'jubaoleibie', title: '举报类别', width: 85 },
  { field: 'jubaoren', title: '举报人', width: 80 },
  { field: 'jbjiangli', title: '举报奖励', width: 80 },
  { field: 'banjietianshu', title: '办结天数', width: 75 },
  { field: 'zuihougengxin', title: '最后更新', width: 150 },
  { field: 'caozuoname', title: '操作员', width: 70 },
  { field: 'bumen', title: '部门', width: 85 },
  { field: 'caozuoriqi', title: '建单日期', width: 150 },
  { field: 'tps', title: '图片', width: 70 },
  { field: 'spren', title: '提交人', width: 70 },
  { field: 'spdate', title: '提交时间', width: 140 },
  { field: 'spzt', title: '状态', width: 76 },
]
const COLUMN_KEY = 'jcxt_selected_columns'
const colDialog = ref(false)
const selectedCols = ref(allColumns.map(c => c.field))
watchColumnStorage()

function watchColumnStorage() {
  try {
    const saved = JSON.parse(localStorage.getItem(COLUMN_KEY) || 'null')
    if (Array.isArray(saved) && saved.length) {
      selectedCols.value = allColumns.map(c => c.field).filter(f => saved.includes(f))
    }
  } catch { /* 忽略损坏的存储 */ }
}
const visibleColumns = computed(() =>
  allColumns.filter(c => selectedCols.value.includes(c.field)))
function saveCols() {
  localStorage.setItem(COLUMN_KEY, JSON.stringify(selectedCols.value))
}

async function load() {
  loading.value = true
  try {
    const params = { ...filters, page: page.current, size: page.size,
      bmid: filters.bmid || undefined }
    const res = await listJcxx(params)
    rows.value = res.items
    total.value = res.total
    footer.value = res.footer && res.footer[0] ? res.footer[0] : null
    await nextTick()
    tableRef.value?.clearSelection()
  } finally {
    loading.value = false
  }
}
function doSearch() {
  page.current = 1
  searchKey.value = filters.sousou
  load()
}
function resetFilters() {
  resetting.value = true
  Object.assign(filters, {
    sousou: '', filterType: 'custom', selectedMonth: '', rq: firstOfMonth(),
    rqend: today(), rqsx: '', lbid: '', jblb: '', guanjing: '', bmid: null,
    tijiao: false, px: false, dg: false, taoyi: false, nongcun: false,
  })
  setTimeout(() => { resetting.value = false; doSearch() }, 0)
}
function onSwitchChange() {
  if (!resetting.value) doSearch()
}

function summaryMethod({ columns }) {
  if (!footer.value) return []
  const map = {
    ze: footer.value.ze, zhuijiaoshuifei: footer.value.zhuijiaoshuifei,
    zhuijiaogongliaofei: footer.value.zhuijiaogongliaofei,
    zhuijiaoshuiliang: footer.value.zhuijiaoshuiliang,
    jbjiangli: footer.value.jbjiangli,
  }
  return columns.map((c) => {
    if (c.property === 'ze' || c.property in map) {
      const v = map[c.property]
      return v != null && v !== 0 ? String(v) : (c.property === 'ze' ? '合计' : '')
    }
    if (c.type === 'selection') return '合计'
    return ''
  })
}

function rowClass({ row }) {
  if (row.zhuangtai === '已完结' || row.zhixingqingkuang === '逃逸') return 'row-done'
  return ''
}

// 图片:短令牌访问
const tokenCache = new Map()
async function openImage(pic, row) {
  let url = tokenCache.get(pic.id)
  if (!url) {
    const res = await getJcImageToken(pic.id)
    url = res.url
    tokenCache.set(pic.id, url)
  }
  window.open(url, '_blank')
}

// ==================== 提交/撤回/删除 ====================
const oneSubmitBusy = ref(false)
async function oneSubmit(row) {
  if (oneSubmitBusy.value) return  // 防双击重复提交
  oneSubmitBusy.value = true
  try {
    await submitJcxxOne(row.ID)
    ElMessage.success('已提交')
    load()
  } catch (e) { /* request.js 已提示 */ }
  finally { oneSubmitBusy.value = false }
}
async function oneRecall(row) {
  try {
    await recallJcxxOne(row.ID)
    ElMessage.success('已撤回')
    load()
  } catch (e) { /* */ }
}
function selection() {
  return tableRef.value?.getSelectionRows() || []
}
const batchSubmitBusy = ref(false)
async function batchSubmit() {
  if (batchSubmitBusy.value) return  // 防双击重复提交
  const ids = selection().map(r => r.ID).join(',')
  if (!ids) return ElMessage.warning('请先勾选记录')
  batchSubmitBusy.value = true
  try {
    const res = await submitJcxxRows(ids)
    let msg = `已提交 ${res.ok_count} 条`
    if (res.passed) msg += `,${res.passed} 条已审核通过跳过`
    if (res.not_mine) msg += `,${res.not_mine} 条非本人建单跳过`
    ElMessage.success(msg)
    load()
  } catch (e) { /* */ }
  finally { batchSubmitBusy.value = false }
}
async function batchRecall() {
  const ids = selection().map(r => r.ID).join(',')
  if (!ids) return ElMessage.warning('请先勾选记录')
  try {
    const res = await recallJcxxRows(ids)
    ElMessage.success(`已撤回 ${res.ok_count} 条${res.passed ? `,${res.passed} 条已审核通过跳过` : ''}`)
    load()
  } catch (e) { /* */ }
}
async function batchDelete() {
  const sel = selection()
  if (sel.length !== 1) return ElMessage.warning('请勾选一条记录')
  const row = sel[0]
  try {
    await ElMessageBox.confirm('确定删除该条稽查记录?', '提示', { type: 'warning' })
  } catch { return }
  try {
    await deleteJcxx(row.ID)
    ElMessage.success('已删除')
    load()
  } catch (e) { /* */ }
}

// ==================== 添加/编辑弹窗 ====================
const dlg = ref(false)
const dlgMode = ref('add')
const dlgTitle = computed(() => (dlgMode.value === 'add' ? '添加稽查信息' : '修改稽查信息'))
const saving = ref(false)
const formRef = ref()
const form = reactive(emptyForm())
const pendingFiles = ref([]) // 添加模式下待上传图片
const picTokenUrls = ref({}) // 编辑模式图片 id -> token url

function emptyForm() {
  return {
    id: null, gongdanhao: '', weizhangriqi: '', chuliriqi: '', weizhangren: '',
    weizhangdianhua: '', weizhangdizhi: '', weizhangneirong: '', wzleibie: '',
    guanjing: '', guancai: '', nongcunjicha: '', jubaoren: '', jubaoleibie: '',
    zhuijiaobm: '稽查部', zhuijiaoshuiliang: null, danjia: '',
    zhuijiaoshuifei: null, zhuijiaogongliaofei: null, peibiaofei: null,
    beizhu: '', spzt: '', caozuoname: '',
    // 破管计算器(非提交字段)
    pm_chang: '', pm_kuan: '', pm_mianji: '', pm_time: '', pm_compre: '', pm_zsl: '',
    // 图片
    pics: [],
  }
}
const formRules = {
  weizhangriqi: [{ required: true, message: '违章日期为必填项', trigger: 'change' }],
}

function totalAmount() {
  const s = v => (parseFloat(v) || 0)
  return (s(form.zhuijiaoshuifei) + s(form.zhuijiaogongliaofei) + s(form.peibiaofei)).toFixed(2)
}
function onShuiliangInput() {
  const d = parseFloat(form.danjia)
  if (d > 0 && form.zhuijiaoshuiliang != null && form.zhuijiaoshuiliang !== '') {
    form.zhuijiaoshuifei = (form.zhuijiaoshuiliang * d).toFixed(2)
  }
}
function onWzleibieChange(v) {
  if (v === '施工挖破水管') form.weizhangneirong = '施工挖破'
  else if (v) form.weizhangneirong = v
  else form.weizhangneirong = ''
}
function onGuanjingClick() {
  if (form.wzleibie === '施工挖破水管' && form.guanjing) {
    form.weizhangneirong = '施工挖破' + form.guanjing + '水管'
  }
}
function onJubaoleibieChange(v) {
  if (v === '肇事举报') form.jubaoren = '肇事者'
}
function onDanjiaChange() { onShuiliangInput() }

// 破管计算器
function jsmj() {
  const c = parseFloat(form.pm_chang) || 0
  const k = parseFloat(form.pm_kuan) || 0
  form.pm_mianji = ((c * k) / 10000).toFixed(4)
  jssl()
}
function jssl() {
  const mj = parseFloat(form.pm_mianji) || 0
  const t = parseFloat(form.pm_time) || 0
  const p = parseFloat(form.pm_compre) || 0
  if (mj > 0 && t > 0 && p > 0) {
    form.pm_zsl = (0.62 * mj * Math.sqrt(2 * 9.8 * p * 100) * 3600 * t).toFixed(2)
  } else {
    form.pm_zsl = ''
  }
}
function qingkong() {
  Object.assign(form, { pm_chang: '', pm_kuan: '', pm_mianji: '', pm_time: '', pm_compre: '', pm_zsl: '' })
}

// 违章单位 autocomplete
const wzrSuggestions = ref([])
async function queryWzr(queryString, cb) {
  if (!queryString) return cb([])
  try {
    const res = await suggestWeizhangren(queryString)
    cb(res.map(r => ({ value: r.duixiang })))
  } catch { cb([]) }
}

// 工单号失焦回填
async function onGongdanhaoBlur() {
  if (!form.gongdanhao) return
  try {
    const res = await getGongdanInfo(form.gongdanhao)
    if (res.success) {
      if (res.data.ksriqi) form.weizhangriqi = res.data.ksriqi?.slice(0, 10)
      if (res.data.dizhi) form.weizhangdizhi = res.data.dizhi
    }
  } catch { /* 未迁移/未找到不提示 */ }
}

const activeTab = ref('base')

function openAdd() {
  Object.assign(form, emptyForm())
  pendingFiles.value = []
  picTokenUrls.value = {}
  dlgMode.value = 'add'
  activeTab.value = 'base'
  dlg.value = true
}

async function openEdit(row) {
  const res = await getJcxxDetail(row.ID)
  Object.assign(form, emptyForm(), {
    id: res.id,
    gongdanhao: res.gongdanhao || '',
    weizhangriqi: res.weizhangriqi || '',
    chuliriqi: res.chuliriqi || '',
    weizhangren: res.weizhangren || '',
    weizhangdianhua: res.weizhangdianhua || '',
    weizhangdizhi: res.weizhangdizhi || '',
    weizhangneirong: res.weizhangneirong || '',
    wzleibie: res.wzleibie || '',
    guanjing: res.guanjing || '',
    guancai: res.guancai || '',
    nongcunjicha: res.nongcunjicha || '',
    jubaoren: res.jubaoren || '',
    jubaoleibie: res.jubaoleibie || '',
    zhuijiaobm: res.zhuijiaobm || '稽查部',
    zhuijiaoshuiliang: res.zhuijiaoshuiliang,
    danjia: res.danjia != null ? String(res.danjia) : '',
    zhuijiaoshuifei: res.zhuijiaoshuifei,
    zhuijiaogongliaofei: res.zhuijiaogongliaofei,
    peibiaofei: res.peibiaofei,
    beizhu: res.beizhu || '',
    spzt: res.spzt || '',
    caozuoname: res.caozuoname || '',
    pics: res.tps || [],
  })
  pendingFiles.value = []
  picTokenUrls.value = {}
  // 为每张图取短令牌
  for (const p of form.pics) {
    try {
      const t = await getJcImageToken(p.id)
      picTokenUrls.value[p.id] = t.url
    } catch { /* 缺图占位 */ }
  }
  dlgMode.value = 'edit'
  activeTab.value = 'base'
  dlg.value = true
  await nextTick()
  loadJcdList()
}

async function save() {
  if (saving.value) return  // 防双击重复提交
  try {
    await formRef.value.validate()
  } catch { return }
  const payload = {
    gongdanhao: form.gongdanhao || null,
    weizhangriqi: form.weizhangriqi || null,
    chuliriqi: form.chuliriqi || null,
    weizhangren: form.weizhangren || null,
    weizhangdianhua: form.weizhangdianhua || null,
    weizhangdizhi: form.weizhangdizhi || null,
    weizhangneirong: form.weizhangneirong || null,
    wzleibie: form.wzleibie || null,
    guanjing: form.guanjing || null,
    guancai: form.guancai || null,
    nongcunjicha: form.nongcunjicha || null,
    jubaoren: form.jubaoren || null,
    jubaoleibie: form.jubaoleibie || null,
    zhuijiaobm: form.zhuijiaobm || null,
    zhuijiaoshuiliang: form.zhuijiaoshuiliang || null,
    danjia: form.danjia || null,
    zhuijiaoshuifei: form.zhuijiaoshuifei || null,
    zhuijiaogongliaofei: form.zhuijiaogongliaofei || null,
    peibiaofei: form.peibiaofei || null,
    beizhu: form.beizhu || null,
  }
  saving.value = true
  try {
    let rid
    if (dlgMode.value === 'add') {
      const res = await addJcxx(payload)
      rid = res.id
    } else {
      payload.spzt = form.spzt
      payload.caozuoname = form.caozuoname
      await updateJcxx(form.id, payload)
      rid = form.id
    }
    // 上传待传图片
    for (const f of pendingFiles.value) {
      try { await uploadJcImage(rid, f) } catch { /* 单张失败不阻断 */ }
    }
    ElMessage.success('保存成功')
    dlg.value = false
    load()
  } catch (e) { /* */ } finally {
    saving.value = false
  }
}

// 图片选择(保存后上传)
function onPickImages(e) {
  const files = Array.from(e.target.files || [])
  for (const f of files) {
    const ext = f.name.toLowerCase().split('.').pop()
    if (!['jpg', 'jpeg'].includes(ext)) {
      ElMessage.warning('不是图片(仅支持 jpg)')
      continue
    }
    pendingFiles.value.push(f)
  }
  e.target.value = ''
}
function removePending(idx) { pendingFiles.value.splice(idx, 1) }
async function removePic(pic) {
  try {
    await ElMessageBox.confirm('确定删除该图片?', '提示', { type: 'warning' })
  } catch { return }
  await deleteJcImage(pic.id)
  form.pics = form.pics.filter(p => p.id !== pic.id)
  ElMessage.success('已删除')
}

// ==================== 关联稽查单(编辑弹窗) ====================
const jcdRows = ref([])
const jcdTotal = ref(0)
const jcdPage = reactive({ current: 1, size: 10 })
const jcdSearch = ref('')
const jcdLoading = ref(false)
async function loadJcdList() {
  if (dlgMode.value !== 'edit' || !form.id) return
  jcdLoading.value = true
  try {
    const res = await listJcdanForJcxx({
      jcxxdanid: form.id, sousou: jcdSearch.value,
      page: jcdPage.current, size: jcdPage.size,
    })
    jcdRows.value = res.items
    jcdTotal.value = res.total
  } finally {
    jcdLoading.value = false
  }
}
async function toggleLink(row) {
  try {
    if (row.colo === '0') {
      await linkJcdan({ id: row.id, jcid: form.id })
      ElMessage.success('已关联')
    } else {
      await unlinkJcdan({ id: row.id, jcid: form.id })
      ElMessage.success('已取消关联')
    }
    loadJcdList()
  } catch { /* */ }
}

// ==================== 导出 / 导入 ====================
const exportColsDialog = ref(false)
function exportParams() {
  return { ...filters, bmid: filters.bmid || undefined }
}
async function onExportAll() {
  try { await exportJcAll(exportParams()) } catch { /* */ }
}
async function onExportMe() {
  exportColsDialog.value = true
}
async function onColToggle(field, checked) {
  try {
    if (checked) await selectExportColumn(field)
    else await deleteExportColumn(field)
    if (checked && !dicts.export_cols.includes(field)) dicts.export_cols.push(field)
    if (!checked) dicts.export_cols = dicts.export_cols.filter(c => c !== field)
  } catch { /* */ }
}
const masterSwitch = ref(false)
async function onMasterSwitch(v) {
  try {
    await selectAllExportColumns(dicts.export_fields.map(f => f.ziduan), v)
    dicts.export_cols = v ? dicts.export_fields.map(f => f.ziduan) : []
  } catch { /* */ }
}
async function doExportMe() {
  if (!dicts.export_cols.length) {
    return ElMessage.warning('没有选字段')
  }
  try { await exportJcMe(exportParams()) } catch { /* */ }
}
async function onRewardExport() {
  try { await exportJcReward(filters.rqend) } catch { /* */ }
}
const importInput = ref()
function onImportPick() { importInput.value?.click() }
async function onImportFile(e) {
  const f = e.target.files[0]
  e.target.value = ''
  if (!f) return
  if (!(f.name.includes('稽查报表') && /\.(xls|xlsx)$/i.test(f.name))) {
    return ElMessage.error('文件名须为「稽查报表.xls」')
  }
  try {
    const res = await importJcReport(f)
    ElMessage.success(res.message || '导入完成')
    load()
  } catch { /* */ }
}

// ==================== 图表抽屉 ====================
const chartDrawer = ref(false)
const chartTab = ref('pie')
const chartLb = ref('5')
const chartYue = ref([])
const chartBmid = ref(0)
let pieChart = null
let barChart = null
const chartYear = ref(new Date().getFullYear())

const lbOptions = [
  { value: '5', label: '追缴水费(元)' },
  { value: '6', label: '追缴工料(元)' },
  { value: '7', label: '追缴水量(吨)' },
  { value: '1', label: '追缴总额(元)' },
  { value: '2', label: '稽查记录数(条)' },
  { value: '3', label: '违章类别统计(条)' },
  { value: '4', label: '违章类别金额(元)' },
  { value: '8', label: '管径(件)' },
]
function openChart() {
  chartDrawer.value = true
  nextTick(() => renderCharts())
}
function renderCharts() {
  const pieEl = document.getElementById('jcxt-pie')
  const barEl = document.getElementById('jcxt-bar')
  if (!pieEl || !barEl) return
  pieChart = pieChart || echarts.init(pieEl)
  barChart = barChart || echarts.init(barEl)
  const yue = chartYue.value.length ? chartYue.value.join(',') : '0'
  getPie({ rq: chartYear.value, leib: Number(chartLb.value), yue, bmid: chartBmid.value })
    .then((res) => {
      const cats = res.category_statistics?.categories2 || []
      pieChart.setOption({
        tooltip: { trigger: 'item' },
        legend: { type: 'scroll', orient: 'vertical', right: 0, top: 10 },
        series: [{
          type: 'pie', radius: ['35%', '65%'], center: ['40%', '50%'],
          data: cats, label: { formatter: '{b}: {c}' },
        }],
      })
      const ms = res.monthly_statistics || {}
      barChart.setOption({
        tooltip: { trigger: 'axis' },
        grid: { left: 60, right: 20, bottom: 30, top: 40 },
        title: { text: `合计:${ms.zong ?? 0}`, left: 'center', textStyle: { fontSize: 13 } },
        xAxis: { type: 'category', data: (ms.monthly_data || []).map(m => m.month) },
        yAxis: { type: 'value' },
        series: [{ type: 'bar', data: (ms.monthly_data || []).map(m => m.value) }],
      })
    })
}
function onChartTab(name) {
  nextTick(() => {
    pieChart?.resize()
    barChart?.resize()
    if (name) renderCharts()
  })
}

// ==================== 工单详情抽屉 ====================
const woDrawer = ref(false)
const woInfo = reactive({
  gongdanhao: '', message: '', loading: false, data: null, images: [],
})
async function viewWorkOrder(no) {
  woInfo.gongdanhao = no || ''
  woInfo.message = ''
  woInfo.data = null
  woInfo.images = []
  woDrawer.value = true
  if (!no) {
    woInfo.message = '工单号为空'
    return
  }
  woInfo.loading = true
  try {
    const res = await getGongdanInfo(no)
    if (res.success && res.data) {
      woInfo.data = res.data
      try {
        const imgRes = await getGongdanImages(res.data.Id || no)
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

onMounted(async () => {
  try {
    const res = await getJcxxDicts()
    Object.assign(dicts, res)
    if (dicts.default_bmid && !filters.bmid) filters.bmid = null
    if (dicts.export_fields.length) {
      masterSwitch.value = dicts.export_cols.length === dicts.export_fields.length
    }
  } catch { /* */ }
  load()
})
</script>

<template>
  <div class="jcxt-page">
    <!-- 筛选工具栏 -->
    <el-card shadow="never" class="filter-card">
      <div class="filter-title">稽查信息汇总表</div>
      <div class="filter-grid">
        <el-input v-model="filters.sousou" placeholder="模糊查询(单位/电话/地址/内容/工单号)"
          clearable style="width: 240px" @keyup.enter="doSearch" @clear="doSearch" />
        <el-select v-model="filters.filterType" style="width: 130px" @change="doSearch">
          <el-option label="自选起止日期" value="custom" />
          <el-option label="本月" value="currentMonth" />
          <el-option label="上月" value="lastMonth" />
          <el-option label="按月份选择" value="selectMonth" />
        </el-select>
        <template v-if="filters.filterType === 'custom'">
          <el-date-picker v-model="filters.rq" type="date" value-format="YYYY-MM-DD"
            placeholder="开始日期" style="width: 130px" @change="doSearch" />
          <el-date-picker v-model="filters.rqend" type="date" value-format="YYYY-MM-DD"
            placeholder="结束日期" style="width: 130px" @change="doSearch" />
        </template>
        <el-date-picker v-if="filters.filterType === 'selectMonth'"
          v-model="filters.selectedMonth" type="month" value-format="YYYY-MM"
          placeholder="选择月份" style="width: 130px" @change="doSearch" />
        <el-select v-model="filters.rqsx" placeholder="日期筛选" clearable
          style="width: 150px" @change="doSearch">
          <el-option v-for="r in dicts.rqsx" :key="r" :label="r" :value="r" />
        </el-select>
        <el-select v-model="filters.lbid" placeholder="违章类别" clearable
          style="width: 150px" @change="doSearch">
          <el-option v-for="w in dicts.wzleibie" :key="w" :label="w" :value="w" />
        </el-select>
        <el-select v-model="filters.bmid" placeholder="选择部门" clearable
          style="width: 140px" @change="doSearch">
          <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
        </el-select>
        <el-select v-model="filters.jblb" placeholder="举报类别" clearable
          style="width: 120px" @change="doSearch">
          <el-option v-for="j in dicts.jubaoleibie" :key="j" :label="j" :value="j" />
        </el-select>
        <el-select v-model="filters.guanjing" placeholder="管径" clearable
          style="width: 120px" @change="doSearch">
          <el-option v-for="g in dicts.guanjing" :key="g" :label="g" :value="g" />
        </el-select>
        <div class="switches">
          <span class="sw"><el-switch v-model="filters.tijiao" @change="onSwitchChange" />提交</span>
          <span class="sw"><el-switch v-model="filters.px" @change="onSwitchChange" />降序</span>
          <span class="sw"><el-switch v-model="filters.dg" @change="onSwitchChange" />300以上</span>
          <span class="sw"><el-switch v-model="filters.taoyi" @change="onSwitchChange" />逃逸</span>
          <span class="sw"><el-switch v-model="filters.nongcun" @change="onSwitchChange" />农村</span>
        </div>
        <div class="btns">
          <el-button type="primary" size="small" @click="doSearch">查询</el-button>
          <el-button size="small" @click="resetFilters">重置</el-button>
        </div>
      </div>
      <div class="toolbar">
        <el-button size="small" type="primary" @click="openAdd">添加</el-button>
        <el-button v-if="!filters.tijiao" size="small" type="success" @click="batchSubmit">提交</el-button>
        <el-button v-else size="small" type="warning" @click="batchRecall">撤回</el-button>
        <el-button size="small" type="danger" @click="batchDelete">删除</el-button>
        <el-button size="small" @click="onExportAll">导出EXCEL</el-button>
        <el-button size="small" @click="onExportMe">导出字段</el-button>
        <el-button size="small" @click="onImportPick">上传报表</el-button>
        <el-button size="small" @click="downloadJcTemplate">下载模板</el-button>
        <el-button v-if="dicts.show_jl" size="small" type="success" @click="onRewardExport">奖励导出</el-button>
        <el-button size="small" @click="openChart">图表</el-button>
        <el-button size="small" @click="colDialog = true">列设置</el-button>
        <input ref="importInput" type="file" accept=".xls,.xlsx" hidden @change="onImportFile">
      </div>
    </el-card>

    <!-- 主表格 -->
    <el-table ref="tableRef" :data="rows" v-loading="loading" class="jc-table"
      row-key="ID" show-summary :summary-method="summaryMethod"
      :row-class-name="rowClass" height="calc(100vh - 320px)" border
      @row-dblclick="(row) => openEdit(row)">
      <el-table-column type="selection" width="38" fixed="left" />
      <el-table-column v-for="c in visibleColumns" :key="c.field" :prop="c.field"
        :label="c.title" :width="c.width" show-overflow-tooltip>
        <template v-if="c.field === 'spurl'" #default="{ row }">
          <el-link v-if="row.spzt === '暂存'" type="primary" :underline="false"
            title="提交售水" @click="oneSubmit(row)">✓</el-link>
          <el-link v-else-if="row.spzt === '待审核'" type="warning" :underline="false"
            title="收回提交" @click="oneRecall(row)">↩</el-link>
          <span v-else-if="row.spzt === '审核通过'" title="审核通过">✔✔</span>
        </template>
        <template v-else-if="c.field === 'gongdanhao'" #default="{ row }">
          <el-link type="primary" :underline="false" @click="viewWorkOrder(row.gongdanhao)">
            {{ row.gongdanhao }}
          </el-link>
        </template>
        <template v-else-if="c.field === 'tps'" #default="{ row }">
          <span v-if="row.tps && row.tps.length" class="pic-icons">
            <el-link v-for="p in row.tps" :key="p.id" :underline="false"
              title="查看图片" @click="openImage(p, row)">🖼</el-link>
          </span>
        </template>
        <template v-else-if="c.field === 'spzt'" #default="{ row }">
          <span v-if="row.spzt === '待审核'" class="sp-tag sp-wait">待审核</span>
          <span v-else-if="row.spzt === '审核通过'" class="sp-tag sp-pass">✔</span>
          <span v-else>{{ row.spzt }}</span>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page.current" v-model:page-size="page.size"
      :total="total" :page-sizes="[30, 100, 300]" layout="total, sizes, prev, pager, next"
      @change="load" />

    <!-- 列设置 -->
    <el-dialog v-model="colDialog" title="显示/隐藏列" width="720px">
      <div class="col-actions">
        <el-button size="small" @click="selectedCols = allColumns.map(c => c.field); saveCols()">全选</el-button>
        <el-button size="small" @click="selectedCols = []; saveCols()">全不选</el-button>
      </div>
      <el-checkbox-group v-model="selectedCols" class="col-grid" @change="saveCols">
        <el-checkbox v-for="c in allColumns" :key="c.field" :value="c.field">
          {{ c.title }}
        </el-checkbox>
      </el-checkbox-group>
    </el-dialog>

    <!-- 添加/编辑弹窗 -->
    <el-dialog v-model="dlg" :title="dlgTitle" width="900px" top="4vh"
      class="jc-form-dialog" :close-on-click-modal="false">
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="90px" size="small">
        <el-tabs v-model="activeTab">
          <el-tab-pane label="基本稽查信息" name="base">
            <div class="grid2">
              <el-form-item label="工单号">
                <el-input v-model="form.gongdanhao" @blur="onGongdanhaoBlur" />
              </el-form-item>
              <el-form-item label="违章日期" required prop="weizhangriqi">
                <el-date-picker v-model="form.weizhangriqi" type="date"
                  value-format="YYYY-MM-DD" style="width: 100%" />
              </el-form-item>
              <el-form-item label="违章单位">
                <el-autocomplete v-model="form.weizhangren" :fetch-suggestions="queryWzr"
                  style="width: 100%" />
              </el-form-item>
              <el-form-item label="单位电话">
                <el-input v-model="form.weizhangdianhua" />
              </el-form-item>
              <el-form-item label="违章地址" class="span2">
                <el-input v-model="form.weizhangdizhi" />
              </el-form-item>
            </div>
          </el-tab-pane>
          <el-tab-pane label="违章类别" name="type">
            <div class="grid2">
              <el-form-item label="违章类别">
                <el-select v-model="form.wzleibie" clearable style="width: 100%"
                  @change="onWzleibieChange">
                  <el-option v-for="w in dicts.wzleibie" :key="w" :label="w" :value="w" />
                </el-select>
              </el-form-item>
              <el-form-item label="选择管径">
                <el-select v-model="form.guanjing" clearable style="width: 100%"
                  @click="onGuanjingClick">
                  <el-option v-for="g in dicts.guanjing" :key="g" :label="g" :value="g" />
                </el-select>
              </el-form-item>
              <el-form-item label="农村稽查">
                <el-select v-model="form.nongcunjicha" clearable style="width: 100%">
                  <el-option label="农村稽查" value="农村稽查" />
                </el-select>
              </el-form-item>
              <el-form-item label="选择管材">
                <el-select v-model="form.guancai" clearable style="width: 100%">
                  <el-option v-for="g in dicts.guancai" :key="g" :label="g" :value="g" />
                </el-select>
              </el-form-item>
              <el-form-item label="违章内容" class="span2">
                <el-input v-model="form.weizhangneirong" type="textarea" :rows="2" />
              </el-form-item>
              <el-form-item label="备注" class="span2">
                <el-input v-model="form.beizhu" type="textarea" :rows="2" />
              </el-form-item>
            </div>
          </el-tab-pane>
          <el-tab-pane label="追缴情况" name="fee">
            <div class="grid2">
              <el-form-item label="处理日期">
                <el-date-picker v-model="form.chuliriqi" type="date"
                  value-format="YYYY-MM-DD" style="width: 100%" />
              </el-form-item>
              <el-form-item label="举报类别">
                <el-select v-model="form.jubaoleibie" clearable style="width: 100%"
                  @change="onJubaoleibieChange">
                  <el-option v-for="j in dicts.jubaoleibie" :key="j" :label="j" :value="j" />
                </el-select>
              </el-form-item>
              <el-form-item label="举报人">
                <el-input v-model="form.jubaoren" />
              </el-form-item>
              <el-form-item label="追缴人">
                <el-input v-model="form.zhuijiaobm" />
              </el-form-item>
              <el-form-item label="追缴水量">
                <el-input v-model="form.zhuijiaoshuiliang" @input="onShuiliangInput" />
              </el-form-item>
              <el-form-item label="水费单价">
                <el-select v-model="form.danjia" clearable style="width: 100%"
                  @change="onDanjiaChange">
                  <el-option v-for="d in dicts.danjia" :key="d" :label="`${d}元`" :value="d" />
                </el-select>
              </el-form-item>
              <el-form-item label="追缴水费">
                <el-input-number v-model="form.zhuijiaoshuifei" :precision="2"
                  :controls="false" style="width: 100%" />
              </el-form-item>
              <el-form-item label="追缴工料费">
                <el-input-number v-model="form.zhuijiaogongliaofei" :precision="2"
                  :controls="false" style="width: 100%" />
              </el-form-item>
              <el-form-item label="赔表费">
                <el-input-number v-model="form.peibiaofei" :precision="2"
                  :controls="false" style="width: 100%" />
              </el-form-item>
              <el-form-item label="费用合计">
                <span class="total-amount">合计金额:{{ totalAmount() }}元</span>
              </el-form-item>
            </div>
            <div class="tip">违章日期为必填项,有处理日期没追缴金额则算逃逸。</div>
          </el-tab-pane>
          <el-tab-pane v-if="dlgMode === 'add'" label="破管计算器" name="calc">
            <div class="grid2">
              <el-form-item label="破管长度cm">
                <el-input v-model="form.pm_chang" @input="jsmj" />
              </el-form-item>
              <el-form-item label="破管宽度cm">
                <el-input v-model="form.pm_kuan" @input="jsmj" />
              </el-form-item>
              <el-form-item label="面积m²">
                <el-input v-model="form.pm_mianji" @input="jssl" />
              </el-form-item>
              <el-form-item label="破管时间h">
                <el-input v-model="form.pm_time" @input="jssl" />
              </el-form-item>
              <el-form-item label="水压MPa">
                <el-input v-model="form.pm_compre" @input="jssl" />
              </el-form-item>
              <el-form-item label="漏损水量吨">
                <el-input v-model="form.pm_zsl" readonly />
              </el-form-item>
            </div>
            <div class="tip">漏损水量 = 0.62 × 面积(m²) × √(2×9.8×水压×100) × 3600 × 时间(h)</div>
          </el-tab-pane>
          <el-tab-pane label="图片" name="pic">
            <div class="pic-toolbar">
              <label class="pick-btn">
                选择图片(jpg)
                <input type="file" accept=".jpg,.jpeg" multiple hidden @change="onPickImages">
              </label>
              <span class="tip-inline">添加模式:图片在保存后自动上传;点击缩略图放大</span>
            </div>
            <div class="pic-list">
              <div v-for="(p, i) in form.pics" :key="p.id" class="pic-item">
                <el-image v-if="picTokenUrls[p.id]" :src="picTokenUrls[p.id]"
                  :preview-src-list="[picTokenUrls[p.id]]" fit="cover"
                  class="pic-thumb" />
                <div v-else class="pic-thumb pic-missing">缺图</div>
                <el-link v-if="dlgMode === 'edit'" type="danger" :underline="false"
                  class="pic-del" @click="removePic(p)">×</el-link>
              </div>
              <div v-for="(f, i) in pendingFiles" :key="'pend' + i" class="pic-item">
                <el-image :src="URL.createObjectURL(f)" fit="cover" class="pic-thumb" />
                <el-link type="danger" :underline="false" class="pic-del"
                  @click="removePending(i)">×</el-link>
              </div>
            </div>
          </el-tab-pane>
          <el-tab-pane v-if="dlgMode === 'edit'" label="关联稽查单" name="jcd">
            <div class="jcd-toolbar">
              <el-input v-model="jcdSearch" placeholder="编号/工单号/地点/描述" clearable
                style="width: 240px" @keyup.enter="loadJcdList" @clear="loadJcdList" />
              <el-button size="small" @click="loadJcdList">查询</el-button>
              <span class="tip-inline">点击行首图标关联/取消关联本稽查信息</span>
            </div>
            <el-table :data="jcdRows" v-loading="jcdLoading" size="small"
              height="300" border>
              <el-table-column width="50">
                <template #default="{ row }">
                  <el-link v-if="row.colo === '0'" type="primary" :underline="false"
                    title="关联本单" @click="toggleLink(row)">○</el-link>
                  <el-link v-else type="danger" :underline="false" title="取消关联"
                    @click="toggleLink(row)">●</el-link>
                </template>
              </el-table-column>
              <el-table-column prop="bianhao" label="编号" width="90" />
              <el-table-column prop="fstime" label="发生时间" width="140" />
              <el-table-column prop="weizhangdanwei" label="违章单位(者)" min-width="150" show-overflow-tooltip />
              <el-table-column prop="nr" label="违章情况描述" min-width="200" show-overflow-tooltip />
            </el-table>
            <el-pagination v-model:current-page="jcdPage.current"
              v-model:page-size="jcdPage.size" :total="jcdTotal" layout="prev, pager, next"
              @change="loadJcdList" />
          </el-tab-pane>
        </el-tabs>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button type="primary" :loading="saving"
          :disabled="dlgMode === 'edit' && form.spzt === '审核通过'"
          @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 导出字段 -->
    <el-dialog v-model="exportColsDialog" title="选择导出字段" width="760px">
      <div class="col-actions">
        <span>全部开或关</span>
        <el-switch v-model="masterSwitch" @change="onMasterSwitch" />
      </div>
      <div class="col-grid">
        <div v-for="f in dicts.export_fields" :key="f.ziduan" class="col-item">
          <el-switch :model-value="dicts.export_cols.includes(f.ziduan)"
            @change="(v) => onColToggle(f.ziduan, v)" />
          <span>{{ f.bt }}</span>
        </div>
      </div>
      <template #footer>
        <el-button type="primary" @click="doExportMe">导出EXCEL</el-button>
        <el-button @click="exportColsDialog = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 图表抽屉 -->
    <el-drawer v-model="chartDrawer" title="稽查统计" size="94%" @open="renderCharts">
      <div class="chart-controls">
        <el-select v-model="chartLb" style="width: 170px" @change="renderCharts">
          <el-option v-for="o in lbOptions" :key="o.value" :label="o.label" :value="o.value" />
        </el-select>
        <el-date-picker v-model="chartYear" type="year" value-format="YYYY"
          style="width: 110px" @change="renderCharts" />
        <el-select v-model="chartBmid" style="width: 150px" @change="renderCharts">
          <el-option label="售水事业部" :value="0" />
          <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
        </el-select>
        <el-select v-model="chartYue" multiple collapse-tags placeholder="月份(不选=全年)"
          style="width: 200px" @change="renderCharts">
          <el-option v-for="m in 12" :key="m" :label="`${m}月`" :value="m" />
        </el-select>
      </div>
      <el-tabs v-model="chartTab" @tab-change="onChartTab">
        <el-tab-pane label="饼图" name="pie">
          <div id="jcxt-pie" class="chart-box" />
        </el-tab-pane>
        <el-tab-pane label="柱状图" name="bar">
          <div id="jcxt-bar" class="chart-box" />
        </el-tab-pane>
      </el-tabs>
    </el-drawer>

    <!-- 工单详情抽屉 -->
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

<style>
.jcxt-page { padding: 12px; }
.jcxt-page .filter-card { margin-bottom: 10px; }
.jcxt-page .filter-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.jcxt-page .filter-grid { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.jcxt-page .switches { display: flex; gap: 10px; align-items: center; }
.jcxt-page .sw { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; }
.jcxt-page .btns { display: flex; gap: 4px; }
.jcxt-page .toolbar { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
.jcxt-page .jc-table { width: 100%; }
.jcxt-page .row-done { background: var(--el-fill-color-light); }
.jcxt-page .sp-tag.sp-wait { color: var(--el-color-warning); font-size: 12px; }
.jcxt-page .sp-tag.sp-pass { color: var(--el-color-success); }
.jcxt-page .pic-icons { white-space: nowrap; }
.jcxt-page .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.jcxt-page .grid2 .span2 { grid-column: span 2; }
.jcxt-page .total-amount { color: var(--el-color-danger); font-weight: 600; }
.jcxt-page .tip { color: var(--el-text-color-secondary); font-size: 12px; margin-top: 4px; }
.jcxt-page .tip-inline { color: var(--el-text-color-secondary); font-size: 12px; }
.jcxt-page .col-actions { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.jcxt-page .col-grid { display: grid; grid-template-columns: repeat(4, 1fr); row-gap: 8px; }
.jcxt-page .col-item { display: flex; align-items: center; gap: 6px; font-size: 13px; }
.jcxt-page .pic-toolbar { margin-bottom: 8px; display: flex; gap: 10px; align-items: center; }
.jcxt-page .pick-btn { display: inline-block; padding: 4px 12px; border: 1px dashed var(--el-border-color);
  border-radius: 4px; cursor: pointer; font-size: 13px; }
.jcxt-page .pic-list { display: flex; flex-wrap: wrap; gap: 10px; }
.jcxt-page .pic-item { position: relative; }
.jcxt-page .pic-thumb { width: 118px; height: 118px; border-radius: 4px;
  border: 1px solid var(--el-border-color); display: flex; align-items: center;
  justify-content: center; color: var(--el-text-color-secondary); }
.jcxt-page .pic-del { position: absolute; top: -6px; right: -6px; background: var(--el-bg-color);
  border-radius: 50%; padding: 0 4px; }
.jcxt-page .jcd-toolbar { display: flex; gap: 8px; align-items: center; margin-bottom: 8px; }
.jcxt-page .chart-controls { display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 10px; }
.jcxt-page .chart-box { height: calc(100vh - 260px); min-height: 420px; }
.jcxt-page .wo-body { min-height: 220px; }
.jcxt-page .wo-image-title { margin: 16px 0 8px; font-weight: 600; }
.jcxt-page .wo-image-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.jcxt-page .wo-image-slot { display: flex; flex-direction: column; align-items: center; gap: 6px; }
.jcxt-page .wo-image { width: 100%; aspect-ratio: 1; border-radius: 6px;
  border: 1px solid var(--el-border-color); }
.jcxt-page .wo-image-empty { display: flex; align-items: center; justify-content: center;
  background: var(--el-fill-color-lighter); color: var(--el-text-color-secondary);
  font-size: 12px; }
.jcxt-page .wo-image-label { font-size: 12px; color: var(--el-text-color-regular); }
.jcxt-page .wo-done { color: var(--el-color-success); font-weight: 600; }
.jcxt-page .wo-doing { color: var(--el-color-warning); font-weight: 600; }
</style>
