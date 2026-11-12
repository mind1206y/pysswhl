<script setup>
import { nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import {
  createOilCard, deleteOilCard, downloadOilCardTemplate, exportOilCardBalance,
  exportOilCardDiff, exportOilCardManual, getMonthlyOilData, getOilCard,
  getOilCardDicts, getOilMonthStat, listOilCards, manualZero, updateOilCard,
  uploadOilCardExcel,
} from '@/api/oilcard'
import { useAuthStore } from '@/stores/auth'

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])

const auth = useAuthStore()
const canOperate = () => auth.hasPerm('oilcard:view')
const canManage = () => auth.hasPerm('oilcard:manage')

const dicts = reactive({
  status: [], oil: [], departments: [], cars: [], lx: [], yongtu: [],
  years: [], current_year: new Date().getFullYear(),
})

// ===== 列表 =====
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(28)
const footer = ref({})
const selected = ref(null)
const filters = reactive({ keyword: '', zt: '正常', bmid: null, chellx: '', chelyt: '' })

function buildParams() {
  const p = { page: page.value, size: size.value }
  if (filters.keyword) p.keyword = filters.keyword
  if (filters.zt) p.zt = filters.zt
  if (filters.bmid) p.bmid = filters.bmid
  if (filters.chellx) p.chellx = filters.chellx
  if (filters.chelyt) p.chelyt = filters.chelyt
  return p
}
async function load() {
  loading.value = true
  try {
    const data = await listOilCards(buildParams())
    rows.value = data.items
    total.value = data.total
    footer.value = data.footer || {}
  } finally { loading.value = false }
}
function search() { page.value = 1; selected.value = null; load() }
function resetFilters() {
  Object.assign(filters, { keyword: '', zt: '正常', bmid: null, chellx: '', chelyt: '' })
  search()
}
function money(v) { return Number(v || 0).toFixed(2) }
function day(v) { return v ? String(v).slice(0, 10) : '' }
function shortKanum(v) { return v && v.length >= 7 ? v.slice(-7) : (v || '') }
function rowClass({ row }) {
  if (row.zt !== '正常') return 'row-off'
  if (row.yujing === 1) return 'row-warn'
  return ''
}

onMounted(async () => {
  const d = await getOilCardDicts()
  Object.assign(dicts, d)
  load()
})

// ===== 新增 / 编辑 =====
const editVisible = ref(false)
const editingId = ref(null)
const editSaving = ref(false)
const formRef = ref()
const blankForm = () => ({
  kanum: '', yanzhengma: '', carid: null, youpin: '', zt: '正常', bz: '', handadd: 0,
})
const form = reactive(blankForm())
const rules = {
  kanum: [{ required: true, message: '请输入卡号', trigger: 'blur' }],
}
function openCreate() {
  editingId.value = null
  Object.assign(form, blankForm())
  editVisible.value = true
}
async function openEdit(row) {
  const target = row || selected.value
  if (!target) { ElMessage.warning('请先选择要编辑的油卡'); return }
  const info = await getOilCard(target.ID || target.id)
  editingId.value = info.id
  Object.assign(form, {
    kanum: info.kanum || '', yanzhengma: info.yanzhengma || '',
    carid: info.carid ?? null, youpin: info.youpin || '', zt: info.zt || '正常',
    bz: info.bz || '', handadd: info.handadd ?? 0,
  })
  editVisible.value = true
}
async function submitEdit() {
  if (editSaving.value) return  // 防双击重复提交
  editSaving.value = true
  try {
    await formRef.value.validate()
    const payload = { ...form }
    if (!payload.carid) payload.carid = null
    if (editingId.value) await updateOilCard(editingId.value, payload)
    else await createOilCard(payload)
    ElMessage.success(editingId.value ? '修改成功' : '添加成功')
    editVisible.value = false
    load()
  } finally { editSaving.value = false }
}
async function doDelete() {
  if (!selected.value) { ElMessage.warning('请先选择要删除的油卡'); return }
  await ElMessageBox.confirm(`确定删除油卡 ${selected.value.kanum}？`, '提示', { type: 'warning' })
  await deleteOilCard(selected.value.ID || selected.value.id)
  ElMessage.success('已删除')
  selected.value = null
  load()
}

// ===== 上传 / 模板 =====
const cardInput = ref()
const balanceInput = ref()
const xfInput = ref()
function pickUpload(kind) {
  if (kind === 'card') cardInput.value.click()
  else if (kind === 'balance') balanceInput.value.click()
  else xfInput.value.click()
}
async function onUploadFile(kind, e) {
  const file = e.target.files?.[0]
  e.target.value = ''
  if (!file) return
  const fd = new FormData()
  fd.append('file', file)
  const res = await uploadOilCardExcel(kind, fd)
  const parts = []
  if (res.imported) parts.push(`新增 ${res.imported}`)
  if (res.updated) parts.push(`更新 ${res.updated}`)
  if (res.skipped) parts.push(`跳过 ${res.skipped}`)
  ElMessage.success(`导入完成：${parts.join('，') || '无变化'}`)
  load()
}
const tplVisible = ref(false)
async function downloadTpl(type) {
  await downloadOilCardTemplate(type)
  ElMessage.success('模板已下载')
}
const diffVisible = ref(false)
const diffPrice = ref(8)
async function doExportBalance() {
  await exportOilCardBalance()
  ElMessage.success('已导出余额预警充值表')
}
async function doExportDiff(type) {
  await exportOilCardDiff(type, diffPrice.value)
  diffVisible.value = false
  ElMessage.success('已导出差额充值表')
}
async function doExportManual() {
  await exportOilCardManual()
  ElMessage.success('已导出手动充值表')
}
async function doManualZero() {
  await ElMessageBox.confirm('确定要把所有正常油卡的手动充值金额清零？', '提示', { type: 'warning' })
  const res = await manualZero()
  ElMessage.success(`已清零 ${res.count} 张油卡`)
  load()
}

// ===== 加油柱状图 =====
const chartVisible = ref(false)
const chartCard = ref(null)
const chartYear = ref(dicts.current_year)
const chartMode = ref('amount')
const chartData = ref([])
const chartEl = ref()
let chartInst = null

async function openChart(row) {
  chartCard.value = row
  chartYear.value = dicts.current_year
  chartMode.value = 'amount'
  chartData.value = await getMonthlyOilData(row.ID || row.id, chartYear.value)
  chartVisible.value = true
}
async function reloadChart() {
  chartData.value = await getMonthlyOilData(chartCard.value.ID || chartCard.value.id, chartYear.value)
  renderChart()
}
function initChart() {
  nextTick(() => {
    if (!chartEl.value) return
    if (chartInst) chartInst.dispose()
    chartInst = echarts.init(chartEl.value)
    renderChart()
  })
}
function switchMode(mode) {
  chartMode.value = mode
  renderChart()
}
function renderChart() {
  if (!chartInst) return
  const field = chartMode.value === 'amount' ? 'amount' : 'volume'
  const unit = chartMode.value === 'amount' ? '元' : '升'
  const values = chartData.value.map((d) => Number(d[field] || 0))
  const maxVal = Math.max(...values, 0)
  chartInst.setOption({
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    grid: { left: '3%', right: '4%', bottom: '3%', top: '8%', containLabel: true },
    xAxis: {
      type: 'category',
      data: chartData.value.map((d) => `${d.month}月`),
      axisLine: { lineStyle: { color: '#c9b283' } },
      axisLabel: { color: '#4a3b26' },
    },
    yAxis: {
      type: 'value', name: unit,
      nameTextStyle: { color: '#a08551' }, axisLabel: { color: '#4a3b26' },
    },
    series: [{
      type: 'bar',
      data: values.map((v) => ({
        value: v,
        itemStyle: {
          color: v === maxVal && maxVal > 0
            ? new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: '#c0453c' }, { offset: 1, color: '#931f18' },
            ])
            : new echarts.graphic.LinearGradient(0, 0, 0, 1, [
              { offset: 0, color: '#e6b96a' }, { offset: 1, color: '#c9881f' },
            ]),
        },
      })),
      barWidth: '50%',
      label: {
        show: true, position: 'top', color: '#4a3b26', fontSize: 11,
        formatter: (p) => (p.value > 0 ? p.value : ''),
      },
    }],
  }, true)
}
function closeChart() {
  if (chartInst) { chartInst.dispose(); chartInst = null }
}

// ===== 加油明细弹窗 =====
const statVisible = ref(false)
const statCard = ref(null)
const statYear = ref(dicts.current_year)
const statData = ref(null)
async function openStat(row) {
  statCard.value = row
  statYear.value = dicts.current_year
  statData.value = await getOilMonthStat(row.ID || row.id, statYear.value)
  statVisible.value = true
}
async function reloadStat() {
  statData.value = await getOilMonthStat(statCard.value.ID || statCard.value.id, statYear.value)
}

onBeforeUnmount(closeChart)
</script>

<template>
  <div class="oilcard-page">
    <input ref="cardInput" type="file" accept=".xls,.xlsx" style="display: none" @change="onUploadFile('card', $event)" />
    <input ref="balanceInput" type="file" accept=".xls,.xlsx" style="display: none" @change="onUploadFile('balance', $event)" />
    <input ref="xfInput" type="file" accept=".xls,.xlsx" style="display: none" @change="onUploadFile('transaction', $event)" />

    <el-card shadow="never" class="filter-card">
      <div class="filter-title">加油卡管理</div>
      <el-form inline class="filter-form">
        <el-form-item label="关键字">
          <el-input v-model="filters.keyword" placeholder="卡号、车号、备注..." clearable
            style="width: 200px" @keyup.enter="search" />
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.zt" clearable style="width: 100px">
            <el-option v-for="s in dicts.status" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <el-form-item label="部门">
          <el-select v-model="filters.bmid" placeholder="选择部门" clearable filterable style="width: 150px">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="filters.chellx" placeholder="车辆类型" clearable filterable style="width: 160px">
            <el-option v-for="t in dicts.lx" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="用途">
          <el-select v-model="filters.chelyt" placeholder="车辆用途" clearable style="width: 130px">
            <el-option v-for="t in dicts.yongtu" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <div class="toolbar">
      <template v-if="canOperate()">
        <el-button type="primary" size="small" @click="openCreate">添加</el-button>
        <el-button size="small" @click="openEdit()">编辑</el-button>
        <el-button v-if="canManage()" size="small" @click="doDelete">删除</el-button>
      </template>
      <template v-if="canManage()">
        <el-button size="small" @click="pickUpload('card')">上传油卡明细表</el-button>
        <el-button size="small" @click="pickUpload('balance')">上传余额记录</el-button>
        <el-button size="small" @click="pickUpload('transaction')">上传交易明细</el-button>
      </template>
      <el-button size="small" @click="tplVisible = true">下载模板</el-button>
      <el-button size="small" @click="doExportBalance">导出余额预警充值表</el-button>
      <el-button size="small" @click="diffVisible = true">导出差额充值表</el-button>
      <el-button size="small" @click="doExportManual">导出手动充值表</el-button>
      <el-button v-if="canManage()" size="small" type="warning" @click="doManualZero">手动充值清零</el-button>
      <span class="toolbar-hint">共 {{ total }} 张卡 · 双击行可编辑 · 点击卡号查看年度柱状图</span>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe size="small"
      height="calc(100vh - 330px)" highlight-current-row row-key="id"
      :row-class-name="rowClass" @current-change="(r) => (selected = r)" @row-dblclick="openEdit">
      <el-table-column prop="xuhao" label="序号" width="58" align="center" fixed="left" />
      <el-table-column label="卡号" width="120" fixed="left">
        <template #default="{ row }">
          <el-button link type="primary" :title="row.kanum" @click="openChart(row)">
            {{ shortKanum(row.kanum) }}
          </el-button>
        </template>
      </el-table-column>
      <el-table-column prop="bumen" label="部门" width="100" show-overflow-tooltip />
      <el-table-column prop="chehao" label="车号" width="110" show-overflow-tooltip />
      <el-table-column prop="paicheCount" label="年度派车次数" width="105" align="center" />
      <el-table-column label="年度合计升数" width="110" align="center">
        <template #default="{ row }">{{ money(row.nianOilL) }}</template>
      </el-table-column>
      <el-table-column label="加油明细" width="82" align="center">
        <template #default="{ row }">
          <el-button link type="primary" @click="openStat(row)">明细</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="clx" label="类型" width="150" show-overflow-tooltip />
      <el-table-column prop="cyt" label="用途" width="95" show-overflow-tooltip />
      <el-table-column label="预警" width="90" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.yujing === 1" type="danger" size="small">余额预警</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="备付金" width="80" align="right">
        <template #default="{ row }">{{ money(row.bfj) }}</template>
      </el-table-column>
      <el-table-column label="余额" width="80" align="right">
        <template #default="{ row }">{{ money(row.ye) }}</template>
      </el-table-column>
      <el-table-column label="总余额" width="86" align="right">
        <template #default="{ row }">{{ money(row.zh) }}</template>
      </el-table-column>
      <el-table-column label="最高量" width="78" align="right">
        <template #default="{ row }">{{ money(row.maxMonthlyOil) }}</template>
      </el-table-column>
      <el-table-column label="平均量" width="78" align="right">
        <template #default="{ row }">{{ money(row.avgLast3MonthsOil) }}</template>
      </el-table-column>
      <el-table-column label="本月差额" width="86" align="right">
        <template #default="{ row }">{{ money(row.ce) }}</template>
      </el-table-column>
      <el-table-column label="本月金额" width="86" align="right">
        <template #default="{ row }">{{ money(row.benyueOil) }}</template>
      </el-table-column>
      <el-table-column label="上月金额" width="86" align="right">
        <template #default="{ row }">{{ money(row.shangyueOil) }}</template>
      </el-table-column>
      <el-table-column label="最后加油日" width="100" align="center">
        <template #default="{ row }">{{ day(row.lastAddOilDate) }}</template>
      </el-table-column>
      <el-table-column label="登记日期" width="100" align="center">
        <template #default="{ row }">{{ day(row.djdate) }}</template>
      </el-table-column>
      <el-table-column label="状态" width="76" align="center">
        <template #default="{ row }">
          <el-tag :type="row.zt === '正常' ? 'success' : (row.zt === '停用' ? 'warning' : 'info')"
            size="small">{{ row.zt }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="youpin" label="油品" width="66" align="center" />
      <el-table-column label="编辑日期" width="100" align="center">
        <template #default="{ row }">{{ day(row.editdate) }}</template>
      </el-table-column>
      <el-table-column label="手动充值" width="86" align="right">
        <template #default="{ row }">{{ money(row.handadd) }}</template>
      </el-table-column>
      <el-table-column prop="bz" label="备注" min-width="150" show-overflow-tooltip />
      <el-table-column prop="ID" label="ID" width="60" align="center" />
    </el-table>

    <div class="footer-bar">
      <span class="footer-title">合计</span>
      <span>总余额 <b>{{ money(footer.zh) }}</b></span>
      <span>备付金 <b>{{ money(footer.bfj) }}</b></span>
      <span>余额 <b>{{ money(footer.ye) }}</b></span>
      <span>本月金额 <b>{{ money(footer.benyueOil) }}</b></span>
      <span>上月金额 <b>{{ money(footer.shangyueOil) }}</b></span>
      <span>本月差额 <b>{{ money(footer.ce) }}</b></span>
    </div>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[28, 90, 200]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>

    <!-- 添加 / 编辑 -->
    <el-dialog v-model="editVisible" :title="editingId ? '编辑油卡' : '新增油卡'" width="560px">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="86px">
        <el-form-item label="卡号" prop="kanum"><el-input v-model="form.kanum" /></el-form-item>
        <el-form-item label="验证码"><el-input v-model="form.yanzhengma" /></el-form-item>
        <el-form-item label="车号">
          <el-select v-model="form.carid" clearable filterable placeholder="选择车辆" style="width: 100%">
            <el-option v-for="c in dicts.cars" :key="c.id" :label="c.chehao" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="油品">
          <el-select v-model="form.youpin" clearable style="width: 100%">
            <el-option v-for="o in dicts.oil" :key="o" :label="o" :value="o" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="form.zt" style="width: 100%">
            <el-option v-for="s in dicts.status" :key="s" :label="s" :value="s" />
          </el-select>
        </el-form-item>
        <template v-if="editingId">
          <el-form-item label="手动充值">
            <el-input-number v-model="form.handadd" :precision="2" :min="0"
              controls-position="right" style="width: 100%" />
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="form.bz" type="textarea" :rows="3" />
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="submitEdit">确定</el-button>
      </template>
    </el-dialog>

    <!-- 下载模板 -->
    <el-dialog v-model="tplVisible" title="下载上传模板" width="380px">
      <div class="tpl-links">
        <el-button type="primary" plain @click="downloadTpl('card')">油卡明细表模板.xlsx</el-button>
        <el-button type="primary" plain @click="downloadTpl('yue')">余额记录模板.xlsx</el-button>
        <el-button type="primary" plain @click="downloadTpl('xf')">消费明细模板.xlsx</el-button>
      </div>
      <div class="tip">上传文件表头须与模板一致，否则会被拦截。</div>
    </el-dialog>

    <!-- 差额充值导出 -->
    <el-dialog v-model="diffVisible" title="选择导出方式" width="420px">
      <div class="diff-box">
        <span>油价：</span>
        <el-select v-model="diffPrice" style="width: 160px">
          <el-option v-for="p in [5, 6, 7, 8, 9, 10]" :key="p" :label="`${p} 元/升${p === 8 ? '（默认）' : ''}`" :value="p" />
        </el-select>
      </div>
      <div class="diff-btns">
        <el-button type="primary" @click="doExportDiff('new')">智能预测（推荐）</el-button>
        <el-button @click="doExportDiff('old')">历史最高差额</el-button>
      </div>
    </el-dialog>

    <!-- 加油柱状图 -->
    <el-dialog v-model="chartVisible" :title="`${chartCard?.kanum || ''} - 加油统计`"
      width="760px" @opened="initChart" @close="closeChart">
      <div class="chart-head">
        <el-select v-model="chartYear" style="width: 110px" @change="reloadChart">
          <el-option v-for="y in dicts.years" :key="y" :label="`${y}年`" :value="y" />
        </el-select>
        <el-button size="small" :type="chartMode === 'amount' ? 'primary' : ''" @click="switchMode('amount')">金额</el-button>
        <el-button size="small" :type="chartMode === 'volume' ? 'primary' : ''" @click="switchMode('volume')">油量（升）</el-button>
      </div>
      <div ref="chartEl" class="chart-box" />
    </el-dialog>

    <!-- 加油月度明细 -->
    <el-dialog v-model="statVisible" :title="`油卡加油统计 - ${statCard?.chehao || ''}`" width="760px">
      <div class="chart-head">
        <el-select v-model="statYear" style="width: 110px" @change="reloadStat">
          <el-option v-for="y in dicts.years" :key="y" :label="`${y}年`" :value="y" />
        </el-select>
        <el-button size="small" @click="reloadStat">查询</el-button>
      </div>
      <div class="stat-summary" v-if="statData">
        合计金额：<b>{{ money(statData.total_amount) }}</b> 元 &nbsp;|&nbsp;
        合计升数：<b>{{ money(statData.total_oil) }}</b> L &nbsp;|&nbsp;
        总派车次数：<b>{{ statData.total_use_count }}</b> 次
      </div>
      <el-table :data="statData?.months || []" size="small" border max-height="420">
        <el-table-column prop="month" label="月份" width="80">
          <template #default="{ row }">{{ row.month }}月</template>
        </el-table-column>
        <el-table-column label="加油金额(元)" width="150">
          <template #default="{ row }">{{ money(row.amount) }}</template>
        </el-table-column>
        <el-table-column label="加油升数(L)" width="150">
          <template #default="{ row }">{{ money(row.oil) }}</template>
        </el-table-column>
        <el-table-column prop="useCount" label="派车次数(次)" width="130" />
      </el-table>
    </el-dialog>
  </div>
</template>

<style scoped>
.oilcard-page { display: flex; flex-direction: column; gap: 10px; }
.filter-card :deep(.el-card__body) { padding: 10px 14px; }
.filter-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 12px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }
.footer-bar {
  display: flex; flex-wrap: wrap; gap: 20px; align-items: center;
  padding: 8px 12px; background: #f5f7fa; border: 1px solid #e4e7ed;
  border-radius: 4px; font-size: 13px; color: #606266;
}
.footer-title { font-weight: 600; color: #303133; }
.footer-bar b { color: #b07d1a; }
.tpl-links { display: flex; flex-direction: column; gap: 10px; }
.tip { color: #909399; font-size: 12px; margin-top: 10px; }
.diff-box { display: flex; align-items: center; gap: 8px; margin-bottom: 18px; }
.diff-btns { display: flex; gap: 12px; }
.chart-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.chart-box { width: 100%; height: 380px; }
.stat-summary {
  margin-bottom: 10px; padding: 8px 12px; background: #f0e7cc;
  border: 1px solid #d8c49a; border-radius: 4px; font-weight: 600; color: #4a3b26;
}
.stat-summary b { color: #b07d1a; }
:deep(.row-warn) { color: #d0302f; }
:deep(.row-off) { background-color: #ffeecd !important; }
</style>
