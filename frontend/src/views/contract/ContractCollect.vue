<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  collectContract,
  createAttachmentToken,
  exportCollect,
  listCollect,
  listCollectSubmitters,
  listCollectYears,
  uncollectContract,
  updateMemo,
} from '@/api/contract'

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(15)
const years = ref([])
const submitters = ref([])
const filters = reactive({ mohu: '', nd: [], tjr: '', jinedayu: null })
let suppressReload = false

const keyword = computed(() => filters.mohu.trim())
const yearNow = new Date().getFullYear()

function defaultNdValues() {
  return years.value.includes(yearNow) ? [yearNow] : []
}

function buildParams() {
  return {
    page: page.value,
    size: size.value,
    mohu: filters.mohu,
    nd: filters.nd.join(','),
    tjr: filters.tjr,
    jinedayu: filters.jinedayu ?? '',
  }
}

async function load() {
  loading.value = true
  try {
    const data = await listCollect(buildParams())
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

async function loadSubmitters() {
  submitters.value = await listCollectSubmitters(filters.nd.join(','))
  if (filters.tjr && !submitters.value.some((s) => s.value === filters.tjr)) {
    filters.tjr = ''
  }
}

async function onYearsChange() {
  if (suppressReload) return
  await loadSubmitters()
  search()
}

async function resetFilters() {
  suppressReload = true
  filters.mohu = ''
  filters.nd = defaultNdValues()
  filters.tjr = ''
  filters.jinedayu = null
  suppressReload = false
  await loadSubmitters()
  search()
}

async function toggleCollect(row, checked) {
  try {
    if (checked) await collectContract(row.id)
    else await uncollectContract(row.id)
    ElMessage.success(checked ? '归集成功' : '已取消归集')
  } finally {
    load()
  }
}

async function openAttachment(tp) {
  try {
    const data = await createAttachmentToken(tp.id)
    window.open(data.url, '_blank')
  } catch { /* 拦截器已提示 */ }
}

function fmtMoney(v) {
  if (v === null || v === undefined || v === '') return ''
  return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtSize(v) {
  const n = Number(v || 0)
  if (!n) return ''
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)}M`
  if (n >= 1024) return `${(n / 1024).toFixed(0)}K`
  return `${n}B`
}

function escHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;')
}

function highlight(value) {
  const text = escHtml(value)
  if (!keyword.value) return text
  const keys = [...new Set(keyword.value.split(/[\s,，]+/).map((k) => k.trim()).filter(Boolean))]
  let out = text
  for (const key of keys) {
    const escaped = key.replace(/([.*+?^=!:${}()|\[\]\/\\])/g, '\\$1')
    out = out.replace(new RegExp(escaped, 'gi'), (m) => `<span class="hl">${m}</span>`)
  }
  return out
}

function rowClass({ row }) {
  return row.zt === '已归集' ? 'row-collected' : ''
}

const memoVisible = ref(false)
const memoSaving = ref(false)
const memoForm = reactive({ id: null, bz: '', name: '' })

function openMemo(row) {
  memoForm.id = row.id
  memoForm.bz = row.bz || ''
  memoForm.name = row.name || ''
  memoVisible.value = true
}

async function saveMemo() {
  if (memoSaving.value) return  // 防双击重复提交
  memoSaving.value = true
  try {
    await updateMemo(memoForm.id, memoForm.bz)
    memoVisible.value = false
    ElMessage.success('已修改记录')
    load()
  } finally {
    memoSaving.value = false
  }
}

async function doExport() {
  await exportCollect({
    mohu: filters.mohu,
    nd: filters.nd.join(','),
    tjr: filters.tjr,
    jinedayu: filters.jinedayu ?? '',
  })
}

onMounted(async () => {
  years.value = await listCollectYears()
  filters.nd = defaultNdValues()
  await loadSubmitters()
  load()
})
</script>

<template>
  <div class="page">
    <el-card shadow="never" class="filter-card">
      <div class="banner">售水内控合同归集移交明细</div>
      <div class="filters">
        <el-input
          v-model="filters.mohu"
          placeholder="输入合同模糊查询"
          clearable
          style="width: 250px"
          @keyup.enter="search"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select
          v-model="filters.nd"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="选择年度(可多选)"
          style="width: 220px"
          @change="onYearsChange"
        >
          <el-option v-for="y in years" :key="y" :label="y" :value="y" />
        </el-select>
        <span class="label">提交人:</span>
        <el-select v-model="filters.tjr" clearable placeholder="全部提交人" style="width: 160px" @change="search">
          <el-option v-for="s in submitters" :key="s.value" :label="s.text" :value="s.value" />
        </el-select>
        <span class="label">金额大于:</span>
        <el-input-number
          v-model="filters.jinedayu"
          :min="0"
          :precision="2"
          :controls="false"
          placeholder="金额"
          style="width: 110px"
          @keyup.enter="search"
        />
        <span class="label">万元</span>
        <el-button @click="search"><el-icon><Filter /></el-icon>过滤</el-button>
        <el-button @click="resetFilters"><el-icon><Refresh /></el-icon>重置</el-button>
        <el-button @click="doExport"><el-icon><Download /></el-icon>导出记录</el-button>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table
        v-loading="loading"
        :data="rows"
        border
        stripe
        height="calc(100vh - 300px)"
        :row-class-name="rowClass"
      >
        <el-table-column label="归集" width="95" align="center" fixed="left">
          <template #default="{ row }">
            <el-switch
              :model-value="row.zt === '已归集'"
              :disabled="row.locked != null"
              active-text="已归集"
              inactive-text="待归集"
              inline-prompt
              @change="(v) => toggleCollect(row, v)"
            />
          </template>
        </el-table-column>
        <el-table-column label="锁定" width="65" align="center">
          <template #default="{ row }">
            <el-icon v-if="row.locked != null" class="locked"><Lock /></el-icon>
            <el-icon v-else class="unlocked"><Unlock /></el-icon>
          </template>
        </el-table-column>
        <el-table-column label="记录" width="60" align="center">
          <template #default="{ row }">
            <el-button link type="primary" title="记录备注" @click="openMemo(row)">
              <el-icon><EditPen /></el-icon>
            </el-button>
          </template>
        </el-table-column>
        <el-table-column prop="allbh" label="合同编号" width="130" show-overflow-tooltip />
        <el-table-column label="合同名称" min-width="230" show-overflow-tooltip>
          <template #default="{ row }"><span v-html="highlight(row.name)" /></template>
        </el-table-column>
        <el-table-column label="签订对象" min-width="240" show-overflow-tooltip>
          <template #default="{ row }"><span v-html="highlight(row.duixiang)" /></template>
        </el-table-column>
        <el-table-column label="合同标的" min-width="200" show-overflow-tooltip>
          <template #default="{ row }"><span v-html="highlight(row.biaodi)" /></template>
        </el-table-column>
        <el-table-column label="金额(元)" width="130" align="right">
          <template #default="{ row }"><span v-html="highlight(fmtMoney(row.jine))" /></template>
        </el-table-column>
        <el-table-column prop="niandu" label="年度" width="70" align="center" />
        <el-table-column prop="qddate" label="签订日期" width="105" align="center" />
        <el-table-column label="合同类别" width="110" show-overflow-tooltip>
          <template #default="{ row }"><span v-html="highlight(row.leibie)" /></template>
        </el-table-column>
        <el-table-column prop="zhaobiaofangshi" label="招标方式" width="150" show-overflow-tooltip />
        <el-table-column prop="editdate" label="最后编辑日期" width="155" />
        <el-table-column label="提交人" width="90">
          <template #default="{ row }"><span v-html="highlight(row.user)" /></template>
        </el-table-column>
        <el-table-column label="归集备注" min-width="150" show-overflow-tooltip>
          <template #default="{ row }"><span v-html="highlight(row.bz)" /></template>
        </el-table-column>
        <el-table-column prop="spdate" label="归集日期" width="155" />
        <el-table-column label="附件" width="110">
          <template #default="{ row }">
            <el-button
              v-for="tp in row.tps"
              :key="tp.id"
              link
              type="primary"
              :title="`${tp.oldname || '未命名'} ${fmtSize(tp.fsize)}`"
              @click="openAttachment(tp)"
            >
              <el-icon><Paperclip /></el-icon>
            </el-button>
            <span v-if="!row.tps?.length" class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="bm" label="部门" width="110" show-overflow-tooltip />
        <el-table-column prop="sp" label="归集人" width="90" />
      </el-table>
      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          :page-sizes="[15, 60, 120]"
          :total="total"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="load"
          @size-change="search"
        />
      </div>
    </el-card>

    <el-dialog v-model="memoVisible" title="记录备注" width="460px">
      <div class="memo-title">{{ memoForm.name }}</div>
      <el-input v-model="memoForm.bz" type="textarea" :rows="5" maxlength="2000" show-word-limit placeholder="填写归集备注" />
      <template #footer>
        <el-button @click="memoVisible = false">取消</el-button>
        <el-button type="primary" @click="saveMemo">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; }
.banner {
  background: #1c1e54;
  color: #fff;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: 2px;
  text-align: center;
  padding: 12px 0;
  border-radius: 4px;
  margin-bottom: 12px;
}
.filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.label { color: #475569; font-size: 14px; }
.table-card :deep(.el-card__body) { padding: 12px; }
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }
.muted { color: #94a3b8; }
.locked { color: #dc2626; }
.unlocked { color: #94a3b8; }
.memo-title { color: #475569; margin-bottom: 10px; }
:deep(.row-collected) { background: #fdf6d8 !important; }
:deep(.hl) { background: #fff3b0; color: #613400; font-weight: 600; }
</style>
