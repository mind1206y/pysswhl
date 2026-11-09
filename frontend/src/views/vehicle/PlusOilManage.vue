<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { exportPlusOil, getPlusOilDicts, listPlusOil } from '@/api/plusoil'

const dicts = reactive({
  departments: [], lx: [], lei: [], status: [], yongtu: [],
  years: [], current_year: new Date().getFullYear(),
})

const now = new Date()
const pad = (n) => String(n).padStart(2, '0')
const fmtDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const yearStart = `${dicts.current_year}-01-01`
const today = fmtDate(now)

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(30)
const footer = ref({ oill: 0, jine: 0 })
const filters = reactive({
  keyword: '',
  dateRange: [yearStart, today],
  year: dicts.current_year,
  month: '',
  bmid: null,
  lei: '',
  chellx: '',
  chezhuangtai: null,
  chelyt: '',
})

function buildParams() {
  const p = { page: page.value, size: size.value }
  if (filters.keyword) p.keyword = filters.keyword
  if (Array.isArray(filters.dateRange) && filters.dateRange.length === 2) {
    p.start = filters.dateRange[0]
    p.end = filters.dateRange[1]
  }
  if (filters.bmid) p.bmid = filters.bmid
  if (filters.lei) p.lei = filters.lei
  if (filters.chellx) p.chellx = filters.chellx
  if (filters.chezhuangtai !== null && filters.chezhuangtai !== '') {
    p.chezhuangtai = filters.chezhuangtai
  }
  if (filters.chelyt) p.chelyt = filters.chelyt
  return p
}

async function load() {
  loading.value = true
  try {
    const data = await listPlusOil(buildParams())
    rows.value = data.items
    total.value = data.total
    footer.value = data.footer || { oill: 0, jine: 0 }
  } finally { loading.value = false }
}
function search() { page.value = 1; load() }

// 年份/月份快捷定位:选年=全年,选月=该月首尾日,同步写回日期框(照旧 applyNianyue)
function onYearMonthChange() {
  const y = Number(filters.year)
  if (!y) return
  if (filters.month) {
    const m = Number(filters.month)
    const lastDay = new Date(y, m, 0).getDate()
    filters.dateRange = [`${y}-${pad(m)}-01`, `${y}-${pad(m)}-${pad(lastDay)}`]
  } else {
    filters.dateRange = [`${y}-01-01`, `${y}-12-31`]
  }
  search()
}

function resetFilters() {
  Object.assign(filters, {
    keyword: '',
    dateRange: [`${dicts.current_year}-01-01`, fmtDate(new Date())],
    year: dicts.current_year,
    month: '',
    bmid: null,
    lei: '',
    chellx: '',
    chezhuangtai: null,
    chelyt: '',
  })
  search()
}

function money(v) { return Number(v || 0).toFixed(2) }

async function doExport() {
  await exportPlusOil(buildParams())
  ElMessage.success('已导出当前筛选记录')
}

onMounted(async () => {
  const d = await getPlusOilDicts()
  Object.assign(dicts, d)
  filters.year = d.current_year || new Date().getFullYear()
  filters.dateRange = [`${filters.year}-01-01`, fmtDate(new Date())]
  load()
})
</script>

<template>
  <div class="plusoil-page">
    <el-card shadow="never" class="filter-card">
      <div class="filter-title">加油明细</div>
      <el-form inline class="filter-form">
        <el-form-item label="关键字">
          <el-input v-model="filters.keyword" placeholder="卡号、车号、地点..." clearable
            style="width: 180px" @keyup.enter="search" />
        </el-form-item>
        <el-form-item label="日期">
          <el-date-picker v-model="filters.dateRange" type="daterange" value-format="YYYY-MM-DD"
            range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期"
            style="width: 240px" @change="search" />
        </el-form-item>
        <el-form-item label="年份">
          <el-select v-model="filters.year" style="width: 100px" @change="onYearMonthChange">
            <el-option v-for="y in dicts.years" :key="y" :label="`${y}年`" :value="y" />
          </el-select>
        </el-form-item>
        <el-form-item label="月份">
          <el-select v-model="filters.month" style="width: 90px" @change="onYearMonthChange">
            <el-option label="全年" value="" />
            <el-option v-for="m in 12" :key="m" :label="`${m}月`" :value="m" />
          </el-select>
        </el-form-item>
        <el-form-item label="油类">
          <el-select v-model="filters.lei" clearable style="width: 90px" @change="search">
            <el-option v-for="l in dicts.lei" :key="l" :label="l" :value="l" />
          </el-select>
        </el-form-item>
        <el-form-item label="车辆类型">
          <el-select v-model="filters.chellx" clearable filterable style="width: 160px" @change="search">
            <el-option v-for="t in dicts.lx" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="车辆状态">
          <el-select v-model="filters.chezhuangtai" clearable style="width: 100px" @change="search">
            <el-option v-for="s in dicts.status" :key="s.value" :label="s.label" :value="s.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="车辆用途">
          <el-select v-model="filters.chelyt" clearable style="width: 120px" @change="search">
            <el-option v-for="t in dicts.yongtu" :key="t" :label="t" :value="t" />
          </el-select>
        </el-form-item>
        <el-form-item label="部门">
          <el-select v-model="filters.bmid" placeholder="归属部门" clearable filterable
            style="width: 150px" @change="search">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <div class="toolbar">
      <el-button size="small" type="success" @click="doExport">导出当前记录</el-button>
      <span class="toolbar-hint">共 {{ total }} 条加油记录</span>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe size="small"
      height="calc(100vh - 340px)" row-key="ID">
      <el-table-column prop="ID" label="ID" width="72" align="center" />
      <el-table-column prop="bm" label="部门" width="110" show-overflow-tooltip />
      <el-table-column prop="kanum" label="油卡号" width="150" show-overflow-tooltip />
      <el-table-column prop="leibie" label="油品类" width="120" show-overflow-tooltip />
      <el-table-column prop="ptime" label="加油日期" width="135" />
      <el-table-column label="金额" width="100" align="right">
        <template #default="{ row }">{{ money(row.jine) }}</template>
      </el-table-column>
      <el-table-column label="油量" width="90" align="right">
        <template #default="{ row }">{{ money(row.oill) }}</template>
      </el-table-column>
      <el-table-column prop="lx" label="车类型" width="150" show-overflow-tooltip />
      <el-table-column prop="chehao" label="车号" width="110" />
      <el-table-column prop="lei" label="油类" width="72" align="center" />
      <el-table-column prop="didian" label="地点" min-width="180" show-overflow-tooltip />
    </el-table>

    <div class="footer-bar">
      <span class="footer-title">合计</span>
      <span>金额 <b>{{ money(footer.jine) }}</b> 元</span>
      <span>油量 <b>{{ money(footer.oill) }}</b> 升</span>
    </div>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[30, 60, 120]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>
  </div>
</template>

<style scoped>
.plusoil-page { display: flex; flex-direction: column; gap: 10px; }
.filter-card :deep(.el-card__body) { padding: 10px 14px; }
.filter-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 12px; }
.toolbar { display: flex; align-items: center; gap: 8px; }
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }
.footer-bar {
  display: flex; flex-wrap: wrap; gap: 24px; align-items: center;
  padding: 8px 12px; background: #f5f7fa; border: 1px solid #e4e7ed;
  border-radius: 4px; font-size: 13px; color: #606266;
}
.footer-title { font-weight: 600; color: #303133; }
.footer-bar b { color: #b07d1a; }
</style>
