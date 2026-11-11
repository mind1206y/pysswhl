<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { exportChelfytj, getChelfytjDicts, listChelfytj } from '@/api/chelfytj'

// ===== 字典(类型/用途/部门,照旧 Index 预载) =====
const dicts = reactive({ chellx: [], chelyt: [], departments: [], my_dept: '' })

// ===== 筛选(照旧搜索条:关键字/日期范围/年度/部门/类型/用途/状态/非油卡) =====
const filters = reactive({
  sousou: '', rq: '', rqend: '', year: '', bmid: null,
  chellx: '', chelyt: '', zt: '0', nocd: false,
})
// 默认日期范围照旧:今年 1 月 1 日 ~ 今天
const now = new Date()
const _pad = (n) => String(n).padStart(2, '0')
const _fmt = (d) => `${d.getFullYear()}-${_pad(d.getMonth() + 1)}-${_pad(d.getDate())}`
filters.rq = `${now.getFullYear()}-01-01`
filters.rqend = _fmt(now)

// 年度快捷选择(照旧 initYearSelector:今年 ~ 近 5 年)
const yearOptions = []
for (let y = now.getFullYear(); y >= now.getFullYear() - 5; y--) yearOptions.push(y)

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const footer = ref({ oil: '合计', noil: 0, weixiu: 0, baoxian: 0, gaosu: 0, tingche: 0, xiche: 0, ye: 0 })
const page = ref(1)
const size = ref(20)

function buildParams(withPage = true) {
  const p = { rq: filters.rq, rqend: filters.rqend, zt: filters.zt }
  if (filters.sousou) p.sousou = filters.sousou
  if (filters.bmid) p.bmid = filters.bmid
  if (filters.chellx) p.chellx = filters.chellx
  if (filters.chelyt) p.chelyt = filters.chelyt
  if (filters.nocd) p.nocd = true
  if (withPage) { p.page = page.value; p.size = size.value }
  return p
}

async function load() {
  loading.value = true
  try {
    const data = await listChelfytj(buildParams())
    rows.value = data.rows
    total.value = data.total
    footer.value = { oil: '合计', ...(data.footer || {}) }
  } finally { loading.value = false }
}

function search() { page.value = 1; load() }

// 年度快捷:选年自动填 1-1 ~ 12-31 并查询(照旧 yearSel.change)
function onYearChange(v) {
  if (v) {
    filters.rq = `${v}-01-01`
    filters.rqend = `${v}-12-31`
  }
  search()
}
// 手动改日期时清除年度快捷选择(照旧 sou)
function onDateChange() { filters.year = ''; search() }

function resetFilters() {
  filters.sousou = ''
  filters.year = ''
  filters.bmid = null
  filters.chellx = ''
  filters.chelyt = ''
  filters.zt = '0'
  filters.nocd = false
  filters.rq = `${now.getFullYear()}-01-01`
  filters.rqend = _fmt(now)
  search()
}

function money(v) {
  return v === null || v === undefined || v === '' ? '' : Number(v).toFixed(2)
}

// footer 合计行(照旧 showFooter:合计栏与列表行同口径)
function summaryMethod({ columns }) {
  return columns.map((c) => {
    if (c.property === 'oil') return '合计'
    const v = footer.value[c.property]
    return ['noil', 'weixiu', 'baoxian', 'gaosu', 'tingche', 'xiche', 'ye'].includes(c.property)
      ? money(v) : ''
  })
}

// 结束日期不早于开始日期(照旧 equaldDate)
const dateDisabled = (d) => {
  if (!filters.rq) return false
  return d.getTime() < new Date(filters.rq).getTime()
}

const exporting = ref(false)
async function doExport() {
  exporting.value = true
  try {
    await exportChelfytj(buildParams(false))
    ElMessage.success('已导出 Excel')
  } finally { exporting.value = false }
}

onMounted(async () => {
  const d = await getChelfytjDicts()
  Object.assign(dicts, d)
  load()
})
</script>

<template>
  <div class="chelfytj-page">
    <!-- 查询条件(照旧 search-panel) -->
    <el-card shadow="never" class="filter-card">
      <div class="filter-title">车辆费用明细统计</div>
      <el-form inline class="filter-form">
        <el-form-item>
          <el-input v-model="filters.sousou" placeholder="输入车号或油卡号查询"
            clearable style="width: 200px" @keyup.enter="search" />
        </el-form-item>
        <el-form-item label="日期范围">
          <el-date-picker v-model="filters.rq" type="date" value-format="YYYY-MM-DD"
            :editable="false" :clearable="false" placeholder="开始日期"
            style="width: 130px" @change="onDateChange" />
          <span class="range-sep">至</span>
          <el-date-picker v-model="filters.rqend" type="date" value-format="YYYY-MM-DD"
            :editable="false" :clearable="false" placeholder="结束日期"
            :disabled-date="dateDisabled" style="width: 130px" @change="onDateChange" />
        </el-form-item>
        <el-form-item label="年度">
          <el-select v-model="filters.year" placeholder="按年度" clearable
            style="width: 100px" @change="onYearChange">
            <el-option v-for="y in yearOptions" :key="y" :label="`${y}年`" :value="y" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-select v-model="filters.bmid" placeholder="选择部门" clearable filterable
            style="width: 130px">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-select v-model="filters.chellx" placeholder="选择类型" clearable filterable
            style="width: 130px">
            <el-option v-for="t in dicts.chellx" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-select v-model="filters.chelyt" placeholder="选择用途" clearable filterable
            style="width: 130px">
            <el-option v-for="t in dicts.chelyt" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-select v-model="filters.zt" style="width: 92px">
            <el-option label="全部" value="0" />
            <el-option label="正常" value="1" />
            <el-option label="已报废" value="2" />
            <el-option label="已删除" value="3" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-switch v-model="filters.nocd" active-text="非油卡" inactive-text="所有" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 工具栏(照旧 datagrid toolbar) -->
    <div class="toolbar">
      <el-button type="primary" size="small" :loading="exporting" @click="doExport">导出Excel</el-button>
      <span class="toolbar-hint">共 {{ total }} 辆车 · {{ filters.rq }} 至 {{ filters.rqend }}</span>
    </div>

    <!-- 主表格(照旧 gettable 11 列 + footer 合计行) -->
    <el-table v-loading="loading" :data="rows" border stripe size="small"
      height="calc(100vh - 330px)" show-summary :summary-method="summaryMethod">
      <el-table-column prop="ID" label="ID" width="56" align="center" />
      <el-table-column prop="bumen" label="部门" width="130" show-overflow-tooltip />
      <el-table-column prop="chehao" label="车号" width="110" align="center" />
      <el-table-column prop="oil" label="油品类" width="90" align="center" />
      <el-table-column prop="baoxian" label="保险金额" width="100" align="right">
        <template #default="{ row }">{{ money(row.baoxian) }}</template>
      </el-table-column>
      <el-table-column prop="noil" label="油费" width="100" align="right">
        <template #default="{ row }">{{ money(row.noil) }}</template>
      </el-table-column>
      <el-table-column prop="weixiu" label="维修金额" width="100" align="right">
        <template #default="{ row }">{{ money(row.weixiu) }}</template>
      </el-table-column>
      <el-table-column prop="gaosu" label="高速费" width="90" align="right">
        <template #default="{ row }">{{ money(row.gaosu) }}</template>
      </el-table-column>
      <el-table-column prop="xiche" label="洗车费" width="90" align="right">
        <template #default="{ row }">{{ money(row.xiche) }}</template>
      </el-table-column>
      <el-table-column prop="tingche" label="停车费" width="90" align="right">
        <template #default="{ row }">{{ money(row.tingche) }}</template>
      </el-table-column>
      <el-table-column prop="ye" label="小计" min-width="110" align="right">
        <template #default="{ row }">{{ money(row.ye) }}</template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[20, 60, 120]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>
  </div>
</template>

<style scoped>
.chelfytj-page { display: flex; flex-direction: column; gap: 10px; }
.filter-card :deep(.el-card__body) { padding: 10px 14px; }
.filter-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 12px; }
.range-sep { margin: 0 4px; color: #606266; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }
</style>
