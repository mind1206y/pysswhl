<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getGdzcDicts, getGdzcQyYears, listGdzc,
  saveGdzcRemark, checkGdzc, getBaofeiDetail,
  exportGdzcDetail, exportGdzcPandian, importGdzc,
} from '@/api/gdzc'

// ===== 字典(照旧 Index 预载:盘点年度 / 类别 / 部门,启用年度按盘点年度联动) =====
const dicts = reactive({
  years: [], categories: [], departments: [], qyYears: [], defaultYear: null,
})

// ===== 列表与筛选(照旧 GetList) =====
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const sumYz = ref(0)
const sumJz = ref(0)
const page = ref(1)
const size = ref(30)
const filters = reactive({
  keyword: '', nd: '', dept_id: null,
  categories: [], qy_years: [], expired: false, asc: false,
})

function buildParams(withPage = true) {
  const p = {}
  if (withPage) { p.page = page.value; p.size = size.value }
  if (filters.keyword) p.keyword = filters.keyword
  if (filters.nd !== '' && filters.nd !== null && filters.nd !== undefined) p.nd = filters.nd
  if (filters.dept_id) p.dept_id = filters.dept_id
  if (filters.categories.length) p.categories = filters.categories.join(',')
  if (filters.qy_years.length) p.qy_years = filters.qy_years.join(',')
  p.expired = !!filters.expired
  p.asc = !!filters.asc
  return p
}

async function load() {
  loading.value = true
  try {
    const data = await listGdzc(buildParams())
    rows.value = data.items || []
    total.value = data.total || 0
    sumYz.value = data.sum_yz || 0
    sumJz.value = data.sum_jz || 0
  } finally { loading.value = false }
}
function search() { page.value = 1; load() }

async function refreshQyYears() {
  const r = await getGdzcQyYears(filters.nd)
  dicts.qyYears = r.years || []
}
async function onNdChange() {
  filters.qy_years = []
  await refreshQyYears()
  search()
}
async function resetFilters() {
  Object.assign(filters, {
    keyword: '', nd: dicts.defaultYear, dept_id: null,
    categories: [], qy_years: [], expired: false, asc: false,
  })
  await refreshQyYears()
  search()
}

function money(v) {
  return v === null || v === undefined || v === '' ? '' : Number(v).toFixed(2)
}
function fmt(v, len = 10) { return v ? String(v).slice(0, len) : '' }

// 合计行(照旧 footer:筛选后全量,不是当页)
function summaryMethod({ columns }) {
  return columns.map((c) => {
    if (c.property === 'didian') return '合计'
    if (c.property === 'yz') return Number(sumYz.value || 0).toFixed(2)
    if (c.property === 'jz') return Number(sumJz.value || 0).toFixed(2)
    return ''
  })
}

// 到期资产行高亮
function rowClass({ row }) { return row.expired_flag ? 'expired-row' : '' }

onMounted(async () => {
  const d = await getGdzcDicts()
  dicts.years = d.years || []
  dicts.categories = d.categories || []
  dicts.departments = d.departments || []
  dicts.defaultYear = d.default_year ?? null
  filters.nd = dicts.defaultYear ?? dicts.years[dicts.years.length - 1] ?? ''
  await refreshQyYears()
  load()
})

// ===== 行内操作:确认/取消盘点、备注 =====
async function toggleCheck(row) {
  const checked = !row.pandian
  await checkGdzc({ id: row.id, checked })
  ElMessage.success(checked ? '已确认盘点' : '已取消盘点')
  load()
}

const remarkOpen = ref(false)
const remarkId = ref(null)
const remarkText = ref('')
function openRemark(row) {
  remarkId.value = row.id
  remarkText.value = row.beizhu || ''
  remarkOpen.value = true
}
async function saveRemark() {
  await saveGdzcRemark({ id: remarkId.value, beizhu: remarkText.value })
  ElMessage.success('备注已保存')
  remarkOpen.value = false
  load()
}

// ===== 报废单详情 =====
const bfOpen = ref(false)
const bfLoading = ref(false)
const bf = reactive({ danju: {}, mingxi: [] })
async function openBaofei(row) {
  bfOpen.value = true
  bfLoading.value = true
  try {
    const d = await getBaofeiDetail(row.baofeidanid)
    bf.danju = d.danju || {}
    bf.mingxi = d.mingxi || []
  } finally { bfLoading.value = false }
}

// ===== 导出(传当前完整筛选,不含分页) =====
const exportingDetail = ref(false)
const exportingPandian = ref(false)
async function doExportDetail() {
  exportingDetail.value = true
  try {
    await exportGdzcDetail(buildParams(false))
    ElMessage.success('已导出固定资产明细表')
  } finally { exportingDetail.value = false }
}
async function doExportPandian() {
  exportingPandian.value = true
  try {
    await exportGdzcPandian(buildParams(false), filters.nd)
    ElMessage.success('已导出盘点表')
  } finally { exportingPandian.value = false }
}

// ===== 导入盘点文件 =====
const importOpen = ref(false)
const importSeq = ref(0)
const uploadFiles = ref([])
const importFile = ref(null)
const importBmid = ref(null)
const importing = ref(false)
function openImport() {
  importSeq.value += 1
  uploadFiles.value = []
  importFile.value = null
  importBmid.value = null
  importOpen.value = true
}
function onImportChange(file) { importFile.value = file }
function onImportRemove() { importFile.value = null }
async function doImport() {
  if (!importFile.value?.raw) return ElMessage.warning('请选择要导入的盘点文件')
  if (!importBmid.value) return ElMessage.warning('请选择部门')
  const fd = new FormData()
  fd.append('file', importFile.value.raw)
  fd.append('bmid', importBmid.value)
  importing.value = true
  try {
    const r = await importGdzc(fd)
    if (!r.ok) { ElMessage.warning('导入失败'); return }
    ElMessage.success(`导入成功：新增 ${r.added} 条，跳过 ${r.skipped} 条，共 ${r.total} 条`)
    importOpen.value = false
    load()
  } finally { importing.value = false }
}
</script>

<template>
  <div class="gdzc-page">
    <!-- 查询条件(照旧 toolbarRow) -->
    <el-card shadow="never" class="filter-card">
      <el-form inline class="filter-form">
        <el-form-item>
          <el-input v-model="filters.keyword" placeholder="输入设备名称/资产号等模糊查询"
            clearable style="width: 220px" @keyup.enter="search" @change="search" />
        </el-form-item>
        <el-form-item label="盘点年度">
          <el-select v-model="filters.nd" placeholder="盘点年度" style="width: 118px" @change="onNdChange">
            <el-option v-for="y in dicts.years" :key="y" :label="`${y}年`" :value="y" />
          </el-select>
        </el-form-item>
        <el-form-item label="部门">
          <el-select v-model="filters.dept_id" placeholder="全部部门" clearable filterable
            style="width: 148px" @change="search">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="资产类别">
          <el-select v-model="filters.categories" multiple collapse-tags collapse-tags-tooltip
            placeholder="全部类别" style="width: 180px" @change="search">
            <el-option v-for="c in dicts.categories" :key="c.id" :label="c.name" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用年度">
          <el-select v-model="filters.qy_years" multiple collapse-tags collapse-tags-tooltip
            placeholder="全部启用年度" style="width: 168px" @change="search">
            <el-option v-for="y in dicts.qyYears" :key="y" :label="`${y}年`" :value="y" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="filters.expired" @change="search">到期资产</el-checkbox>
        </el-form-item>
        <el-form-item>
          <el-checkbox v-model="filters.asc" @change="search">升序</el-checkbox>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 工具栏:查询/重置与导出/导入合并为一行,按钮统一高度 -->
    <div class="toolbar">
      <el-button type="primary" @click="search">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
      <el-button type="primary" :loading="exportingDetail" @click="doExportDetail">导出EXCEL</el-button>
      <el-button :loading="exportingPandian" @click="doExportPandian">导出盘点表EXCEL</el-button>
      <el-button @click="openImport">导入盘点文件</el-button>
      <span class="toolbar-hint">共 {{ total }} 条 · 原值合计 {{ money(sumYz) }} · 净值合计 {{ money(sumJz) }}</span>
    </div>

    <!-- 主表格:照旧 gdzc/Index.cshtml 22 列顺序与列宽(资产号/设备名称按需求加宽) -->
    <el-table v-loading="loading" :data="rows" border stripe size="small" row-key="id"
      height="calc(100vh - 340px)" show-summary :summary-method="summaryMethod"
      :row-class-name="rowClass">
      <el-table-column label="确认/取消" width="60">
        <template #default="{ row }">
          <el-button link type="primary" size="small" style="white-space:nowrap"
            @click="toggleCheck(row)">
            {{ row.pandian ? '取消' : '确认' }}
          </el-button>
        </template>
      </el-table-column>
      <el-table-column label="备注记录" width="60">
        <template #default="{ row }">
          <el-button link type="primary" size="small" style="white-space:nowrap"
            @click="openRemark(row)">备注</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="id" label="编号" width="60" />
      <el-table-column prop="baofeiqk" label="报废情况" width="90" show-overflow-tooltip />
      <el-table-column prop="lb" label="固定资产类别" width="120" show-overflow-tooltip />
      <el-table-column prop="zccode" label="资产号" width="168" show-overflow-tooltip />
      <el-table-column prop="sbname" label="设备名称" width="312" show-overflow-tooltip />
      <el-table-column prop="num" label="数量" width="60" align="right" />
      <el-table-column prop="didian" label="在用地点" width="90" show-overflow-tooltip />
      <el-table-column prop="xsriqi" label="设备启用日期" width="100">
        <template #default="{ row }">{{ fmt(row.xsriqi) }}</template>
      </el-table-column>
      <el-table-column prop="yz" label="原值" width="140" align="right">
        <template #default="{ row }">{{ money(row.yz) }}</template>
      </el-table-column>
      <el-table-column prop="jz" label="净值" width="140" align="right">
        <template #default="{ row }">{{ money(row.jz) }}</template>
      </el-table-column>
      <el-table-column prop="guige" label="规格型号" width="165" show-overflow-tooltip />
      <el-table-column prop="sbbh" label="设备编号" width="190" show-overflow-tooltip />
      <el-table-column prop="yujishiyong" label="期限" width="60" align="right" />
      <el-table-column prop="yishiyong" label="已用" width="60" align="right" />
      <el-table-column prop="nd" label="盘点年度" width="60" align="center" />
      <el-table-column prop="bm" label="所属的部门" width="90" show-overflow-tooltip />
      <el-table-column label="报废单" width="80">
        <template #default="{ row }">
          <el-button v-if="row.baofeidanid" link type="primary" size="small"
            @click="openBaofei(row)">{{ row.baofeidanid }}</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="beizhuren" label="备注人" width="90" show-overflow-tooltip />
      <el-table-column prop="beizhu" label="备注" width="200" show-overflow-tooltip />
      <el-table-column label="备注日期" width="110">
        <template #default="{ row }">{{ fmt(row.bzdate) }}</template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[30, 60, 90]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>

    <!-- 备注记录 -->
    <el-dialog v-model="remarkOpen" title="备注记录" width="480px" top="12vh"
      class="std-dialog" :close-on-click-modal="false">
      <el-form label-width="70px">
        <el-form-item label="备注">
          <el-input v-model="remarkText" type="textarea" :rows="5"
            placeholder="可留空以清除备注" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="remarkOpen = false">取消</el-button>
        <el-button type="primary" @click="saveRemark">保存</el-button>
      </template>
    </el-dialog>

    <!-- 报废单详情 -->
    <el-dialog v-model="bfOpen" title="报废单详情" width="960px" top="7vh" class="std-dialog">
      <div v-loading="bfLoading" class="bf-body">
        <el-descriptions :column="2" border size="small">
          <el-descriptions-item label="日期">{{ fmt(bf.danju.riqi) || '—' }}</el-descriptions-item>
          <el-descriptions-item label="摘要">{{ bf.danju.zhaiyao || '—' }}</el-descriptions-item>
          <el-descriptions-item label="部门">{{ bf.danju.bumen || '—' }}</el-descriptions-item>
          <el-descriptions-item label="登记人">{{ bf.danju.dengjiren || '—' }}</el-descriptions-item>
          <el-descriptions-item label="登记日期">{{ fmt(bf.danju.dengjiriqi) || '—' }}</el-descriptions-item>
        </el-descriptions>
        <div class="bf-section">单据图片</div>
        <div v-if="bf.danju.pics?.length" class="bf-pics">
          <div v-for="(p, i) in bf.danju.pics" :key="i" class="bf-pic">
            <el-image :src="p" :preview-src-list="bf.danju.pics" :initial-index="i"
              fit="cover" class="bf-img" />
            <a :href="p" target="_blank" rel="noopener">新窗口打开</a>
          </div>
        </div>
        <div v-else class="bf-empty">暂无图片</div>
        <div class="bf-section">资产明细（{{ bf.mingxi.length }}）</div>
        <el-table :data="bf.mingxi" border stripe size="small" max-height="300">
          <el-table-column prop="nd" label="盘点年度" width="80" align="center" />
          <el-table-column prop="zccode" label="资产号" width="100" show-overflow-tooltip />
          <el-table-column prop="sbname" label="设备名称" min-width="120" show-overflow-tooltip />
          <el-table-column prop="guige" label="规格型号" width="100" show-overflow-tooltip />
          <el-table-column prop="lb" label="资产类别" width="100" show-overflow-tooltip />
          <el-table-column prop="sbbh" label="设备编号" width="100" show-overflow-tooltip />
          <el-table-column prop="num" label="数量" width="60" align="right" />
          <el-table-column label="原值" width="90" align="right">
            <template #default="{ row }">{{ money(row.yz) }}</template>
          </el-table-column>
          <el-table-column label="启用日期" width="100">
            <template #default="{ row }">{{ fmt(row.qyrq || row.xsriqi) }}</template>
          </el-table-column>
          <el-table-column prop="didian" label="在用地点" min-width="100" show-overflow-tooltip />
        </el-table>
      </div>
      <template #footer>
        <el-button @click="bfOpen = false">关闭</el-button>
      </template>
    </el-dialog>

    <!-- 导入盘点文件 -->
    <el-dialog v-model="importOpen" title="导入盘点文件" width="520px" top="10vh"
      class="std-dialog" :close-on-click-modal="false">
      <el-form label-width="80px">
        <el-form-item label="部门" required>
          <el-select v-model="importBmid" placeholder="请选择部门" filterable style="width: 100%">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="盘点文件" required>
          <el-upload :key="importSeq" v-model:file-list="uploadFiles" :auto-upload="false"
            :limit="1" accept=".xls,.xlsx" :on-change="onImportChange" :on-remove="onImportRemove">
            <el-button size="small">选择文件</el-button>
            <template #tip>
              <div class="el-upload__tip">仅支持 .xls / .xlsx 盘点文件</div>
            </template>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="importOpen = false">取消</el-button>
        <el-button type="primary" :loading="importing" @click="doImport">开始导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.gdzc-page { display: flex; flex-direction: column; gap: 10px; }
.filter-card :deep(.el-card__body) { padding: 10px 14px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 12px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.toolbar :deep(.el-button) { height: 32px; }
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }

/* 到期资产行:浅色 rgba 高亮(深浅主题都不写死深色底),
   文字用主题变量,浅色主题下为深色字,暗色主题下自动转浅色,均清晰可读 */
.gdzc-page :deep(.expired-row) td.el-table__cell {
  background: rgba(245, 158, 11, 0.16) !important;
}
.gdzc-page :deep(.expired-row) td.el-table__cell .cell {
  color: var(--el-text-color-primary, #303133);
}

/* 弹窗内白卡(与 .std-dialog 表单卡同口径) */
.bf-body {
  background: #fff; border: none; border-radius: 12px; padding: 14px 16px;
  box-shadow: 0 1px 2px rgba(16, 24, 40, .04), 0 4px 14px rgba(16, 24, 40, .05);
}
.bf-section { font-size: 13px; font-weight: 600; color: #5a5752; margin: 14px 0 8px; }
.bf-pics { display: flex; flex-wrap: wrap; gap: 10px; }
.bf-pic { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.bf-img { width: 96px; height: 96px; border-radius: 8px; border: 1px solid #ebebeb; }
.bf-pic a { font-size: 12px; color: var(--el-color-primary, #533afd); }
.bf-empty { font-size: 12px; color: #909399; }
.gdzc-page :deep(.el-upload__tip) { font-size: 12px; color: #909399; }
</style>
