<script setup>
/**
 * 材料结算单查看 —— 照旧 Views/Jiesuan/Index.cshtml 1:1 复刻(只读)
 * 顶部关键字搜索(材料名称或单号),列表展示领料明细的结算状态;
 * 剩余可结算 <= 0 的行灰显(照旧 row-settled)。
 */
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { listJiesuanView } from '@/api/jiesuan'

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = reactive({ current: 1, size: 20 })
const keyword = ref('')

const tableWrap = ref(null)
const tableH = ref(480)
let observer = null

function fitTable() {
  if (tableWrap.value) tableH.value = Math.max(160, tableWrap.value.clientHeight)
}
function onResize() { fitTable() }

async function load() {
  loading.value = true
  try {
    const params = { page: page.current, size: page.size }
    if (keyword.value) params.keyword = keyword.value
    const res = await listJiesuanView(params)
    rows.value = res.rows
    total.value = res.total
  } finally {
    loading.value = false
  }
}

function search() {
  page.current = 1
  load()
}

function reset() {
  keyword.value = ''
  search()
}

function rowClass({ row }) {
  return Number(row.shengyu || 0) <= 0 ? 'row-settled' : ''
}

function numText(v) {
  const n = Number(v || 0)
  return Number.isInteger(n) ? String(n) : String(Number(n.toFixed(4)))
}

onMounted(() => {
  load()
  window.addEventListener('resize', onResize)
  fitTable()
  if (typeof ResizeObserver !== 'undefined') {
    observer = new ResizeObserver(fitTable)
    if (tableWrap.value) observer.observe(tableWrap.value)
  }
})
onBeforeUnmount(() => {
  window.removeEventListener('resize', onResize)
  if (observer) { observer.disconnect(); observer = null }
})
</script>

<template>
  <div class="js-page">
    <el-card shadow="never" class="filter-card">
      <div class="filter-title">材料结算单查看</div>
      <el-form inline class="filter-form">
        <el-form-item label="搜索">
          <el-input v-model="keyword" clearable style="width: 320px"
            placeholder="输入材料名称或单号回车查询"
            @keyup.enter="search" @clear="search" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
          <el-button @click="reset">重置</el-button>
        </el-form-item>
        <span class="toolbar-hint">共 {{ total }} 条 · 剩余可结算为 0 的行灰显</span>
      </el-form>
    </el-card>

    <el-card shadow="never" class="table-card">
      <div ref="tableWrap" class="js-table-wrap">
        <el-table v-loading="loading" :data="rows" border size="small"
          :max-height="tableH" row-key="id" :row-class-name="rowClass">
          <el-table-column prop="danno" label="领料单号" width="155" show-overflow-tooltip />
          <el-table-column prop="gongyingshang" label="供应商" min-width="190"
            show-overflow-tooltip />
          <el-table-column prop="sqriqi" label="领料日期" width="105" />
          <el-table-column prop="llname" label="材料名称" min-width="150"
            show-overflow-tooltip />
          <el-table-column prop="model" label="型号" width="110" show-overflow-tooltip />
          <el-table-column prop="spec" label="规格" width="110" show-overflow-tooltip />
          <el-table-column prop="unit" label="单位" width="65" align="center" />
          <el-table-column label="可结算数量" width="100" align="center">
            <template #default="{ row }">{{ numText(row.renum) }}</template>
          </el-table-column>
          <el-table-column label="已结算数量" width="100" align="center">
            <template #default="{ row }">{{ numText(row.jiesuannum) }}</template>
          </el-table-column>
          <el-table-column label="剩余可结算" width="100" align="center">
            <template #default="{ row }">{{ numText(row.shengyu) }}</template>
          </el-table-column>
          <el-table-column prop="jsrq" label="结算日期" width="105" align="center" />
          <el-table-column prop="id" label="材料ID" width="75" align="center" />
          <el-table-column prop="beizhu" label="备注" min-width="140"
            show-overflow-tooltip />
        </el-table>
      </div>
      <div class="pager">
        <el-pagination v-model:current-page="page.current" v-model:page-size="page.size"
          :total="total" :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="load" @size-change="search" />
      </div>
    </el-card>
  </div>
</template>

<style scoped>
.js-page {
  box-sizing: border-box;
  height: calc(100vh - 94px);
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow: hidden;
}
.filter-card { flex: 0 0 auto; }
.filter-card :deep(.el-card__body) { padding: 8px 12px; }
.filter-title { font-size: 15px; font-weight: 600; margin-bottom: 6px; }
.filter-form { display: flex; align-items: center; }
.filter-form :deep(.el-form-item) { margin-bottom: 0; margin-right: 10px; }
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.table-card { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
.table-card :deep(.el-card__body) {
  padding: 6px 8px; flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column;
}
.js-table-wrap { flex: 1 1 auto; min-height: 0; overflow: hidden; }
.pager { flex: 0 0 auto; display: flex; justify-content: flex-end; margin-top: 4px; }
.js-page :deep(.el-table--small .el-table__cell) { padding: 2px 0; }
.js-page :deep(.el-table .cell) { line-height: 20px; padding: 0 4px; }
.js-page :deep(.el-table__header-wrapper th) { padding: 3px 0; }
/* 只保留两种底色:普通行白底 + 已结算行(剩余可结算=0)灰底 */
.js-page :deep(.el-table__body tr.row-settled > td.el-table__cell) {
  background: #f2f2f2 !important;
  color: #999 !important;
}
@media (max-height: 760px) {
  .js-page { gap: 5px; }
  .filter-title { margin-bottom: 4px; }
}
</style>
