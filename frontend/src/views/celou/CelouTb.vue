<script setup>
/**
 * 测漏成果汇总(照旧 Views/CelouTb/Index.cshtml 复刻)
 * - 24 列台账(含复选框)、全量合计行、两行筛选、6 个工具栏按钮
 * - 13 个统计图表 Tab、Excel 导入/导出/模板、工单详情抽屉、年度节约水量公式
 * - 热力图 1:1 复刻旧版:Leaflet + 本地高德离线瓦片、4 套色谱、3 种权重、200m 点击统计
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent, LegendComponent, TitleComponent, ToolboxComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { useAuthStore } from '@/stores/auth'
import {
  batchNonYuding, deleteCelou, downloadCelouTemplate, exportCelou,
  getCelouDicts, getCelouMonths, getChartBar, getChartPie,
  getChartTb, getHeatmapPoints, getHeatmapStats, getHeatmapTileToken,
  getWorkOrder, listCelou, updateCelouCoord, uploadCelou,
} from '@/api/celou'

echarts.use([
  BarChart, LineChart, PieChart, GridComponent, LegendComponent,
  TitleComponent, ToolboxComponent, TooltipComponent, CanvasRenderer,
])

const auth = useAuthStore()
const canManage = computed(() => auth.hasPerm('celou:manage'))

// ===== 列定义(照旧 datagrid columns 顺序与文案) =====
const COLUMNS = [
  { prop: 'ID', label: 'ID', width: 74, fixed: 'left', align: 'center' },
  { prop: 'xsbm', label: '部门', width: 100, fixed: 'left' },
  { prop: 'louliang', label: '测定漏量（m³/h）', width: 128 },
  { prop: 'gongdan', label: '工单号', width: 106, align: 'center' },
  { prop: 'bgdate', label: '漏点上报日期', width: 112 },
  { prop: 'xiufudate', label: '修复日期', width: 100 },
  { prop: 'qjll', label: '年度节约水量(m³)', width: 138, align: 'right', formula: true },
  { prop: 'qjllProcess', label: '计算过程', width: 180, align: 'right' },
  { prop: 'didian', label: '地址', width: 225, tip: true },
  { prop: 'guanjing', label: '管径', width: 66 },
  { prop: 'guancai', label: '管材', width: 82 },
  { prop: 'yy', label: '原因', width: 145, tip: true },
  { prop: 'dwwucha', label: '定位误差', width: 80 },
  { prop: 'dingliang', label: '定量方式', width: 112 },
  { prop: 'username', label: '上传人', width: 76 },
  { prop: 'yudingliang', label: '预定量', width: 74, align: 'center' },
  { prop: 'scdatetime', label: '上传日期', width: 152 },
  { prop: 'nian', label: '记录年', width: 74 },
  { prop: 'yue', label: '月', width: 58 },
  { prop: 'celoudw', label: '测漏单位', width: 185, tip: true },
  { prop: 'zuobiao_leibie', label: '坐标类别', width: 116 },
  { prop: 'zuobiao_jingdu', label: '经度', width: 108, align: 'right', fixed6: true, editable: true },
  { prop: 'zuobiao_weidu', label: '纬度', width: 108, align: 'right', fixed6: true, editable: true },
  { prop: 'xgusername', label: '修改人', width: 80, align: 'center' },
  { prop: 'xgdatetime', label: '修改时间', width: 152 },
]

const TABS = [
  { key: 'llhb', label: '测定漏量环比', kind: 'tb', metric: 'll', mode: 'hb' },
  { key: 'lltb', label: '测定漏量同比', kind: 'tb', metric: 'll', mode: 'tb' },
  { key: 'dshb', label: '测漏点数环比', kind: 'tb', metric: 'ds', mode: 'hb' },
  { key: 'dstb', label: '测漏点数同比', kind: 'tb', metric: 'ds', mode: 'tb' },
  { key: 'bmll', label: '漏量部门分布', kind: 'pie', type: 'bumen', metric: 'louliang' },
  { key: 'bmjl', label: '记录部门分布', kind: 'pie', type: 'bumen', metric: 'count' },
  { key: 'gjll', label: '漏量管径分布', kind: 'pie', type: 'guanjing', metric: 'louliang' },
  { key: 'gjjl', label: '记录管径分布', kind: 'pie', type: 'guanjing', metric: 'count' },
  { key: 'gcll', label: '漏量管材分布', kind: 'pie', type: 'guancai', metric: 'louliang' },
  { key: 'gcjl', label: '记录管材分布', kind: 'pie', type: 'guancai', metric: 'count' },
  { key: 'dwll', label: '队伍漏量分布', kind: 'pie', type: 'duiwu', metric: 'louliang' },
  { key: 'gjbar', label: '管径平均漏量', kind: 'bar', btype: 'guanjing' },
  { key: 'llbar', label: '漏量范围平均漏量', kind: 'bar', btype: 'louliang' },
]

const LL_OPTIONS = [5, 10, 15, 20, 30, 50, 100, 200]
const GJ_FALLBACK = [15, 20, 25, 32, 40, 50, 65, 80, 100, 150, 200, 300, 400,
  500, 600, 800, 1000, 1200, 1400, 1600]

const filters = reactive({
  page: 1, rows: 20, mohu: '', guanjing: '', xiaolouliang: '', dalouliang: '',
  px: false, px2: false, showDuplicate: false, yudingliangFlag: false,
  filterUsername: '', bumen: '', nd: '', mon: '-1', celoudw: '', gjdayu: '', gjxiaoyu: '',
})
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const footer = ref({ louliang: 0, qjll: 0 })
const selected = ref([])
const dicts = ref({ departments: [], years: [], diameters: [], teams: [], usernames: [], coordinate_types: [], months_of_year: {} })
const months = ref([{ value: -1, label: '==请选择月份==' }])

// 弹窗状态
const uploadDlg = ref(false)
const chartDlg = ref(false)
const formulaDlg = ref(false)
const heatDlg = ref(false)
const drawer = ref(false)

const uploadForm = reactive({
  nd: '', yf: '', cldw: '', yudingliang: false,
  zuobiao_leibie: '高德火星坐标', file: null,
})
const uploading = ref(false)
const fileInput = ref(null)

// 表格内联编辑经纬度
const COORD_PROPS = ['zuobiao_jingdu', 'zuobiao_weidu']
const editCell = ref(null)            // { id, prop } 当前正在编辑的单元格
const editVal = ref('')               // 编辑框临时值
function isCoordCell(prop) { return COORD_PROPS.includes(prop) }
function isEditing(row, prop) {
  return !!editCell.value && editCell.value.id === row.ID && editCell.value.prop === prop
}
async function startEdit(row, prop) {
  editCell.value = { id: row.ID, prop }
  editVal.value = row[prop] == null ? '' : String(row[prop])
  await nextTick()
  const el = document.querySelector('.celou-page .coord-edit input')
  if (el) { el.focus(); el.select() }
}
function cancelEdit() { editCell.value = null }
async function commitCoord(row, prop) {
  if (!isEditing(row, prop)) return
  const raw = (editVal.value ?? '').toString().trim()
  const num = Number(raw)
  if (!raw || !isFinite(num)) { cancelEdit(); return }
  const old = row[prop]
  row[prop] = num
  editCell.value = null
  try {
    const r = await updateCelouCoord({
      id: row.ID,
      jingdu: prop === 'zuobiao_jingdu' ? num : row.zuobiao_jingdu,
      weidu: prop === 'zuobiao_weidu' ? num : row.zuobiao_weidu,
    })
    row.xgusername = r.xgusername
    row.xgdatetime = r.xgdatetime
    ElMessage.success('坐标已更新')
  } catch (e) {
    row[prop] = old
    ElMessage.error('坐标更新失败')
  }
}

const activeTab = ref('llhb')
const chartYear = ref('')
const gjBarValue = ref('')
const llBarValue = ref('')
const chartEl = ref(null)
let chart = null

// ===== 热力图(照旧 Heatmap.cshtml:4 套色谱 / 3 种权重 / 25px 半径) =====
const GRADIENTS = {
  yellowRed: { 0.0: '#fff3e0', 0.2: '#ffb74d', 0.4: '#ff9800', 0.6: '#ff5722', 0.8: '#d32f2f', 1.0: '#8b0000' },
  blueRed: { 0.0: '#0a2f5a', 0.2: '#1e88e5', 0.4: '#43a047', 0.6: '#fb8c00', 0.8: '#f4511e', 1.0: '#d50000' },
  greenRed: { 0.0: '#e8f5e9', 0.2: '#a5d6a7', 0.4: '#fff176', 0.6: '#ff9800', 0.8: '#f44336', 1.0: '#b71c1c' },
  purpleRed: { 0.0: '#f3e5f5', 0.2: '#ce93d8', 0.4: '#e91e63', 0.6: '#f44336', 0.8: '#d32f2f', 1.0: '#4a0000' },
}
const SCHEMES = [
  { key: 'yellowRed', label: '黄红系', css: 'linear-gradient(135deg,#fff3e0,#d32f2f)' },
  { key: 'blueRed', label: '科技蓝红', css: 'linear-gradient(135deg,#0a2f5a,#d50000)' },
  { key: 'greenRed', label: '经典绿红', css: 'linear-gradient(135deg,#e8f5e9,#b71c1c)' },
  { key: 'purpleRed', label: '紫红高温', css: 'linear-gradient(135deg,#f3e5f5,#4a0000)' },
]
const heatWeight = ref('count')
const heatScheme = ref('yellowRed')
const heatTotal = ref(0)          // 筛选命中的记录数
const heatPointCount = ref(0)     // 实际热力点数(数量权重会按网格聚合)
const heatRadiusMeters = ref(0)
const heatEl = ref(null)
const heatStats = ref(null)
const heatBusy = ref(false)
const heatAvailable = ref(true)
let leafletMap = null
let heatLayer = null
let leafletPromise = null

const workOrder = ref(null)
const workOrderLoading = ref(false)

function money(v) {
  if (v === null || v === undefined || v === '') return ''
  return Number(v).toFixed(2)
}
function coord(v) {
  return v === null || v === undefined || v === '' ? '' : Number(v).toFixed(6)
}
function rowClass({ row }) {
  return row.yudingliang ? 'row-yuding' : ''
}
function summaryMethod({ columns }) {
  return columns.map((col) => {
    // 选择列只有 44px,标签放这里会竖排;改放部门列
    if (col.property === 'xsbm') return '全量合计'
    if (col.property === 'louliang') return money(footer.value.louliang)
    if (col.property === 'qjll') return money(footer.value.qjll)
    return ''
  })
}
function apiParams(extra = {}) {
  const p = {}
  for (const [k, v] of Object.entries(filters)) {
    if (v === '' || v === null || v === undefined || v === '-1') continue
    p[k] = v
  }
  return { ...p, ...extra }
}

async function loadDicts() {
  dicts.value = await getCelouDicts()
  if (!filters.nd) filters.nd = dicts.value.current_year || new Date().getFullYear()
  chartYear.value = filters.nd
  await loadMonths()
}
async function loadMonths() {
  const r = await getCelouMonths(filters.nd || 0)
  // 后端是数字 value,前端统一字符串,否则 el-select 会直接显示 -1 而不是提示项文案
  months.value = r.map((m) => ({ ...m, value: String(m.value) }))
  if (!months.value.some((m) => m.value === String(filters.mon))) filters.mon = '-1'
}
async function loadList() {
  loading.value = true
  try {
    const r = await listCelou(apiParams())
    rows.value = r.rows
    total.value = r.total
    footer.value = r.footer?.[0] || { louliang: 0, qjll: 0 }
  } finally {
    loading.value = false
  }
}
function search() { filters.page = 1; loadList() }
function resetFilters() {
  Object.assign(filters, {
    page: 1, rows: 20, mohu: '', guanjing: '', xiaolouliang: '', dalouliang: '',
    px: false, px2: false, showDuplicate: false, yudingliangFlag: false,
    filterUsername: '', bumen: '', nd: dicts.value.current_year || new Date().getFullYear(),
    mon: '-1', celoudw: '', gjdayu: '', gjxiaoyu: '',
  })
  loadMonths(); loadList()
}
function onSelectionChange(v) { selected.value = v }
function requireSelected() {
  if (!selected.value.length) { ElMessage.warning('请先勾选记录'); return null }
  return selected.value.map((r) => r.ID)
}
watch(() => filters.nd, () => { search(); loadMonths() })

// ===== 工具栏 =====
async function doDelete() {
  const ids = requireSelected()
  if (!ids) return
  await ElMessageBox.confirm(`确定删除勾选的 ${ids.length} 条测漏成果记录？`, '批量删除', { type: 'warning' })
  await deleteCelou(ids)
  ElMessage.success('删除成功')
  loadList()
}
async function doBatchNonYuding() {
  const ids = requireSelected()
  if (!ids) return
  await batchNonYuding(ids)
  ElMessage.success('已设为非预定')
  loadList()
}
async function doExport() {
  if (!filters.nd) { ElMessage.warning('请先选择年度！'); return }
  await exportCelou(apiParams(), filters.nd)
}
function openUpload() {
  Object.assign(uploadForm, {
    nd: dicts.value.current_year || '', yf: '', cldw: '', yudingliang: false,
    zuobiao_leibie: '高德火星坐标', file: null,
  })
  uploadDlg.value = true
  // 原生 <input type="file"> 不会随 uploadForm.file=null 而清空自身显示的文件名,
  // 必须手动把控件 value 置空,否则再次打开弹窗会残留上一次选中的文件
  nextTick(() => { if (fileInput.value) fileInput.value.value = '' })
}
function onFilePick(e) { uploadForm.file = e.target.files?.[0] || null }
async function doUpload() {
  if (!uploadForm.cldw) return ElMessage.error('请选择或填写测漏单位')
  if (!uploadForm.nd) return ElMessage.error('请选择年度')
  if (!uploadForm.yf) return ElMessage.error('请选择月份')
  if (!uploadForm.file) return ElMessage.error('请选择文件')
  const fd = new FormData()
  fd.append('upcost', uploadForm.file)
  fd.append('cldw', uploadForm.cldw)
  fd.append('nd', String(uploadForm.nd))
  fd.append('yf', String(uploadForm.yf))
  fd.append('yudingliang', uploadForm.yudingliang ? '1' : '0')
  fd.append('zuobiao_leibie', uploadForm.zuobiao_leibie)
  uploading.value = true
  try {
    const r = await uploadCelou(fd)
    ElMessage.success(`上传成功！导入 ${r.imported} 条（${Object.entries(r.sheets || {}).map(([k, v]) => `${k} ${v}`).join('、')}）`)
    uploadDlg.value = false
    await loadDicts()
    loadList()
  } finally {
    uploading.value = false
  }
}

// ===== 工单详情 =====
async function openWorkOrder(no) {
  if (!no) return
  drawer.value = true
  workOrder.value = null
  workOrderLoading.value = true
  try { workOrder.value = await getWorkOrder(String(no).trim()) }
  finally { workOrderLoading.value = false }
}

// ===== 统计图表 =====
function currentTab() { return TABS.find((t) => t.key === activeTab.value) || TABS[0] }
function openCharts() {
  chartYear.value = filters.nd || dicts.value.current_year || new Date().getFullYear()
  chartDlg.value = true
  // 弹窗内容懒渲染,等 opened 后再初始化 ECharts 容器
}
function onChartOpened() { ensureChart(); loadChart() }
function ensureChart() {
  if (!chartEl.value) return null
  if (!chart) chart = echarts.init(chartEl.value)
  return chart
}
function baseOption(title) {
  return {
    title: { text: title, left: 'center', textStyle: { fontSize: 15 } },
    tooltip: { trigger: 'axis' },
    legend: { bottom: 4, type: 'scroll' },
    toolbox: { right: 16, top: 2, feature: { dataView: { readOnly: true }, magicType: { type: ['line', 'bar'] }, restore: {}, saveAsImage: {} } },
    grid: { left: 68, right: 72, top: 78, bottom: 48 },
    color: ['#5470C6', '#91CC75', '#fac858', '#ee6666', '#73c0de', '#3ba272'],
  }
}
async function loadChart() {
  const t = currentTab()
  const c = ensureChart()
  if (!c) return
  c.showLoading({ text: '正在加载图表…' })
  try {
    const params = apiParams()
    if (t.kind === 'tb') {
      const d = await getChartTb({ ...params, n: chartYear.value })
      const months12 = Array.from({ length: 12 }, (_, i) => `${i + 1}月`)
      const isDs = t.metric === 'ds'
      const cur = Array.from({ length: 12 }, (_, i) => d[`${isDs ? 'd' : ''}yue${i + 1}`] || 0)
      const prev = Array.from({ length: 12 }, (_, i) => d[`${isDs ? 'd' : ''}qyue${i + 1}`] || 0)
      const rate = Array.from({ length: 12 }, (_, i) =>
        d[`${isDs ? 'd' : ''}${t.mode === 'hb' ? 'hb' : 'tb'}yue${i + 1}`] || 0)
      c.setOption({
        ...baseOption(`${chartYear.value} 年 · ${t.label}`),
        tooltip: { trigger: 'axis' },
        legend: { bottom: 4, data: [`${chartYear.value}年`, `${Number(chartYear.value) - 1}年`, '变化率(%)'] },
        xAxis: { type: 'category', data: months12 },
        yAxis: [
          { type: 'value', name: isDs ? '点数(个)' : '漏量(m³/h)' },
          { type: 'value', name: '变化率(%)', axisLabel: { formatter: '{value}%' } },
        ],
        series: [
          { name: `${chartYear.value}年`, type: 'bar', data: cur },
          { name: `${Number(chartYear.value) - 1}年`, type: 'bar', data: prev },
          { name: '变化率(%)', type: 'line', yAxisIndex: 1, data: rate, smooth: true },
        ],
      }, true)
    } else if (t.kind === 'pie') {
      const d = await getChartPie({ ...params, kind: t.type, n: chartYear.value })
      const top = d.slice(0, 15)
      c.setOption({
        title: { text: `${chartYear.value} 年 · ${t.label}`, left: 'center', textStyle: { fontSize: 15 } },
        tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
        legend: { type: 'scroll', orient: 'vertical', left: 8, top: 48, bottom: 8, width: 240 },
        toolbox: { right: 16, top: 2, feature: { dataView: { readOnly: true }, saveAsImage: {} } },
        color: ['#5470C6', '#91CC75', '#fac858', '#ee6666', '#73c0de', '#3ba272', '#fc8452', '#9a60b4'],
        series: [{
          type: 'pie', radius: ['32%', '66%'], center: ['62%', '54%'],
          data: top.map((x) => ({ name: x.name, value: x[t.metric] })),
          label: { formatter: '{b}\n{d}%', fontSize: 11 },
          emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,.25)' } },
        }],
      }, true)
    } else {
      const isGj = t.btype === 'guanjing'
      const v = isGj ? gjBarValue.value : llBarValue.value
      if (!v) {
        c.hideLoading()
        c.clear()
        c.setOption({ title: { text: `请选择${isGj ? '管径' : '漏量上限'}`, left: 'center', top: 'middle', textStyle: { fontSize: 14, color: '#909399' } } }, true)
        return
      }
      const d = await getChartBar({ ...params, kind: t.btype, value: v })
      c.setOption({
        ...baseOption(`${t.label}（${isGj ? '管径≤' + v : '漏量≤' + v}）`),
        legend: { bottom: 4, data: ['平均漏量', '记录数'] },
        xAxis: { type: 'category', data: d.years.map((y) => `${y}年`) },
        yAxis: [{ type: 'value', name: '平均漏量(m³/h)' }, { type: 'value', name: '记录数' }],
        series: [
          { name: '平均漏量', type: 'bar', data: d.avgs },
          { name: '记录数', type: 'line', yAxisIndex: 1, data: d.counts, smooth: true },
        ],
      }, true)
    }
  } finally {
    c.hideLoading()
  }
}
function onChartResize() {
  chart?.resize()
  leafletMap?.invalidateSize()
}

// ===== Leaflet 热力图(照旧 Views/CelouTb/Heatmap.cshtml 1:1 复刻) =====
function loadScript(src) {
  return new Promise((resolve, reject) => {
    const s = document.createElement('script')
    s.src = src
    s.async = false
    s.onload = resolve
    s.onerror = () => reject(new Error('资源加载失败：' + src))
    document.head.appendChild(s)
  })
}
function ensureLeaflet() {
  if (window.L?.heatLayer) return Promise.resolve(window.L)
  if (!leafletPromise) {
    leafletPromise = (async () => {
      for (const href of ['/vendor/leaflet/leaflet.css', '/vendor/leaflet/Control.FullScreen.css']) {
        if (!document.querySelector(`link[href="${href}"]`)) {
          const link = document.createElement('link')
          link.rel = 'stylesheet'
          link.href = href
          document.head.appendChild(link)
        }
      }
      await loadScript('/vendor/leaflet/leaflet.js')
      await loadScript('/vendor/leaflet/leaflet-heat.js')
      await loadScript('/vendor/leaflet/Control.FullScreen.js')
      if (!window.L?.heatLayer) throw new Error('Leaflet 热力插件未就绪')
      return window.L
    })().catch((e) => { leafletPromise = null; throw e })
  }
  return leafletPromise
}
function escapeHtml(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c])
}
// 热力半径固定 25px,按当前缩放/纬度换算成米(照旧 updateRadiusLabel)
function updateRadiusLabel() {
  if (!leafletMap) return
  const zoom = leafletMap.getZoom()
  const lat = leafletMap.getCenter().lat
  const mpp = (40075016.686 / (256 * Math.pow(2, zoom))) * Math.cos(lat * Math.PI / 180)
  heatRadiusMeters.value = Math.round(25 * mpp)
}
async function ensureHeatMap() {
  const L = await ensureLeaflet()
  if (leafletMap) { leafletMap.invalidateSize(); return }
  const tk = await getHeatmapTileToken()
  heatAvailable.value = !!tk.available
  leafletMap = L.map(heatEl.value, {
    center: [24.479, 118.089], zoom: 12, preferCanvas: true,
  })
  L.tileLayer(`/api/celou/tiles?z={z}&x={x}&y={y}&token=${encodeURIComponent(tk.token)}`, {
    attribution: '&copy; 高德地图', maxZoom: 18, maxNativeZoom: 17,
  }).addTo(leafletMap)
  if (L.control?.fullscreen) {
    L.control.fullscreen({ position: 'topleft', title: '全屏模式' }).addTo(leafletMap)
  }
  leafletMap.on('click', onMapClick)
  leafletMap.on('zoomend moveend', updateRadiusLabel)
  updateRadiusLabel()
  setTimeout(() => leafletMap?.invalidateSize(), 80)
}
async function onMapClick(e) {
  const L = window.L
  try {
    const d = await getHeatmapStats({
      ...apiParams(), lng: e.latlng.lng, lat: e.latlng.lat, radius: 200,
    })
    heatStats.value = d
    if (!d.count) return
    const lng = Number(e.latlng.lng).toFixed(6)
    const lat = Number(e.latlng.lat).toFixed(6)
    const details = (d.details || []).map((x) =>
      `<li><b>${escapeHtml(x.didian || '无地址')}</b> 漏量 ${Number(x.louliang || 0).toFixed(1)} m³/h，管径 ${escapeHtml(x.guanjing || (x.gjsmall ? x.gjsmall + 'mm' : '未知'))}，经度 ${Number(x.jingdu || 0).toFixed(6)} · 纬度 ${Number(x.weidu || 0).toFixed(6)}</li>`,
    ).join('')
    const html = `<div class="celou-pop">
      <div class="celou-pop-hd"><strong>测漏统计</strong><span>半径 ${d.radius} m</span></div>
      <div class="celou-pop-coord">点击坐标：经度 <b>${lng}</b> · 纬度 <b>${lat}</b>（GCJ-02）</div>
      工单数量：<b>${d.count}</b><br>总漏量：<b>${Number(d.totalFlow).toFixed(2)}</b> m³/h<br>
      平均管径：<b>${Number(d.avgDiameter).toFixed(0)}</b> mm · 最大管径：<b>${d.maxDiameter}</b> mm
      ${details ? `<div class="celou-pop-dt"><strong>附近工单（最近 ${d.details.length} 条）</strong><ul>${details}</ul></div>` : ''}
      <div class="celou-pop-ft">按当前主页面筛选条件统计</div></div>`
    L.popup({ maxWidth: 340 }).setLatLng(e.latlng).setContent(html).openOn(leafletMap)
  } catch (err) {
    ElMessage.error('附近统计查询失败')
  }
}
async function loadHeat() {
  if (!leafletMap || heatBusy.value) return
  heatBusy.value = true
  try {
    const d = await getHeatmapPoints({ ...apiParams(), weight: heatWeight.value })
    heatTotal.value = d.total
    const pts = d.points.map((p) => [p.lat, p.lng, p.intensity])
    heatPointCount.value = pts.length
    const L = window.L
    if (heatLayer) { leafletMap.removeLayer(heatLayer); heatLayer = null }
    if (pts.length) {
      heatLayer = L.heatLayer(pts, {
        radius: 25, blur: 20, maxZoom: 18, minOpacity: 0.3,
        gradient: GRADIENTS[heatScheme.value],
      }).addTo(leafletMap)
    }
  } catch (e) {
    ElMessage.error('热力数据加载失败')
  } finally {
    heatBusy.value = false
  }
}
function openHeat() { heatDlg.value = true }
async function onHeatOpened() {
  try {
    await ensureHeatMap()
    await loadHeat()
  } catch (e) {
    ElMessage.error('地图初始化失败：' + (e.message || e))
  }
}
function onHeatClosed() {
  if (leafletMap) { leafletMap.remove(); leafletMap = null }
  heatLayer = null
  heatStats.value = null
}
function changeScheme(k) { heatScheme.value = k; loadHeat() }

onMounted(async () => {
  await loadDicts()
  await loadList()
  window.addEventListener('resize', onChartResize)
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onChartResize)
  chart?.dispose()
  if (leafletMap) { leafletMap.remove(); leafletMap = null }
})
</script>

<template>
  <div class="celou-page">
    <el-card class="filter-card">
      <div class="filter-title">📊 测漏成果汇总表</div>
      <div class="filter-line">
        <el-input v-model="filters.mohu" placeholder="模糊查询" clearable style="width: 180px"
          @keyup.enter="search" />
        <el-button type="primary" @click="search">搜索</el-button>
        <el-button @click="resetFilters">重置</el-button>
        <span class="fl-group">
          <span class="fl-label">管径：</span>
          <el-input v-model="filters.guanjing" placeholder="精确匹配" style="width: 84px" @keyup.enter="search" />
        </span>
        <span class="fl-group">
          <span class="fl-label">漏量：</span>
          <el-input v-model="filters.xiaolouliang" placeholder="最小值" style="width: 80px" @keyup.enter="search" />
          <span class="fl-label">至</span>
          <el-input v-model="filters.dalouliang" placeholder="最大值" style="width: 80px" @keyup.enter="search" />
        </span>
        <span class="fl-group">
          <el-switch v-model="filters.px" inline-prompt active-text="on" inactive-text="off"
            style="width: 52px" @change="search" />
          <span class="fl-label small">非定点、探测</span>
        </span>
        <span class="fl-group">
          <el-switch v-model="filters.px2" inline-prompt active-text="on" inactive-text="off"
            style="width: 52px" @change="search" />
          <span class="fl-label small">配合定点、管线探测</span>
        </span>
        <el-checkbox v-model="filters.showDuplicate" @change="search">仅显示重复工单</el-checkbox>
        <el-checkbox v-model="filters.yudingliangFlag" @change="search">预定量</el-checkbox>
      </div>
      <div class="filter-line">
        <span class="fl-group">
          <span class="fl-label">上传人：</span>
          <el-select v-model="filters.filterUsername" clearable placeholder="所有上传人"
            style="width: 120px" @change="search">
            <el-option v-for="u in dicts.usernames" :key="u" :label="u" :value="u" />
          </el-select>
        </span>
        <el-select v-model="filters.bumen" clearable placeholder="归属部门" style="width: 132px" @change="search">
          <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
        </el-select>
        <el-select v-model="filters.nd" clearable placeholder="选择年度" style="width: 116px">
          <el-option v-for="y in dicts.years" :key="y" :label="y" :value="y" />
        </el-select>
        <el-select v-model="filters.mon" placeholder="==请选择月份==" style="width: 160px" @change="search">
          <el-option v-for="m in months" :key="m.value" :label="m.label" :value="m.value" />
        </el-select>
        <el-select v-model="filters.gjdayu" clearable placeholder="管径≥" style="width: 116px" @change="search">
          <el-option v-for="g in dicts.diameters" :key="g" :label="`管径>=${g}`" :value="g" />
        </el-select>
        <el-select v-model="filters.gjxiaoyu" clearable placeholder="管径≤" style="width: 116px" @change="search">
          <el-option v-for="g in dicts.diameters" :key="g" :label="`管径<=${g}`" :value="g" />
        </el-select>
        <el-select v-model="filters.celoudw" clearable placeholder="测漏单位" style="width: 210px" @change="search">
          <el-option v-for="t in dicts.teams" :key="t" :label="t" :value="t" />
        </el-select>
        <el-button class="heat-btn" size="small" @click="openHeat">热力图</el-button>
      </div>
    </el-card>

    <div class="toolbar">
      <template v-if="canManage">
        <el-button type="danger" size="small" plain @click="doDelete">批量删除</el-button>
        <el-button type="primary" size="small" @click="openUpload">上传测漏成果表</el-button>
        <el-button size="small" @click="downloadCelouTemplate">下载测漏成果表模板</el-button>
      </template>
      <el-button size="small" @click="openCharts">统计图表</el-button>
      <el-button size="small" @click="doExport">导出记录</el-button>
      <el-button v-if="canManage" size="small" @click="doBatchNonYuding">批量设为非预定</el-button>
      <el-button size="small" text type="primary" @click="formulaDlg = true">年度节约水量公式</el-button>
      <span class="toolbar-hint">共 {{ total }} 条 · 点工单号查看详情 · 合计为筛选后全量</span>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe size="small"
      height="calc(100vh - 292px)" :row-class-name="rowClass"
      show-summary :summary-method="summaryMethod" @selection-change="onSelectionChange">
      <el-table-column type="selection" width="44" fixed="left" />
      <el-table-column v-for="c in COLUMNS" :key="c.prop" :prop="c.prop" :width="c.width"
        :align="c.align || 'left'" :fixed="c.fixed" :show-overflow-tooltip="c.tip">
        <template #header>
          <span v-if="c.formula" class="formula-head" @click.stop="formulaDlg = true">
            {{ c.label }} <span class="formula-icon">ⓘ</span>
          </span>
          <span v-else>{{ c.label }}</span>
        </template>
        <template #default="{ row }">
          <span v-if="c.prop === 'gongdan'" class="link-like" @click="openWorkOrder(row.gongdan)">{{ row.gongdan }}</span>
          <span v-else-if="c.prop === 'yudingliang'" class="yuding-tag">{{ row.yudingliang ? '预定量' : '' }}</span>
          <span v-else-if="c.prop === 'qjll' || c.prop === 'louliang'">{{ money(row[c.prop]) }}</span>
          <el-input v-else-if="canManage && isCoordCell(c.prop) && isEditing(row, c.prop)"
            v-model="editVal" size="small" class="coord-edit"
            @keyup.enter="commitCoord(row, c.prop)" @keyup.esc="cancelEdit"
            @blur="commitCoord(row, c.prop)" />
          <span v-else-if="c.fixed6"
            :class="{ 'coord-editable': canManage && isCoordCell(c.prop) }"
            :title="canManage && isCoordCell(c.prop) ? '双击编辑经纬度' : ''"
            @dblclick="canManage && isCoordCell(c.prop) && startEdit(row, c.prop)">{{ coord(row[c.prop]) }}</span>
          <span v-else>{{ row[c.prop] }}</span>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="filters.page" v-model:page-size="filters.rows"
        :page-sizes="[20, 60, 120]" :total="total" layout="total, sizes, prev, pager, next, jumper"
        @current-change="loadList" @size-change="search" />
    </div>

    <!-- 上传测漏成果表 -->
    <el-dialog v-model="uploadDlg" title="上传“测漏成果清单.xls”文件" width="600px">
      <div class="tip">
        说明：文件名称不限，且支持.xls、.xlsx格式，要求严格按模板文件的格式，标题和列标题不要变。
      </div>
      <el-form label-width="110px" size="small">
        <el-form-item label="记录年度">
          <el-select v-model="uploadForm.nd" placeholder="===选择记录年度===" style="width: 100%">
            <el-option v-for="y in Array.from({ length: 13 }, (_, i) => 2020 + i)" :key="y" :label="y" :value="y" />
          </el-select>
        </el-form-item>
        <el-form-item label="记录月份">
          <el-select v-model="uploadForm.yf" placeholder="===选择记录月份===" style="width: 100%">
            <el-option v-for="m in 12" :key="m" :label="m" :value="m" />
          </el-select>
        </el-form-item>
        <el-form-item label="测漏单位">
          <el-select v-model="uploadForm.cldw" filterable allow-create default-first-option
            placeholder="请选择或填写测漏单位" style="width: 100%">
            <el-option v-for="t in dicts.teams" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="标记为预定量">
          <el-checkbox v-model="uploadForm.yudingliang" />
        </el-form-item>
        <el-form-item label="坐标类型">
          <el-select v-model="uploadForm.zuobiao_leibie" style="width: 100%">
            <el-option v-for="t in dicts.coordinate_types" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="Excel 文件">
          <input ref="fileInput" type="file" accept=".xls,.xlsx" @change="onFilePick" />
          <span class="file-name">{{ uploadForm.file?.name || '' }}</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="uploadDlg = false">关闭</el-button>
        <el-button type="primary" :loading="uploading" @click="doUpload">上传</el-button>
      </template>
    </el-dialog>

    <!-- 统计图表(13 Tab) -->
    <el-dialog v-model="chartDlg" title="测漏成果图" width="min(1440px, 94vw)" top="5vh"
      destroy-on-close @opened="onChartOpened" @closed="chart?.dispose(); chart = null">
      <div class="chart-layout">
        <el-tabs v-model="activeTab" tab-position="left" class="chart-tabs" @tab-change="loadChart">
          <el-tab-pane v-for="t in TABS" :key="t.key" :name="t.key" :label="t.label" />
        </el-tabs>
        <div class="chart-main">
          <div class="chart-controls">
            <span>年度：</span>
            <el-select v-model="chartYear" style="width: 108px" @change="loadChart">
              <el-option v-for="y in dicts.years" :key="y" :label="y" :value="y" />
            </el-select>
            <template v-if="currentTab().kind === 'bar'">
              <span v-if="currentTab().btype === 'guanjing'">管径≤：</span>
              <el-select v-if="currentTab().btype === 'guanjing'" v-model="gjBarValue"
                placeholder="==请选择管径==" style="width: 150px" @change="loadChart">
                <el-option v-for="g in (dicts.diameters.length ? dicts.diameters : GJ_FALLBACK)"
                  :key="g" :label="`≤ DN${g}`" :value="g" />
              </el-select>
              <span v-else>漏量≤：</span>
              <el-select v-if="currentTab().btype === 'louliang'" v-model="llBarValue"
                placeholder="==请选择漏量上限==" style="width: 168px" @change="loadChart">
                <el-option v-for="v in LL_OPTIONS" :key="v" :label="`≤ ${v} m³/h`" :value="v" />
              </el-select>
            </template>
            <span class="chart-hint">数据源与当前列表筛选条件一致</span>
          </div>
          <div ref="chartEl" class="chart-canvas"></div>
        </div>
      </div>
    </el-dialog>

    <!-- 年度节约水量公式 -->
    <el-dialog v-model="formulaDlg" title="年度节约水量 — 计算公式" width="520px">
      <div class="formula-doc">
        <p><b>年度节约水量(m³) = 测定漏量(m³/h) × 24 × 分级天数 × 0.6</b></p>
        <p>大中型暗漏 ≥ 8 m³/h → 60 天</p>
        <p>小型暗漏 0.5 ~ 8 m³/h → 90 天</p>
        <p>不计量 &lt; 0.5 m³/h → —</p>
        <p class="muted">说明：压力折算系数 本次测算全管网统一固定 0.6；合计行为筛选后全量合计，不是当页合计。</p>
      </div>
    </el-dialog>

    <!-- Leaflet 热力图(1:1 复刻旧版 Heatmap.cshtml) -->
    <el-dialog v-model="heatDlg" class="celou-heat-dialog" title="测漏成果热力图"
      width="min(1220px, 95vw)" top="4vh" destroy-on-close
      @opened="onHeatOpened" @closed="onHeatClosed">
      <div class="celou-heat-head">
        <div class="celou-heat-group">
          <span>🎯 权重</span>
          <el-select v-model="heatWeight" size="small" style="width: 112px" @change="loadHeat">
            <el-option label="数量权重" value="count" />
            <el-option label="漏量权重" value="flow" />
            <el-option label="管径权重" value="diameter" />
          </el-select>
        </div>
        <div class="celou-heat-group">
          <span>🎨 色谱</span>
          <button v-for="s in SCHEMES" :key="s.key" type="button" class="celou-scheme"
            :class="{ active: heatScheme === s.key }" :style="{ background: s.css }"
            :title="s.label" @click="changeScheme(s.key)" />
        </div>
        <div class="celou-heat-group"><span>🔍 半径</span><b class="celou-heat-num">~{{ heatRadiusMeters }} m</b></div>
        <div class="celou-heat-group">
          <span>📊 热力点</span><b class="celou-heat-num">{{ heatPointCount }}</b>
          <span class="celou-heat-sub">/ 命中 {{ heatTotal }} 条</span>
        </div>
        <el-button size="small" :loading="heatBusy" @click="loadHeat">🔄 刷新热力</el-button>
      </div>
      <div class="celou-heat-filter">
        沿用主页面筛选：{{ filters.nd || '全部年度' }} 年 ·
        {{ filters.mon === '-1' ? '全年' : filters.mon + ' 月' }} · 部门/单位/管径/漏量等条件
        <span class="celou-heat-tip">点击地图任意位置查看 200 米内统计</span>
      </div>
      <div ref="heatEl" class="celou-heat-map"></div>
      <div class="celou-heat-foot">
        <span>GCJ-02 · 本地高德离线瓦片 · © 高德地图</span>
        <span v-if="!heatAvailable" class="celou-heat-warn">未找到瓦片目录，底图为空（热力层仍可用）</span>
      </div>
      <div v-if="heatStats?.count > 0" class="celou-heat-stats">
        <b>附近统计：</b>{{ heatStats.count }} 条 · 漏量合计 {{ heatStats.totalFlow }} m³/h ·
        平均管径 DN{{ heatStats.avgDiameter }} · 最大 DN{{ heatStats.maxDiameter }}
      </div>
    </el-dialog>

    <!-- 工单详情抽屉 -->
    <el-drawer v-model="drawer" title="工单详情" size="420px">
      <div v-loading="workOrderLoading">
        <template v-if="workOrder?.success && workOrder.data">
          <div v-for="f in [
            ['工单号', workOrder.data.Id], ['创建时间', workOrder.data.CreateTime],
            ['结束时间', workOrder.data.updateTime], ['地址', workOrder.data.AddressStr],
            ['问题描述', workOrder.data.Problem], ['备注', workOrder.data.OtherDemand],
            ['漏水损坏类型', workOrder.data.DamageType], ['漏水口径', workOrder.data.LeakageType],
            ['关闭阀门', workOrder.data.CloseValve],
          ]" :key="f[0]" class="wo-row"><span>{{ f[0] }}：</span><b>{{ f[1] ?? '暂无数据' }}</b></div>
          <div class="wo-row"><span>状态：</span>
            <b :class="workOrder.data.Status == 1 ? 'wo-done' : 'wo-doing'">
              {{ workOrder.data.Status == 1 ? '已处理' : '处理中' }}
            </b>
          </div>
        </template>
        <el-empty v-else :description="workOrder?.msg || '暂无数据'" />
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
.celou-page { display: flex; flex-direction: column; gap: 8px; }
.filter-card :deep(.el-card__body) { padding: 10px 14px; }
.filter-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.filter-line { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-bottom: 6px; }
.filter-line:last-child { margin-bottom: 0; }
/* 标签与控件必须同组换行,避免"上传人："留在上一行而下拉掉到下一行 */
.fl-group { display: inline-flex; align-items: center; gap: 4px; white-space: nowrap; }
.fl-label { font-size: 12px; color: #606266; margin-left: 4px; white-space: nowrap; }
.fl-label.small { margin-left: 0; }
.filter-line :deep(.el-checkbox) { margin-right: 4px; }
.filter-line :deep(.el-switch) { --el-switch-off-color: #7d8590; }
.heat-btn { margin-left: auto; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }
.link-like { color: #b07d1a; text-decoration: underline; cursor: pointer; }
.coord-editable { cursor: pointer; }
.coord-editable:hover { text-decoration: underline dotted #409eff; }
.coord-edit { --el-component-size-small: 24px; }
.celou-page :deep(.coord-edit) .el-input__wrapper { padding: 0 6px; }
.celou-page :deep(.coord-edit) { width: 100%; }
.yuding-tag { color: #d03050; font-weight: 600; }
.formula-head { cursor: pointer; color: #409eff; }
.formula-icon { font-size: 12px; }
:deep(.row-yuding) { background-color: rgba(214, 178, 94, .35) !important; color: #7a4a12; font-weight: 600; }
.tip { color: #909399; font-size: 12px; line-height: 1.7; margin-bottom: 12px; }
.file-name { margin-left: 8px; color: #606266; font-size: 12px; }
.chart-layout { display: flex; gap: 12px; height: 620px; }
.chart-tabs { width: 140px; flex: none; }
.chart-tabs :deep(.el-tabs__item) { font-size: 12px; padding: 0 8px; height: 34px; line-height: 34px; }
.chart-tabs :deep(.el-tabs__content) { display: none; }
.chart-main { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.chart-controls { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #606266; }
.chart-hint { margin-left: auto; color: #909399; }
.chart-canvas { flex: 1; min-height: 540px; }
.formula-doc p { line-height: 1.9; font-size: 13px; margin: 4px 0; }
.formula-doc .muted { color: #909399; }
.wo-row { display: flex; gap: 8px; padding: 7px 0; border-bottom: 1px dashed #ebeef5; font-size: 13px; }
.wo-row span { color: #909399; min-width: 92px; text-align: right; }
.wo-row b { font-weight: 500; word-break: break-all; }
.wo-done { color: #52c41a; }
.wo-doing { color: #fa541c; }
</style>

<style>
/* 热力图弹窗会 teleport 到 body,scoped 样式命中不了,故单独一份带前缀的全局样式 */
.celou-heat-dialog {
  --el-dialog-bg-color: #071120;
  --el-dialog-border-radius: 16px;
  border: 1px solid rgba(0, 200, 255, .32);
  box-shadow: 0 18px 60px rgba(0, 0, 0, .45);
}
.celou-heat-dialog .el-dialog__header { padding: 12px 18px; border-bottom: 1px solid rgba(0, 200, 255, .18); margin: 0; }
.celou-heat-dialog .el-dialog__title { color: #bbf0ff; font-size: 15px; letter-spacing: .5px; }
.celou-heat-dialog .el-dialog__headerbtn .el-dialog__close { color: #7fb6d6; }
.celou-heat-dialog .el-dialog__body { padding: 10px 14px 12px; }
.celou-heat-head {
  display: flex; flex-wrap: wrap; align-items: center; gap: 8px 14px;
  padding: 8px 12px; margin-bottom: 8px; font-size: 12px; color: #bbf0ff;
  background: rgba(10, 24, 40, .9); border: 1px solid rgba(0, 200, 255, .22); border-radius: 20px;
}
.celou-heat-group { display: inline-flex; align-items: center; gap: 6px; white-space: nowrap; }
.celou-heat-num { color: #ffd966; font-weight: 700; text-shadow: 0 0 6px rgba(255, 170, 51, .45); }
.celou-heat-sub, .celou-heat-tip, .celou-heat-foot { color: #6f93b0; font-size: 11px; }
.celou-heat-head .el-select__wrapper { background: #0e1a2b; box-shadow: 0 0 0 1px #2f6f96 inset; }
.celou-heat-head .el-select__selected-item { color: #d9f3ff; }
.celou-scheme {
  width: 24px; height: 24px; border-radius: 50%; cursor: pointer; padding: 0;
  border: 2px solid rgba(255, 255, 255, .25); transition: transform .18s, box-shadow .18s;
}
.celou-scheme:hover { transform: scale(1.16); border-color: #fff; }
.celou-scheme.active { border-color: #fff; box-shadow: 0 0 10px rgba(255, 255, 255, .7); transform: scale(1.12); }
.celou-heat-filter {
  display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
  margin-bottom: 8px; padding: 0 4px; font-size: 11px; color: #8fb6d6;
}
.celou-heat-tip { margin-left: auto; }
.celou-heat-map {
  height: min(560px, 66vh); min-height: 360px; width: 100%;
  border-radius: 14px; overflow: hidden; background: #010b14;
  box-shadow: 0 0 0 1px rgba(0, 242, 255, .18) inset;
}
.celou-heat-foot { display: flex; justify-content: space-between; gap: 10px; padding: 7px 4px 0; }
.celou-heat-warn { color: #ffb74d; }
.celou-heat-stats {
  margin-top: 8px; padding: 7px 10px; font-size: 12px; color: #bfe6ff;
  border: 1px solid rgba(0, 200, 255, .22); border-radius: 8px; background: rgba(10, 24, 40, .8);
}
.celou-heat-map.leaflet-container { font-family: inherit; }
.celou-heat-map .leaflet-control-zoom a {
  background: #102238; color: #bbf0ff; border-color: rgba(0, 200, 255, .25);
}
.celou-heat-map .leaflet-control-attribution {
  background: rgba(6, 16, 28, .72); color: #6f93b0; font-size: 10px;
}
.celou-heat-map .leaflet-control-attribution a { color: #8bc5ff; }
/* Leaflet CSS 是运行时动态插入 head 末尾,需靠 .celou-heat-map 后代选择器提高优先级 */
.celou-heat-map .leaflet-popup-content-wrapper,
.celou-heat-map .leaflet-popup-tip { background: #0d1c2e; color: #d6ecff; }
.celou-heat-map .leaflet-popup-content-wrapper {
  border: 1px solid rgba(0, 200, 255, .35); border-radius: 10px;
  box-shadow: 0 8px 26px rgba(0, 0, 0, .5);
}
.celou-heat-map .leaflet-popup-content {
  margin: 10px 12px; font-size: 12.5px; line-height: 1.8; font-family: inherit;
}
.celou-heat-map a.leaflet-popup-close-button { color: #8fb6d9 !important; }
.celou-pop { min-width: 230px; }
.celou-pop b { color: #ffd966; }
.celou-pop-hd {
  display: flex; justify-content: space-between; gap: 16px;
  border-bottom: 1px solid rgba(0, 200, 255, .45); margin-bottom: 6px; padding-bottom: 4px;
}
.celou-pop-hd span { color: #8bc5ff; }
.celou-pop-coord {
  margin: 0 0 6px; padding-bottom: 5px; font-size: 11.5px; line-height: 1.6;
  color: #bfe6ff; border-bottom: 1px solid rgba(0, 200, 255, .18);
}
.celou-pop-dt { margin-top: 8px; border-top: 1px solid rgba(0, 200, 255, .2); padding-top: 6px; }
.celou-pop-dt ul { max-height: 150px; overflow-y: auto; margin: 4px 0 0; padding-left: 16px; font-size: 11px; }
.celou-pop-ft { margin-top: 6px; font-size: 10px; color: #7aa2f7; }
@media (max-width: 900px) {
  .celou-heat-map { height: 50vh; min-height: 300px; }
  .celou-heat-tip { margin-left: 0; }
}
</style>
