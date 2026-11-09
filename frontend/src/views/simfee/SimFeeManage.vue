<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  exportEmptyYongtu,
  exportSimFees,
  getSimFeeDicts,
  getSimFeeMonths,
  listSimFees,
} from '@/api/simfee'

const money = (v) => Number(v || 0).toFixed(2)

const dicts = reactive({
  departments: [],
  years: [],
  months: [],
  default_year: null,
  default_month: null,
  current_year: null,
  current_month: null,
})

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const tj = ref('0.00')
const page = ref(1)
const size = ref(20)
const filters = reactive({
  keyword: '',
  bmid: null,
  year: null,
  month: null,
  onlySelf: false,
})

function buildParams() {
  const p = { year: filters.year, month: filters.month, only_self: filters.onlySelf }
  if (filters.bmid) p.bmid = filters.bmid
  if (filters.keyword) p.keyword = filters.keyword
  return p
}

async function load() {
  if (!filters.year || !filters.month) {
    rows.value = []
    total.value = 0
    tj.value = '0.00'
    return
  }
  loading.value = true
  try {
    const data = await listSimFees({ ...buildParams(), page: page.value, size: size.value })
    rows.value = data.items || []
    total.value = data.total || 0
    tj.value = data.tj || '0.00'
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

async function onYearChange() {
  const y = filters.year
  if (!y) {
    filters.month = null
    dicts.months = []
    load()
    return
  }
  const data = await getSimFeeMonths(y)
  const months = data.months || []
  dicts.months = months
  filters.month = months.length ? months[months.length - 1] : null
  search()
}

function resetFilters() {
  Object.assign(filters, {
    keyword: '',
    bmid: null,
    year: dicts.default_year,
    month: dicts.default_month,
    onlySelf: false,
  })
  dicts.months = []
  getSimFeeMonths(filters.year).then((data) => {
    dicts.months = data.months || []
    search()
  })
}

function rowClassName({ row }) {
  return !row.yongtu ? 'row-no-yongtu' : ''
}

async function doExport() {
  if (!filters.year || !filters.month) {
    ElMessage.warning('请先选择年度和月份')
    return
  }
  await exportSimFees(buildParams())
  ElMessage.success('已导出当前筛选记录')
}

async function doExportEmpty() {
  if (!filters.year) {
    ElMessage.warning('请先选择正确的年度')
    return
  }
  await exportEmptyYongtu(filters.year)
  ElMessage.success('已导出年度用途为空的记录')
}

async function init() {
  const data = await getSimFeeDicts()
  Object.assign(dicts, data)
  filters.year = data.default_year
  filters.month = data.default_month
  load()
}

onMounted(init)
</script>

<template>
  <div class="fee-page">
    <div class="page-head">
      <div>
        <div class="page-title">通信费用明细表</div>
        <div class="page-sub">按年度 / 月份查看 SIM 卡话费，年度合计含该卡全年各月</div>
      </div>
      <div class="head-actions">
        <el-button @click="doExport">导出 EXCEL</el-button>
        <el-button @click="doExportEmpty">导出年度用途为空</el-button>
      </div>
    </div>

    <el-card shadow="never" class="filter-card">
      <div class="filters">
        <el-input
          v-model="filters.keyword"
          placeholder="卡号 / 地点 / 用途"
          clearable
          class="filter-search"
          @keyup.enter="search"
          @clear="search"
        />
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="resetFilters">重置</el-button>
        <span class="switch-label">本人</span>
        <el-switch v-model="filters.onlySelf" @change="search" />
        <el-select
          v-model="filters.bmid"
          clearable
          filterable
          placeholder="费用归属部门"
          class="filter-item"
          @change="search"
        >
          <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
        </el-select>
        <el-select
          v-model="filters.year"
          placeholder="选择年度"
          class="filter-small"
          @change="onYearChange"
        >
          <el-option v-for="y in dicts.years" :key="y" :label="`${y} 年`" :value="y" />
        </el-select>
        <el-select
          v-model="filters.month"
          clearable
          placeholder="选择月份"
          class="filter-small"
          @change="search"
        >
          <el-option v-for="m in dicts.months" :key="m" :label="`${m} 月`" :value="m" />
        </el-select>
        <span class="total-text">总计金额：{{ tj }} 元</span>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table
        v-loading="loading"
        :data="rows"
        border
        stripe
        row-key="id"
        :row-class-name="rowClassName"
        max-height="calc(100vh - 300px)"
      >
        <el-table-column prop="bm" label="卡的部门" width="120" show-overflow-tooltip />
        <el-table-column prop="kahao" label="卡号" width="155" show-overflow-tooltip />
        <el-table-column prop="zt" label="状态" width="100" />
        <el-table-column label="当月费用" width="110" align="right">
          <template #default="{ row }">{{ money(row.jine) }}</template>
        </el-table-column>
        <el-table-column label="年度合计费用" width="125" align="right">
          <template #default="{ row }">{{ money(row.huizongjine) }}</template>
        </el-table-column>
        <el-table-column prop="yongtu" label="用途" min-width="160" show-overflow-tooltip />
        <el-table-column prop="wangluo" label="网络" width="110" />
        <el-table-column prop="zhanghu" label="账户" width="110" />
        <el-table-column prop="didian" label="卡地点" min-width="180" show-overflow-tooltip />
        <el-table-column prop="bz" label="卡备注" min-width="160" show-overflow-tooltip />
        <el-table-column prop="nian" label="年" width="75" align="center" />
        <el-table-column prop="yue" label="月" width="65" align="center" />
        <el-table-column prop="syren" label="上传人" width="100" />
        <el-table-column prop="upbm" label="费用归属部门" width="130" show-overflow-tooltip />
      </el-table>
      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          :total="total"
          :page-sizes="[20, 200, 400]"
          layout="total, sizes, prev, pager, next, jumper"
          background
          @current-change="load"
          @size-change="search"
        />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.fee-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.page-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  flex-wrap: wrap;
}
.page-title {
  font-size: 20px;
  font-weight: 600;
  color: #1c1e54;
}
.page-sub {
  margin-top: 4px;
  font-size: 12px;
  color: #64748d;
}
.head-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.filter-card :deep(.el-card__body) {
  padding: 14px 16px;
}
.filters {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}
.filter-search {
  width: 260px;
  max-width: 100%;
}
.filter-item {
  width: 180px;
}
.filter-small {
  width: 120px;
}
.switch-label {
  font-size: 13px;
  color: #475569;
  margin-left: 4px;
}
.total-text {
  margin-left: auto;
  color: #c62828;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}
.table-card :deep(.el-card__body) {
  padding: 0;
}
.pager {
  display: flex;
  justify-content: flex-end;
  padding: 12px 16px;
}
.table-card :deep(.row-no-yongtu) td {
  background: rgba(198, 40, 40, 0.08) !important;
  color: #c62828;
}
@media (max-width: 768px) {
  .filter-search {
    width: 100%;
  }
  .total-text {
    margin-left: 0;
  }
}
</style>
