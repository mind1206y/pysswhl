<script setup>
/**
 * 车辆油量统计报表(照旧 oiltj/Index.cshtml 1:1 复刻,Element Plus + ECharts 版)。
 * 旧页功能清单:
 * - 筛选:车号模糊/部门/车辆类型/车号/年度/月份 + 三开关(所有-正常/非油卡/柴油)
 * - 表格:行展开 12 月油量子表;双击行开油量图;全年加油量列悬停统计卡片;
 *         百公里油耗 >=15 红底预警、<0 粉底异常
 * - 图表:油量图/里程图互相切换;部门年度油量堆叠图(升数/金额切换)
 * - 加油明细弹窗:月度加油金额/升数/派车次数 + 合计
 * - 导出:月度报表/年度报表/财务报表
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { DataLine } from '@element-plus/icons-vue'
import * as echarts from 'echarts'
import {
  exportOiltjFinance, exportOiltjMonth, exportOiltjYear,
  getGlChart, getMonthStat, getOilChart, getOiltjCars, getOiltjDicts,
  getOiltjMonths, getYouliang, getZChart, listOiltj,
} from '@/api/oiltj'

const dicts = reactive({
  years: [], lx_used: [], departments: [], vehicles: [],
  my_dept: '', current_year: new Date().getFullYear(),
  current_month: new Date().getMonth() + 1,
})

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)

const filters = reactive({
  sousou: '',
  bmid: null,
  clx: '',
  chel: null,
  nian: null,          // 空=今年(照旧年度下拉首项)
  yue: -1,             // -1=上月(照旧月份下拉首项)
  px: false,           // false=只看正常车(照旧 offText「正常」)
  nooilcard: false,
  oillie: false,       // 柴油(oil=='0#')
})

const monthOptions = ref([{ value: -1, text: '==月份（上月）==' }])
const carOptions = ref([])   // [{value,text}]

function buildParams() {
  const p = { page: page.value, size: size.value }
  if (filters.sousou) p.sousou = filters.sousou
  if (filters.bmid) p.bmid = filters.bmid
  if (filters.clx) p.clx = filters.clx
  if (filters.chel) p.cheid = filters.chel
  if (filters.nian) p.nian = filters.nian
  if (filters.yue !== -1) p.yue = filters.yue   // -1 不传,后端默认上月
  if (filters.px) p.px = true
  if (filters.nooilcard) p.nooilcard = true
  if (filters.oillie) p.oillie = true
  return p
}

async function load() {
  loading.value = true
  try {
    const d = await listOiltj(buildParams())
    rows.value = d.rows
    total.value = d.total
  } finally { loading.value = false }
}
function search() { page.value = 1; load() }

function onSortChange({ prop, order }) {
  if (!prop || !order) return
  loading.value = true
  listOiltj({ ...buildParams(), page: 1, size: size.value, sort: prop, order: order === 'ascending' ? 'asc' : 'desc' })
    .then((d) => { rows.value = d.rows; total.value = d.total })
    .finally(() => { loading.value = false })
}

// 年份变化 → 月份下拉联动(照旧 getmon:重填后选中「上月」首项)
async function onYearChange() {
  const d = await getOiltjMonths(filters.nian || 0)
  monthOptions.value = [{ value: -1, text: '==月份（上月）==' }]
    .concat(d.months.map((m) => ({ value: m, text: `${m}` })))
  filters.yue = -1
  search()
}

// 部门变化 → 车号下拉联动并清空(照旧 getss)
async function onDeptChange() {
  const d = await getOiltjCars(filters.bmid || 0)
  carOptions.value = d
  filters.chel = null
  search()
}

const statusText = (v) => ({ 1: '正常', 2: '报废' }[v] || '')
const num2 = (v) => Number(v || 0).toFixed(2)

function rowClass({ row }) {
  if (Number(row.lpkm) >= 15) return 'oiltj-row-warn'       // peachpuff + 红字(照旧)
  if (Number(row.lpkm) < 0) return 'oiltj-row-bad'          // lightcoral(照旧)
  return ''
}

// ===== 行展开:12 月油量子表(照旧 getyouliang) =====
const expandCache = reactive({})
async function loadExpand(row, expandRows) {
  if (!expandRows.includes(row)) return
  if (!expandCache[row.cheid]) {
    const d = await getYouliang(row.cheid, row.niand)
    expandCache[row.cheid] = d.rows[0] || {}
  }
}

// ===== 加油明细弹窗(照旧 showOilMonthStat / GetOilMonthStat) =====
const statDlg = reactive({
  visible: false, cheid: 0, chehao: '',
  year: new Date().getFullYear(), months: [], loading: false,
})
const statYearOptions = computed(() => {
  const end = new Date().getFullYear() + 1
  const arr = []
  for (let y = 2020; y <= end; y++) arr.push(y)
  return arr
})
const totalStat = computed(() => {
  let amount = 0, oil = 0, useCount = 0
  for (const m of statDlg.months) {
    amount += Number(m.amount) || 0
    oil += Number(m.oil) || 0
    useCount += Number(m.useCount) || 0
  }
  return { amount: amount.toFixed(2), oil: oil.toFixed(2), useCount }
})
function openStat(row) {
  statDlg.cheid = row.cheid
  statDlg.chehao = row.chehao
  statDlg.year = new Date().getFullYear()
  statDlg.visible = true
  loadMonthStat()
}
async function loadMonthStat() {
  statDlg.loading = true
  try {
    const d = await getMonthStat(statDlg.cheid, statDlg.year)
    statDlg.months = d.months
  } finally { statDlg.loading = false }
}

// ===== 行双击:油量图 ↔ 里程图(照旧 showCharts/showGlCharts) =====
const chartDlg = reactive({ visible: false, mode: 'oil', title: '油量图', cheid: 0, niand: 0, row: null })
let chartInst = null
const tableRef = ref(null)
const chartRef = ref(null)
const zChartRef = ref(null)

function selectedRows() { return tableRef.value?.getSelectionRows() || [] }
function needOneRow() {
  const sel = selectedRows()
  if (sel.length !== 1) { ElMessage.warning('请选择单条数据'); return null }
  return sel[0]
}
async function openChart(row, mode = 'oil') {
  chartDlg.row = row
  chartDlg.cheid = row.cheid
  chartDlg.niand = row.niand
  chartDlg.mode = mode
  chartDlg.title = mode === 'oil' ? '油量图' : '里程图'
  chartDlg.visible = true
  await nextTick()
  renderChartDlg()
}
function dblclickRow(row) { openChart(row, 'oil') }
function switchChartMode() {
  chartDlg.mode = chartDlg.mode === 'oil' ? 'gl' : 'oil'
  chartDlg.title = chartDlg.mode === 'oil' ? '油量图' : '里程图'
  renderChartDlg()
}

async function renderChartDlg() {
  if (!chartRef.value) return
  chartInst = chartInst || echarts.init(chartRef.value)
  const row = chartDlg.row
  const months = Array.from({ length: 12 }, (_, i) => `${i + 1}月`)
  if (chartDlg.mode === 'oil') {
    const d = await getOilChart(chartDlg.cheid, chartDlg.niand)
    chartInst.setOption({
      title: { text: d.chehao, textStyle: { color: '#333' } },
      tooltip: {}, legend: {},
      xAxis: { data: months }, yAxis: {},
      series: [{
        name: `全年油量共：${row.noil}（升）`, type: 'bar',
        data: months.map((_, i) => d[`yue${i + 1}`]),
        label: { show: true, position: 'top', distance: 10 },
      }],
    }, true)
  } else {
    const d = await getGlChart(chartDlg.cheid, chartDlg.niand)
    chartInst.setOption({
      title: { text: d.chehao, textStyle: { color: '#333' } },
      tooltip: {}, legend: {},
      xAxis: { data: months }, yAxis: {},
      series: [{
        name: `全年里程：${row.ngls}（km）`, type: 'bar',
        data: months.map((_, i) => d[`yue${i + 1}`]),
        label: { show: true, position: 'top', distance: 10 },
      }],
    }, true)
  }
  chartInst.resize()
}

// ===== 部门年度油量堆叠图(照旧 showZCharts/GetZchart,升数/金额切换) =====
const zDlg = reactive({ visible: false, isJine: false })
let zInst = null
let zData = null
async function showZCharts() {
  zDlg.visible = true
  const d = await getZChart({ bmid: filters.bmid || undefined, year: filters.nian || undefined })
  zData = d
  await nextTick()
  setTimeout(() => {
    if (zInst) zInst.dispose()
    zInst = echarts.init(zChartRef.value)
    renderZChart()
  }, 50)
}
function renderZChart() {
  if (!zInst || !zData) return
  const isJine = zDlg.isJine
  const suffix = isJine ? '_je' : ''
  const unit = isJine ? ' 元' : ' 升'
  const months = Array.from({ length: 12 }, (_, i) => `${i + 1}月`)
  const s0 = [], s92 = [], s95 = [], monthTotal = []
  for (let m = 1; m <= 12; m++) {
    const v0 = zData[`yue${m}_0${suffix}`] || 0
    const v92 = zData[`yue${m}_92${suffix}`] || 0
    const v95 = zData[`yue${m}_95${suffix}`] || 0
    s0.push(v0); s92.push(v92); s95.push(v95)
    monthTotal.push(Number((v0 + v92 + v95).toFixed(2)))
  }
  zInst.setOption({
    graphic: [
      { type: 'text', left: 'center', top: 10, style: { text: zData.kahao, fontSize: 16, fontWeight: 'bold', fill: '#333' } },
      { type: 'text', left: 'center', top: 35, style: { text: `${zData.nian}年全年油量：${zData.zong} 升`, fontSize: 13, fill: '#333' } },
      {
        type: 'group', left: 'center', top: 55,
        children: [
          { type: 'text', style: { text: `■ 0# ${zData.zong0} 升`, fill: '#1363F1', fontSize: 12 } },
          { type: 'text', left: 120, style: { text: `■ 92# ${zData.zong92} 升`, fill: '#44E448', fontSize: 12 } },
          { type: 'text', left: 260, style: { text: `■ 95# ${zData.zong95} 升`, fill: '#EC6941', fontSize: 12 } },
        ],
      },
      { type: 'text', left: 'center', top: 78, style: { text: `${zData.nian}年全年金额：${zData.zong_je} 元`, fontSize: 13, fill: '#333' } },
      {
        type: 'group', left: 'center', top: 98,
        children: [
          { type: 'text', style: { text: `■ 0# ¥${zData.zong0_je} 元`, fill: '#1363F1', fontSize: 12 } },
          { type: 'text', left: 120, style: { text: `■ 92# ¥${zData.zong92_je} 元`, fill: '#44E448', fontSize: 12 } },
          { type: 'text', left: 260, style: { text: `■ 95# ¥${zData.zong95_je} 元`, fill: '#EC6941', fontSize: 12 } },
        ],
      },
    ],
    tooltip: {
      trigger: 'axis', axisPointer: { type: 'shadow' },
      formatter: (params) => params
        .filter((p) => p.seriesName !== '月总量')
        .map((p) => `${p.marker}${p.seriesName}：${Number(p.value || 0).toFixed(2)}${unit}`)
        .join('<br/>'),
    },
    legend: { data: ['0#', '92#', '95#'], top: 125 },
    grid: { top: 155, left: 50, right: 30, bottom: 40 },
    xAxis: { type: 'category', data: months, axisLabel: { color: '#333' } },
    yAxis: { type: 'value', axisLabel: { color: '#333' } },
    series: [
      { name: '0#', type: 'bar', stack: 'oil', barWidth: 40, data: s0, itemStyle: { color: '#1363F1' } },
      { name: '92#', type: 'bar', stack: 'oil', barWidth: 40, data: s92, itemStyle: { color: '#44E448' } },
      { name: '95#', type: 'bar', stack: 'oil', barWidth: 40, data: s95, itemStyle: { color: '#EC6941' } },
      {
        name: '月总量', type: 'bar', data: monthTotal, barWidth: 0,
        itemStyle: { color: 'transparent' },
        label: {
          show: true, position: 'top', fontSize: 12, fontWeight: 'bold',
          align: 'left', padding: [0, 0, 0, -50], color: '#333',
          formatter: (p) => Number(p.value || 0).toFixed(2) + unit,
        },
      },
    ],
  }, true)
  zInst.resize()
}

// ===== 全年加油量悬停卡片(照旧 hoverCard:加油折线 + 派车次数折线) =====
const hoverCard = ref(null)
const hoverHideTimer = ref(null)
let hoverCharts = { oil: null, use: null }
let hoverReqSeq = 0
const hoverStatCache = reactive({})

function showHover(row, event) {
  clearTimeout(hoverHideTimer.value)
  const seq = ++hoverReqSeq
  const year = Number(row.niand) || new Date().getFullYear()
  hoverCard.value.style.display = 'block'
  positionHover(event)
  const key = `${row.cheid}_${year}`
  const onReady = (data) => {
    if (seq !== hoverReqSeq) return
    renderHoverCharts(data, row)
    positionHover(event)
  }
  if (hoverStatCache[key]) { onReady(hoverStatCache[key]); return }
  getMonthStat(row.cheid, year).then((d) => {
    hoverStatCache[key] = d.months
    onReady(d.months)
  }).catch(() => {
    if (seq === hoverReqSeq) hoverCard.value.querySelector('.cshc-foot').textContent = '加载失败'
  })
}
function hideHover() {
  clearTimeout(hoverHideTimer.value)
  hoverHideTimer.value = setTimeout(() => {
    hoverReqSeq++
    if (hoverCard.value) hoverCard.value.style.display = 'none'
  }, 150)
}
function positionHover(event) {
  const card = hoverCard.value
  const cw = card.offsetWidth, ch = card.offsetHeight
  const r = (event.target.closest('td') || event.target).getBoundingClientRect()
  const top = Math.min(Math.max(r.top, 8), Math.max(window.innerHeight - ch - 8, 8))
  let left = r.right + 10
  if (left + cw > window.innerWidth - 8) left = r.left - cw - 10
  if (left < 8) {
    left = Math.min(Math.max(r.left, 8), window.innerWidth - cw - 8)
    card.style.left = `${Math.round(left)}px`
    card.style.top = `${Math.round(Math.min(r.bottom + 6, window.innerHeight - ch - 8))}px`
    return
  }
  card.style.left = `${Math.round(left)}px`
  card.style.top = `${Math.round(top)}px`
}
function renderHoverCharts(data, row) {
  const card = hoverCard.value
  card.querySelector('.cshc-title').textContent = `${row.chehao} — ${row.niand}年`
  const months = [], oils = [], amounts = [], useCounts = []
  let tOil = 0, tAmount = 0, tUse = 0
  for (const it of data) {
    months.push(`${it.month}月`)
    oils.push(Number(it.oil) || 0)
    amounts.push(Number(it.amount) || 0)
    useCounts.push(Number(it.useCount) || 0)
    tOil += oils[oils.length - 1]; tAmount += amounts[amounts.length - 1]; tUse += useCounts[useCounts.length - 1]
  }
  card.querySelector('.cshc-foot').innerHTML =
    `合计升数 <strong>${tOil.toFixed(2)} L</strong> · 合计金额 <strong>${tAmount.toFixed(2)} 元</strong> · 派车 <strong>${tUse}</strong> 次`
  hoverCharts.oil = hoverCharts.oil || echarts.init(card.querySelector('#cshcOilChart'))
  hoverCharts.use = hoverCharts.use || echarts.init(card.querySelector('#cshcUseChart'))
  const axisCommon = {
    axisLine: { lineStyle: { color: 'rgba(180,150,90,0.4)' } },
    axisTick: { show: false },
    axisLabel: { color: '#a08551', fontSize: 9, interval: 0 },
  }
  const tooltipPaper = {
    trigger: 'axis', backgroundColor: '#fdf8e8', borderColor: '#cbb586',
    textStyle: { color: '#4a3b26', fontSize: 11 },
  }
  hoverCharts.oil.setOption({
    animation: false, tooltip: tooltipPaper,
    legend: { top: 0, right: 0, itemWidth: 12, itemHeight: 7, textStyle: { color: '#a08551', fontSize: 10 } },
    grid: { left: 2, right: 2, top: 20, bottom: 0, containLabel: true },
    xAxis: { type: 'category', data: months, ...axisCommon },
    yAxis: [
      { type: 'value', ...axisCommon, splitLine: { lineStyle: { color: 'rgba(180,150,90,0.18)' } } },
      { type: 'value', show: false },
    ],
    series: [
      { name: '升数(L)', type: 'line', smooth: true, symbol: 'circle', symbolSize: 4, data: oils, lineStyle: { width: 2, color: '#b07d1a' }, itemStyle: { color: '#b07d1a' } },
      { name: '金额(元)', type: 'line', smooth: true, symbol: 'none', yAxisIndex: 1, data: amounts, lineStyle: { width: 1.5, type: 'dashed', color: '#b07d1a' }, itemStyle: { color: '#b07d1a' } },
    ],
  }, true)
  hoverCharts.use.setOption({
    animation: false, tooltip: tooltipPaper,
    grid: { left: 2, right: 2, top: 10, bottom: 0, containLabel: true },
    xAxis: { type: 'category', data: months, ...axisCommon },
    yAxis: { type: 'value', ...axisCommon, splitLine: { lineStyle: { color: 'rgba(180,150,90,0.18)' } } },
    series: [{
      name: '派车次数', type: 'line', smooth: true, symbol: 'circle', symbolSize: 4,
      data: useCounts, lineStyle: { width: 2, color: '#c9881f' }, itemStyle: { color: '#c9881f' },
      areaStyle: { color: 'rgba(217,154,43,0.15)' },
    }],
  }, true)
}

// ===== 导出 =====
async function doExport(fn, label) {
  await fn(buildParams())
  ElMessage.success(`已导出${label}`)
}

function onResize() {
  chartInst?.resize()
  zInst?.resize()
}

onMounted(async () => {
  window.addEventListener('resize', onResize)
  load()
  const d = await getOiltjDicts()
  Object.assign(dicts, d)
  getOiltjMonths(filters.nian || 0).then((md) => {
    monthOptions.value = [{ value: -1, text: '==月份（上月）==' }]
      .concat(md.months.map((m) => ({ value: m, text: `${m}` })))
  })
  getOiltjCars(filters.bmid || 0).then((cd) => { carOptions.value = cd })
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  chartInst?.dispose()
  zInst?.dispose()
  hoverCharts.oil?.dispose()
  hoverCharts.use?.dispose()
})
</script>

<template>
  <div class="oiltj-page">
    <el-card shadow="never" class="filter-card">
      <div class="filter-title">车辆油量统计报表</div>
      <el-form inline class="filter-form" @submit.prevent>
        <el-form-item label="车号">
          <el-input v-model="filters.sousou" placeholder="输入车号模糊查询" clearable
            style="width: 180px" @keyup.enter="search" @clear="search" />
        </el-form-item>
        <el-form-item label="部门">
          <el-select v-model="filters.bmid" placeholder="选择部门" clearable filterable
            style="width: 170px" @change="onDeptChange">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="车辆类型">
          <el-select v-model="filters.clx" placeholder="车辆类型" clearable style="width: 130px" @change="search">
            <el-option v-for="lx in dicts.lx_used" :key="lx" :label="lx" :value="lx" />
          </el-select>
        </el-form-item>
        <el-form-item label="车辆">
          <el-select v-model="filters.chel" placeholder="选择车号" clearable filterable
            style="width: 220px" @change="search">
            <el-option v-for="c in carOptions" :key="c.value" :label="c.text" :value="c.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="年度">
          <el-select v-model="filters.nian" placeholder="年度(今年)" clearable style="width: 110px"
            @change="onYearChange">
            <el-option v-for="y in dicts.years" :key="y" :label="y" :value="y" />
          </el-select>
        </el-form-item>
        <el-form-item label="月份">
          <el-select v-model="filters.yue" style="width: 150px" @change="search">
            <el-option v-for="m in monthOptions" :key="m.value" :label="m.text" :value="m.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="车辆状态">
          <el-switch v-model="filters.px" active-text="所有" inactive-text="正常" @change="search" />
        </el-form-item>
        <el-form-item>
          <el-switch v-model="filters.nooilcard" active-text="非油卡" inactive-text="所有" @change="search" />
        </el-form-item>
        <el-form-item>
          <el-switch v-model="filters.oillie" active-text="柴油" inactive-text="油类" @change="search" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <el-card shadow="never" class="table-card">
      <div class="table-toolbar">
        <el-button @click="doExport(exportOiltjMonth, '月度报表')">导出月度报表</el-button>
        <el-button @click="doExport(exportOiltjYear, '年度报表')">导出年度报表</el-button>
        <el-button @click="doExport(exportOiltjFinance, '财务报表')">导出财务报表</el-button>
        <el-button @click="() => { const r = needOneRow(); if (r) openChart(r, 'gl') }">里程油耗图</el-button>
        <el-button @click="showZCharts">年度油量图表</el-button>
      </div>

      <el-table ref="tableRef" v-loading="loading" :data="rows" :row-class-name="rowClass"
        border stripe row-key="ID" @row-dblclick="(row) => dblclickRow(row)"
        @expand-change="loadExpand" @sort-change="onSortChange">
        <el-table-column type="selection" width="42" />
        <el-table-column type="expand">
          <template #default="{ row }">
            <el-table :data="[expandCache[row.cheid] || {}]" size="small" border class="expand-table">
              <el-table-column prop="chehao" label="车号" min-width="90" />
              <el-table-column prop="nian" label="年" width="70" />
              <el-table-column v-for="m in 12" :key="m" :label="`${m}月`" min-width="70">
                <template #default="{ row: sub }">{{ num2(sub[`yue${m}`]) }}</template>
              </el-table-column>
            </el-table>
          </template>
        </el-table-column>
        <el-table-column prop="ID" label="序号" width="55" />
        <el-table-column prop="bumen" label="部门" min-width="100" show-overflow-tooltip />
        <el-table-column prop="chehao" label="车号" min-width="100" show-overflow-tooltip />
        <el-table-column label="加油明细" width="82" align="center">
          <template #default="{ row }">
            <el-button link type="primary" title="查看加油" @click="openStat(row)">
              <el-icon><DataLine /></el-icon>
            </el-button>
          </template>
        </el-table-column>
        <el-table-column prop="bz" label="类型" min-width="110" show-overflow-tooltip />
        <el-table-column prop="cheyt" label="用途" width="90" />
        <el-table-column prop="niand" label="年度" width="70" />
        <el-table-column prop="yuef" label="月份" width="65" />
        <el-table-column prop="ngls" label="全年行驶公里" width="115" sortable="custom" />
        <el-table-column prop="noil" label="全年加油量（l）" width="130" sortable="custom">
          <template #default="{ row }">
            <span class="noil-hover" @mouseenter="(e) => showHover(row, e)">{{ num2(row.noil) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="times" label="年用车次数" width="95" />
        <el-table-column prop="delf" label="车辆状态" width="85">
          <template #default="{ row }">{{ statusText(row.delf) }}</template>
        </el-table-column>
        <el-table-column prop="bydgls" label="本月底公里数" width="115" />
        <el-table-column prop="sydgls" label="上月底公里数" width="115" />
        <el-table-column prop="yssgls" label="月行驶公里" width="100" />
        <el-table-column prop="yoil" label="月加油量（升）" width="110" />
        <el-table-column prop="monthLpkm" label="月百公里油耗" width="110" />
        <el-table-column prop="ye" label="余额" width="85" />
        <el-table-column prop="lpkm" label="百公里油耗" width="95" />
        <el-table-column prop="chuchang" label="注册日期" width="105" />
      </el-table>

      <el-pagination v-model:current-page="page" v-model:page-size="size"
        :total="total" :page-sizes="[20, 60, 200]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </el-card>

    <!-- 加油明细弹窗 -->
    <el-dialog v-model="statDlg.visible" :title="`车辆加油统计 - ${statDlg.chehao} (${statDlg.year}年)`"
      width="640px">
      <div class="stat-toolbar">
        <span>选择年份：</span>
        <el-select v-model="statDlg.year" style="width: 120px" @change="loadMonthStat">
          <el-option v-for="y in statYearOptions" :key="y" :label="`${y}年`" :value="y" />
        </el-select>
        <el-button style="margin-left: 10px" @click="loadMonthStat">查询</el-button>
      </div>
      <div class="stat-summary">
        合计金额：<strong>¥ {{ totalStat.amount }}</strong>　|　
        合计升数：<strong>{{ totalStat.oil }} L</strong>　|　
        总派车次数：<strong>{{ totalStat.useCount }} 次</strong>
      </div>
      <el-table v-loading="statDlg.loading" :data="statDlg.months" size="small" border>
        <el-table-column prop="month" label="月份" width="80" align="center">
          <template #default="{ row }">{{ row.month }}月</template>
        </el-table-column>
        <el-table-column label="加油金额(元)" align="center">
          <template #default="{ row }">¥ {{ Number(row.amount || 0).toFixed(2) }}</template>
        </el-table-column>
        <el-table-column label="加油升数(L)" align="center">
          <template #default="{ row }">{{ Number(row.oil || 0).toFixed(2) }} L</template>
        </el-table-column>
        <el-table-column label="派车次数(次)" align="center">
          <template #default="{ row }">{{ row.useCount }} 次</template>
        </el-table-column>
      </el-table>
    </el-dialog>

    <!-- 油量/里程图弹窗 -->
    <el-dialog v-model="chartDlg.visible" :title="chartDlg.title" width="820px"
      @closed="() => chartInst?.clear()">
      <div ref="chartRef" class="chart-box" />
      <template #footer>
        <el-button type="primary" @click="switchChartMode">
          {{ chartDlg.mode === 'oil' ? '里程图表' : '油量图表' }}
        </el-button>
        <el-button @click="chartDlg.visible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 年度油量堆叠图 -->
    <el-dialog v-model="zDlg.visible" title="年度油量图表" width="820px">
      <div class="z-toggle">
        升数
        <el-switch v-model="zDlg.isJine" active-text="金额" inactive-text="升数" @change="renderZChart" />
        金额
      </div>
      <div ref="zChartRef" class="chart-box z-chart" />
      <template #footer>
        <el-button @click="zDlg.visible = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 全年加油量悬停卡片 -->
    <div ref="hoverCard" class="car-stat-hover-card" @mouseenter="clearTimeout(hoverHideTimer)"
      @mouseleave="hideHover" style="display: none">
      <div class="cshc-title" />
      <div class="cshc-sub">加油明细（升数 / 金额）</div>
      <div id="cshcOilChart" class="cshc-chart" />
      <div class="cshc-sub">派车次数</div>
      <div id="cshcUseChart" class="cshc-chart" />
      <div class="cshc-foot" />
    </div>
  </div>
</template>

<style scoped>
.oiltj-page { padding: 0; }
.filter-card :deep(.el-card__body) { padding-bottom: 4px; }
.filter-title { font-size: 16px; font-weight: 600; margin-bottom: 10px; color: var(--el-text-color-primary); }
.table-toolbar { display: flex; margin-bottom: 10px; }
.noil-hover { cursor: pointer; text-decoration: underline dotted rgba(176, 125, 26, 0.55); text-underline-offset: 3px; }
.noil-hover:hover { color: #b07d1a; }
:deep(.oiltj-row-warn) { background: #ffe5b4 !important; }
:deep(.oiltj-row-warn td) { background: transparent !important; color: #b3261e; }
:deep(.oiltj-row-bad) { background: #f08080 !important; }
:deep(.oiltj-row-bad td) { background: transparent !important; }
.expand-table { margin: 4px 12px; width: auto; }

.stat-toolbar { display: flex; align-items: center; margin-bottom: 12px; }
.stat-summary {
  margin-bottom: 12px; padding: 8px 12px; border-radius: 4px; font-weight: 600;
  background: var(--el-fill-color-light); border: 1px solid var(--el-border-color-lighter);
  color: var(--el-text-color-primary);
}
.stat-summary strong { color: #b07d1a; }

.chart-box { width: 100%; height: 480px; }
.z-chart { height: 464px; }
.z-toggle { text-align: right; padding: 0 12px 4px 0; color: var(--el-text-color-regular); }

.car-stat-hover-card {
  position: fixed; z-index: 3000; width: 392px; padding: 10px 12px 8px;
  background: linear-gradient(145deg, #f6efdb, #f0e6c9);
  border: 1px solid #d8c49a; border-radius: 8px;
  box-shadow: 0 8px 24px rgba(120, 90, 30, 0.3); box-sizing: border-box;
}
.cshc-title { font-weight: 700; color: #7a5a28; font-size: 14px; margin-bottom: 4px; }
.cshc-sub { color: #a08551; font-size: 11px; margin: 4px 0 2px; }
.cshc-chart { width: 100%; height: 150px; }
.cshc-foot { color: #4a3b26; font-size: 12px; padding-top: 5px; margin-top: 4px; border-top: 1px dashed #d8c49a; }
.cshc-foot strong { color: #b07d1a; }
</style>
