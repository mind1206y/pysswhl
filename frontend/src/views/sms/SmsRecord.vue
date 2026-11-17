<script setup>
import { onMounted, reactive, ref } from 'vue'
import { listSmsRecords } from '@/api/sms'

// ===== 列表与筛选(照旧 SmsRecord Index.cshtml datagrid) =====
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(30)
const filters = reactive({ mohu: '' })

async function load() {
  loading.value = true
  try {
    const data = await listSmsRecords({
      page: page.value, size: size.value, mohu: filters.mohu || undefined,
    })
    rows.value = data.rows
    total.value = data.total
  } finally { loading.value = false }
}
function search() { page.value = 1; load() }
function resetFilters() {
  filters.mohu = ''
  search()
}
function fmt(v, len = 19) { return v ? String(v).replace('T', ' ').slice(0, len) : '' }
// 照旧 formatter:网关返回含 "true"(旧报文)或 "code":"0"(新报文)视为发送成功
function isOk(zt) {
  const s = zt || ''
  return s.includes('"true"') || s.includes('"code":"0"') || s.includes("'code':'0'")
}
</script>

<template>
  <div class="sms-page">
    <!-- 查询条件(照旧 easyui-searchbox 模糊查询) -->
    <el-card shadow="never" class="filter-card">
      <div class="filter-title">短信发送记录</div>
      <el-form inline class="filter-form" @submit.prevent>
        <el-form-item label="模糊查询">
          <el-input v-model="filters.mohu" placeholder="类别 / 内容 / 手机 / 接收人 / 结果 / 发送人"
            clearable style="width: 300px" @keyup.enter="search" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <div class="toolbar">
      <span class="toolbar-hint">共 {{ total }} 条 · 按发送时间倒序 · 只读(发送由各业务模块自动/手动产生)</span>
    </div>

    <!-- 主表格(照旧 datagrid 8 列) -->
    <el-table v-loading="loading" :data="rows" border stripe size="small"
      height="calc(100vh - 250px)" row-key="id">
      <el-table-column prop="id" label="流水号" width="80" />
      <el-table-column prop="sender" label="发送人" width="110" show-overflow-tooltip />
      <el-table-column prop="lb" label="类别" width="140" show-overflow-tooltip />
      <el-table-column prop="riqi" label="日期" width="160">
        <template #default="{ row }">{{ fmt(row.riqi) }}</template>
      </el-table-column>
      <el-table-column prop="ren" label="接收人" width="100" show-overflow-tooltip />
      <el-table-column prop="tel" label="手机" width="130" />
      <el-table-column prop="nr" label="短信内容" min-width="320" show-overflow-tooltip />
      <el-table-column label="推送结果" width="100">
        <template #default="{ row }">
          <el-tooltip :content="row.zt" placement="top" :disabled="!row.zt">
            <span :class="isOk(row.zt) ? 'zt-ok' : 'zt-fail'">{{ isOk(row.zt) ? '成功' : '失败' }}</span>
          </el-tooltip>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[30, 60, 120]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>
  </div>
</template>

<style scoped>
.sms-page { display: flex; flex-direction: column; gap: 10px; }
.filter-card :deep(.el-card__body) { padding: 10px 14px; }
.filter-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 12px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }
.zt-ok { color: #67c23a; font-weight: 600; }
.zt-fail { color: #f56c6c; font-weight: 600; }
</style>
