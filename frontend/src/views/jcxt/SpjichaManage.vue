<script setup>
/** 审批稽查(照旧 Spjicha/Index.cshtml 1:1 复刻):纯审批页,无编辑弹窗 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  approveSpOne, approveSpRows, cancelSpOne, cancelSpRows, computReward,
  comptaTongan, exportSpReward, getSpjichaDicts, getJcImageToken, heduiWorkOrder,
  listSpjicha,
} from '@/api/jcxt'

const filters = reactive({
  sousou: '', filterType: 'custom', selectedMonth: '', rq: firstOfMonth(),
  rqend: today(), rqsx: '', lbid: '', guanjing: '', bmid: null,
  px: false, dg: false,
})
const dicts = reactive({
  departments: [], wzleibie: [], rqsx: [], guanjing: [],
})
const resetting = ref(false)

function firstOfMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
}
function today() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const tableRef = ref()
const rows = ref([])
const total = ref(0)
const footer = ref(null)
const page = reactive({ current: 1, size: 30 })
const loading = ref(false)

const allColumns = [
  { field: 'url', title: '审批', width: 50 },
  { field: 'spdate', title: '审批时间', width: 130 },
  { field: 'ssspren', title: '售水审批人', width: 90 },
  { field: 'spren', title: '提交人', width: 80 },
  { field: 'gongdanhao', title: '工单号', width: 80 },
  { field: 'weizhangriqi', title: '违章日期', width: 90 },
  { field: 'weizhangren', title: '违章单位', width: 170 },
  { field: 'wzleibie', title: '违章类别', width: 120 },
  { field: 'weizhangdianhua', title: '违章电话', width: 100 },
  { field: 'weizhangdizhi', title: '违章地址', width: 180 },
  { field: 'weizhangneirong', title: '违章内容', width: 240 },
  { field: 'guanjing', title: '管径', width: 70 },
  { field: 'chuliriqi', title: '处理日期', width: 90 },
  { field: 'banjietianshu', title: '办结天数', width: 75 },
  { field: 'zuihougengxin', title: '最后更新', width: 150 },
  { field: 'caozuoname', title: '操作员', width: 70 },
  { field: 'bumen', title: '部门', width: 85 },
  { field: 'caozuoriqi', title: '建单日期', width: 150 },
  { field: 'zhuijiaoshuiliang', title: '追缴水量', width: 85 },
  { field: 'zhuijiaoshuifei', title: '追缴水费', width: 85 },
  { field: 'zhuijiaogongliaofei', title: '追缴工料费', width: 90 },
  { field: 'ze', title: '追缴总额', width: 85 },
  { field: 'zhuijiaobm', title: '追缴人', width: 70 },
  { field: 'peibiaofei', title: '赔表费', width: 70 },
  { field: 'nongcunjicha', title: '农村稽查', width: 80 },
  { field: 'zhixingqingkuang', title: '是否逃逸', width: 75 },
  { field: 'zhuangtai', title: '处理状态', width: 80 },
  { field: 'jubaoleibie', title: '举报类别', width: 85 },
  { field: 'jubaoren', title: '举报人', width: 80 },
  { field: 'jbjiangli', title: '举报奖励', width: 80 },
  { field: 'zhuijiaojiangli', title: '追缴奖励', width: 80 },
  { field: 'tps', title: '图片', width: 70 },
  { field: 'spzt', title: '审批状态', width: 80 },
]
const COLUMN_KEY = 'spjicha_selected_columns'
const colDialog = ref(false)
const selectedCols = ref(allColumns.map(c => c.field))
try {
  const saved = JSON.parse(localStorage.getItem(COLUMN_KEY) || 'null')
  if (Array.isArray(saved) && saved.length) {
    // 旧系统迁移:补上 ssspren/spren 两列(默认可见)
    const merged = [...new Set([...saved, 'ssspren', 'spren'])]
    selectedCols.value = allColumns.map(c => c.field).filter(f => merged.includes(f))
  }
} catch { /* */ }
const visibleColumns = computed(() =>
  allColumns.filter(c => selectedCols.value.includes(c.field)))
function saveCols() {
  localStorage.setItem(COLUMN_KEY, JSON.stringify(selectedCols.value))
}

async function load() {
  loading.value = true
  try {
    const params = { ...filters, page: page.current, size: page.size,
      bmid: filters.bmid || undefined }
    const res = await listSpjicha(params)
    rows.value = res.items
    total.value = res.total
    footer.value = res.footer && res.footer[0] ? res.footer[0] : null
    await new Promise(r => setTimeout(r))
    tableRef.value?.clearSelection()
  } finally {
    loading.value = false
  }
}
function doSearch() { page.current = 1; load() }
function resetFilters() {
  resetting.value = true
  Object.assign(filters, {
    sousou: '', filterType: 'custom', selectedMonth: '', rq: firstOfMonth(),
    rqend: today(), rqsx: '', lbid: '', guanjing: '', bmid: null,
    px: false, dg: false,
  })
  setTimeout(() => { resetting.value = false; doSearch() }, 0)
}

function summaryMethod({ columns }) {
  if (!footer.value) return []
  const map = {
    ze: footer.value.ze, zhuijiaoshuifei: footer.value.zhuijiaoshuifei,
    zhuijiaogongliaofei: footer.value.zhuijiaogongliaofei,
    zhuijiaoshuiliang: footer.value.zhuijiaoshuiliang,
    jbjiangli: footer.value.jbjiangli,
  }
  return columns.map((c) => {
    if (c.property && c.property in map) {
      const v = map[c.property]
      return v != null && v !== 0 ? String(v) : ''
    }
    if (c.type === 'selection') return '合计'
    return ''
  })
}
function rowClass({ row }) {
  if (row.zhuangtai === '已完结' || row.zhixingqingkuang === '逃逸') return 'row-done'
  return ''
}

const tokenCache = new Map()
async function openImage(pic) {
  let url = tokenCache.get(pic.id)
  if (!url) {
    const res = await getJcImageToken(pic.id)
    url = res.url
    tokenCache.set(pic.id, url)
  }
  window.open(url, '_blank')
}

async function oneApprove(row) {
  try { await approveSpOne(row.ID); ElMessage.success('已审批'); load() } catch { /* */ }
}
async function oneCancel(row) {
  try { await cancelSpOne(row.ID); ElMessage.success('已取消审批'); load() } catch { /* */ }
}
async function batchApprove() {
  const ids = tableRef.value?.getSelectionRows()?.map(r => r.ID).join(',') || ''
  if (!ids) return ElMessage.warning('请先勾选记录')
  try {
    await ElMessageBox.confirm('确定要审批?', '提示', { type: 'warning' })
  } catch { return }
  try { await approveSpRows(ids); ElMessage.success('审批完成'); load() } catch { /* */ }
}
async function batchCancel() {
  const ids = tableRef.value?.getSelectionRows()?.map(r => r.ID).join(',') || ''
  if (!ids) return ElMessage.warning('请先勾选记录')
  try {
    await ElMessageBox.confirm('确定取消审批?', '提示', { type: 'warning' })
  } catch { return }
  try { await cancelSpRows(ids); ElMessage.success('取消完成'); load() } catch { /* */ }
}

const computing = ref(false)
async function onComput() {
  computing.value = true
  try {
    await computReward(filters.rqend)
    ElMessage.success('奖励计算完成')
    load()
  } catch { /* */ } finally { computing.value = false }
}
async function onCompta() {
  computing.value = true
  try {
    const res = await comptaTongan(filters.rqend)
    ElMessage.success(`同安奖励分配完成,共 ${res.updated} 条`)
    load()
  } catch { /* */ } finally { computing.value = false }
}
async function onExportReward() {
  try { await exportSpReward(filters.rqend) } catch { /* */ }
}
const heduiInput = ref()
async function onHeduiFile(e) {
  const f = e.target.files[0]
  e.target.value = ''
  if (!f) return
  if (!(f.name.includes('工单信息') && /\.(xls|xlsx)$/i.test(f.name))) {
    return ElMessage.error('需要名为「工单信息.xls」的文件')
  }
  try {
    await heduiWorkOrder(f)
    ElMessage.success('核对完成,已下载核对文件')
  } catch { /* */ }
}

onMounted(async () => {
  try {
    const res = await getSpjichaDicts()
    Object.assign(dicts, res)
  } catch { /* */ }
  load()
})
</script>

<template>
  <div class="spjc-page">
    <el-card shadow="never" class="filter-card">
      <div class="filter-title">稽查审批表</div>
      <div class="filter-grid">
        <el-input v-model="filters.sousou" placeholder="模糊查询" clearable
          style="width: 220px" @keyup.enter="doSearch" @clear="doSearch" />
        <el-select v-model="filters.filterType" style="width: 130px" @change="doSearch">
          <el-option label="自选起止日期" value="custom" />
          <el-option label="本月" value="currentMonth" />
          <el-option label="上月" value="lastMonth" />
          <el-option label="按月份选择" value="selectMonth" />
        </el-select>
        <template v-if="filters.filterType === 'custom'">
          <el-date-picker v-model="filters.rq" type="date" value-format="YYYY-MM-DD"
            placeholder="开始日期" style="width: 130px" @change="doSearch" />
          <el-date-picker v-model="filters.rqend" type="date" value-format="YYYY-MM-DD"
            placeholder="结束日期" style="width: 130px" @change="doSearch" />
        </template>
        <el-date-picker v-if="filters.filterType === 'selectMonth'"
          v-model="filters.selectedMonth" type="month" value-format="YYYY-MM"
          placeholder="选择月份" style="width: 130px" @change="doSearch" />
        <el-select v-model="filters.rqsx" placeholder="日期筛选" clearable
          style="width: 150px" @change="doSearch">
          <el-option v-for="r in dicts.rqsx" :key="r" :label="r" :value="r" />
        </el-select>
        <el-select v-model="filters.lbid" placeholder="违章类别" clearable
          style="width: 140px" @change="doSearch">
          <el-option v-for="w in dicts.wzleibie" :key="w" :label="w" :value="w" />
        </el-select>
        <el-select v-model="filters.bmid" placeholder="选择部门" clearable
          style="width: 140px" @change="doSearch">
          <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
        </el-select>
        <el-select v-model="filters.guanjing" placeholder="管径" clearable
          style="width: 120px" @change="doSearch">
          <el-option v-for="g in dicts.guanjing" :key="g" :label="g" :value="g" />
        </el-select>
        <div class="switches">
          <span class="sw"><el-switch v-model="filters.px"
            :disabled="resetting" @change="doSearch" />降序</span>
          <span class="sw"><el-switch v-model="filters.dg"
            :disabled="resetting" @change="doSearch" />300以上</span>
        </div>
        <div class="btns">
          <el-button type="primary" size="small" @click="doSearch">查询</el-button>
          <el-button size="small" @click="resetFilters">重置</el-button>
        </div>
      </div>
      <div class="toolbar">
        <el-button size="small" type="danger" @click="batchApprove">审批通过</el-button>
        <el-button size="small" @click="batchCancel">取消审批</el-button>
        <el-button size="small" type="success" @click="onExportReward">导出稽查奖励报表</el-button>
        <el-button size="small" :loading="computing" @click="onComput">计算奖励</el-button>
        <el-button size="small" :loading="computing" @click="onCompta">同安奖励</el-button>
        <el-button size="small" @click="heduiInput?.click()">上传.xls工单信息文件</el-button>
        <el-button size="small" @click="colDialog = true">显示/隐藏列</el-button>
        <input ref="heduiInput" type="file" accept=".xls,.xlsx" hidden @change="onHeduiFile">
      </div>
    </el-card>

    <el-table ref="tableRef" :data="rows" v-loading="loading" class="sp-table"
      row-key="ID" show-summary :summary-method="summaryMethod"
      :row-class-name="rowClass" height="calc(100vh - 320px)" border>
      <el-table-column type="selection" width="38" fixed="left" />
      <el-table-column v-for="c in visibleColumns" :key="c.field" :prop="c.field"
        :label="c.title" :width="c.width" show-overflow-tooltip>
        <template v-if="c.field === 'url'" #default="{ row }">
          <el-link v-if="row.spzt === '待审核'" type="primary" :underline="false"
            title="点击可审核数据" @click="oneApprove(row)">○</el-link>
          <el-link v-else type="success" :underline="false" title="点击可取消审核"
            @click="oneCancel(row)">✔</el-link>
        </template>
        <template v-else-if="c.field === 'tps'" #default="{ row }">
          <span v-if="row.tps && row.tps.length" class="pic-icons">
            <el-link v-for="p in row.tps" :key="p.id" :underline="false" title="查看图片"
              @click="openImage(p)">🖼</el-link>
          </span>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination v-model:current-page="page.current" v-model:page-size="page.size"
      :total="total" :page-sizes="[30, 120, 300]" layout="total, sizes, prev, pager, next"
      @change="load" />

    <el-dialog v-model="colDialog" title="显示/隐藏列" width="760px">
      <div class="col-actions">
        <el-button size="small" @click="selectedCols = allColumns.map(c => c.field); saveCols()">全选</el-button>
        <el-button size="small" @click="selectedCols = []; saveCols()">全不选</el-button>
      </div>
      <el-checkbox-group v-model="selectedCols" class="col-grid" @change="saveCols">
        <el-checkbox v-for="c in allColumns" :key="c.field" :value="c.field">
          {{ c.title }}
        </el-checkbox>
      </el-checkbox-group>
    </el-dialog>
  </div>
</template>

<style>
.spjc-page { padding: 12px; }
.spjc-page .filter-card { margin-bottom: 10px; }
.spjc-page .filter-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.spjc-page .filter-grid { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.spjc-page .switches { display: flex; gap: 10px; align-items: center; }
.spjc-page .sw { display: inline-flex; align-items: center; gap: 4px; font-size: 12px; }
.spjc-page .btns { display: flex; gap: 4px; }
.spjc-page .toolbar { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
.spjc-page .sp-table { width: 100%; }
.spjc-page .row-done { background: var(--el-fill-color-light); }
.spjc-page .pic-icons { white-space: nowrap; }
.spjc-page .col-actions { margin-bottom: 10px; }
.spjc-page .col-grid { display: grid; grid-template-columns: repeat(4, 1fr); row-gap: 8px; }
</style>
