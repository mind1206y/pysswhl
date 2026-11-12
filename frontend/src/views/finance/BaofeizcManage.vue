<script setup>
import { nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getBaofeizcDicts, listBaofeizc, getBaofeizc, createBaofeizc, updateBaofeizc,
  deleteBaofeizc, listBaofeizcMx, listBaofeizcCandidates, addBaofeizcMx,
  deleteBaofeizcMx, uploadBaofeizcImage, deleteBaofeizcImage, exportBaofeizc,
} from '@/api/baofeizc'

// ===== 字典(照旧 Index 预载:部门 / 起止日期 / 新增单据默认部门) =====
const dicts = reactive({
  departments: [], default_start: '', default_end: '', default_bmid: null,
})

// ===== 列表与筛选(照旧 GetList:关键字 / 单据日期起止 / 部门) =====
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(20)
const filters = reactive({ keyword: '', start: '', end: '', dept_id: null })

function buildParams() {
  const p = { page: page.value, size: size.value }
  if (filters.keyword) p.keyword = filters.keyword
  if (filters.start) p.start = filters.start
  if (filters.end) p.end = filters.end
  if (filters.dept_id) p.dept_id = filters.dept_id
  return p
}
async function load() {
  loading.value = true
  try {
    const data = await listBaofeizc(buildParams())
    rows.value = data.items || []
    total.value = data.total || 0
  } finally { loading.value = false }
}
function search() { page.value = 1; load() }
function resetFilters() {
  Object.assign(filters, {
    keyword: '', start: dicts.default_start, end: dicts.default_end, dept_id: null,
  })
  search()
}
function money(v) { return v === null || v === undefined || v === '' ? '' : Number(v).toFixed(2) }
function fmt(v, len = 10) { return v ? String(v).slice(0, len) : '' }

onMounted(async () => {
  const d = await getBaofeizcDicts()
  dicts.departments = d.departments || []
  dicts.default_start = d.default_start || ''
  dicts.default_end = d.default_end || ''
  dicts.default_bmid = d.default_bmid ?? null
  filters.start = dicts.default_start
  filters.end = dicts.default_end
  load()
})

// ===== 勾选(编辑 / 删除 / 导出均要求选中且仅选中一行) =====
const selection = ref([])
function onSelectionChange(v) { selection.value = v }
function requireOne() {
  if (selection.value.length !== 1) { ElMessage.warning('请选择一条数据'); return null }
  return selection.value[0]
}

// ===== 主表展开行子表(照旧 getmxb,懒加载) =====
const mxCache = reactive({})     // 报废单 id -> 资产明细
const mxLoading = reactive({})
async function loadMx(bfid) {
  mxLoading[bfid] = true
  try {
    const data = await listBaofeizcMx(bfid)
    mxCache[bfid] = data.items || []
  } finally { mxLoading[bfid] = false }
}
function onExpandChange(row, expanded) {
  // Element Plus 不同版本第二参可能是展开行数组或布尔,兼容两种
  const isOpen = Array.isArray(expanded) ? expanded.includes(row) : !!expanded
  if (isOpen) loadMx(row.id)
}
async function removeMx(bfid, subRow) {
  await deleteBaofeizcMx({ id: subRow.id })
  ElMessage.success('已删除明细')
  await Promise.all([loadMx(bfid), load()])
}
function expiredRowClass({ row }) {
  return row.expired_flag || (row.yishiyong > 0 && row.yishiyong === row.yujishiyong)
    ? 'bfz-expired-row' : ''
}

// ===== 添加 / 编辑报废单(照旧 #addDiv / #editDiv,共用弹窗 + tabs) =====
const dialog = ref(false)
const editingId = ref(null)
const formRef = ref()
const activeTab = ref('info')
const blankForm = () => ({ riqi: '', bmid: null, zaiyao: '' })
const form = reactive(blankForm())
const rules = {
  riqi: [{ required: true, message: '请选择报废日期', trigger: 'change' }],
}
const images = ref([])           // [{ dizhi, url }]
const uploading = ref(false)
const saving = ref(false)
const fileInput = ref()

function openCreate() {
  editingId.value = null
  Object.assign(form, blankForm(), { bmid: dicts.default_bmid ?? null })
  images.value = []
  activeTab.value = 'info'
  dialog.value = true
  nextTick(() => formRef.value?.clearValidate())
}
async function openEdit(row) {
  const data = await getBaofeizc(row.id)
  editingId.value = data.id
  Object.assign(form, blankForm(), {
    riqi: data.riqi || '', bmid: data.bmid ?? null, zaiyao: data.zaiyao || '',
  })
  images.value = (data.images || []).map((x) => ({ dizhi: x.dizhi, url: x.url }))
  activeTab.value = 'info'
  dialog.value = true
  nextTick(() => formRef.value?.clearValidate())
}
async function submitForm() {
  if (saving.value) return  // 防双击重复提交
  saving.value = true
  try {
    activeTab.value = 'info'
    await nextTick()
    try { await formRef.value.validate() } catch { return }
    const payload = {
      riqi: form.riqi || null, bmid: form.bmid,
      zaiyao: form.zaiyao || '', images: images.value.map((x) => x.dizhi),
    }
    if (editingId.value) await updateBaofeizc(editingId.value, payload)
    else await createBaofeizc(payload)
    ElMessage.success(editingId.value ? '修改成功' : '添加成功')
    dialog.value = false
    load()
  } finally { saving.value = false }
}

// ===== 图片上传 / 删除(照旧两段式上传:上传即落盘,保存时传 dizhi 数组) =====
function pickFile() { fileInput.value?.click() }
async function onFileChange(e) {
  const file = e.target.files?.[0]
  e.target.value = ''
  if (!file) return
  const ext = '.' + (file.name.split('.').pop() || '').toLowerCase()
  if (!['.jpg', '.jpeg', '.png'].includes(ext)) return ElMessage.warning('只支持 jpg / jpeg / png 图片')
  if (file.size > 10 * 1024 * 1024) return ElMessage.warning('图片不能超过 10MB')
  const fd = new FormData()
  fd.append('file', file)
  uploading.value = true
  try {
    const r = await uploadBaofeizcImage(fd)
    images.value.push({ dizhi: r.dizhi, url: r.url })
    ElMessage.success('图片已上传')
  } finally { uploading.value = false }
}
async function removeImage(i) {
  const im = images.value[i]
  await deleteBaofeizcImage(im.dizhi)
  images.value.splice(i, 1)
  ElMessage.success('已删除图片')
}

// ===== 删除 / 导出清理报告表 =====
async function doDelete() {
  const row = requireOne(); if (!row) return
  try {
    await ElMessageBox.confirm('如有明细记录将无法删除,确定要删除数据吗?', '提示', { type: 'warning' })
  } catch { return }
  await deleteBaofeizc(row.id)
  ElMessage.success('删除成功')
  load()
}
const exporting = ref(false)
async function doExport() {
  const row = requireOne(); if (!row) return
  exporting.value = true
  try {
    await exportBaofeizc(row.id)
    ElMessage.success('已导出清理报告表')
  } finally { exporting.value = false }
}

// ===== 添加资产设备候选弹窗(照旧 Getmx:本部门未报废资产 ∪ 已挂本单资产) =====
const candOpen = ref(false)
const candBfid = ref(null)
const candKeyword = ref('')
const candRows = ref([])
const candTotal = ref(0)
const candPage = ref(1)
const candSize = ref(10)
const candLoading = ref(false)
const candAddSaving = ref(false)
const candCancelSaving = ref(false)

function openCandidates(row) {
  candBfid.value = row.id
  candKeyword.value = ''
  candPage.value = 1
  candOpen.value = true
  loadCandidates()
}
async function loadCandidates() {
  candLoading.value = true
  try {
    const data = await listBaofeizcCandidates({
      bfid: candBfid.value, keyword: candKeyword.value,
      page: candPage.value, size: candSize.value,
    })
    candRows.value = data.items || []
    candTotal.value = data.total || 0
  } finally { candLoading.value = false }
}
function searchCandidates() { candPage.value = 1; loadCandidates() }
async function addCandidate(sub) {
  if (candAddSaving.value) return  // 防双击重复提交
  candAddSaving.value = true
  try {
    await addBaofeizcMx({ id: sub.id, bfid: candBfid.value })
    ElMessage.success('已加入报废')
    await Promise.all([loadCandidates(), load()])
  } finally { candAddSaving.value = false }
}
async function cancelCandidate(sub) {
  if (candCancelSaving.value) return  // 防双击重复提交
  candCancelSaving.value = true
  try {
    await deleteBaofeizcMx({ id: sub.id })
    ElMessage.success('已取消报废')
    await Promise.all([loadCandidates(), load()])
  } finally { candCancelSaving.value = false }
}
</script>

<template>
  <div class="bfz-page">
    <!-- 查询条件(照旧 toolbarRow) -->
    <el-card shadow="never" class="filter-card">
      <el-form inline class="filter-form">
        <el-form-item>
          <el-input v-model="filters.keyword" placeholder="请输入名称或资产编号查询"
            clearable style="width: 240px" @keyup.enter="search" />
        </el-form-item>
        <el-form-item label="报废单日期">
          <el-date-picker v-model="filters.start" type="date" value-format="YYYY-MM-DD"
            :editable="false" placeholder="开始日期" style="width: 146px" />
          <span class="date-sep">至</span>
          <el-date-picker v-model="filters.end" type="date" value-format="YYYY-MM-DD"
            :editable="false" placeholder="结束日期" style="width: 146px" />
        </el-form-item>
        <el-form-item label="部门">
          <el-select v-model="filters.dept_id" placeholder="全部部门" clearable filterable
            style="width: 150px">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 工具栏:查询/重置与单据操作合并为一行,按钮统一高度 -->
    <div class="toolbar">
      <el-button type="primary" @click="search">查询</el-button>
      <el-button @click="resetFilters">重置</el-button>
      <el-button type="primary" @click="openCreate">添加报废单</el-button>
      <el-button @click="() => { const r = requireOne(); if (r) openEdit(r) }">编辑</el-button>
      <el-button @click="doDelete">删除</el-button>
      <el-button :loading="exporting" @click="doExport">导出清理报告表</el-button>
      <span class="toolbar-hint">共 {{ total }} 条 · 双击行可编辑</span>
    </div>

    <!-- 主表(照旧 GetList;展开行显示资产明细子表) -->
    <el-table v-loading="loading" :data="rows" border stripe size="small"
      height="calc(100vh - 310px)" row-key="id"
      @selection-change="onSelectionChange" @row-dblclick="openEdit"
      @expand-change="onExpandChange">
      <el-table-column type="selection" width="42" />
      <el-table-column type="expand" width="36">
        <!-- Element Plus 展开列插槽名是 #default(不是 #expand),否则 row 为 undefined
             会在 renderExpand 里抛 TypeError,整张表都渲染不出来 -->
        <template #default="{ row: parent }">
          <div class="mx-wrap">
            <div class="mx-title">资产明细（{{ (mxCache[parent.id] || []).length }} 条）</div>
            <el-table :data="mxCache[parent.id] || []" v-loading="mxLoading[parent.id]"
              border stripe size="small" row-key="id" :row-class-name="expiredRowClass">
              <el-table-column label="删除" width="62" align="center">
                <template #default="{ row }">
                  <el-button link type="danger" size="small"
                    @click="removeMx(parent.id, row)">删除</el-button>
                </template>
              </el-table-column>
              <el-table-column prop="nd" label="盘点年度" width="76" align="center" />
              <el-table-column prop="zccode" label="资产号" width="96" show-overflow-tooltip />
              <el-table-column prop="sbname" label="设备名称" min-width="120" show-overflow-tooltip />
              <el-table-column prop="guige" label="规格型号" width="100" show-overflow-tooltip />
              <el-table-column prop="lb" label="资产类别" width="96" show-overflow-tooltip />
              <el-table-column prop="sbbh" label="设备编号" width="96" show-overflow-tooltip />
              <el-table-column prop="num" label="数量" width="56" align="right" />
              <el-table-column prop="yz" label="原值" width="90" align="right">
                <template #default="{ row }">{{ money(row.yz) }}</template>
              </el-table-column>
              <el-table-column prop="qyrq" label="启用日期" width="100">
                <template #default="{ row }">{{ fmt(row.qyrq) }}</template>
              </el-table-column>
              <el-table-column prop="didian" label="在用地点" min-width="100" show-overflow-tooltip />
              <el-table-column prop="bm" label="部门" width="110" show-overflow-tooltip />
            </el-table>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="ts" label="报废条数" width="76" align="center" />
      <el-table-column label="添加资产设备" width="104" align="center">
        <template #default="{ row }">
          <el-button link type="primary" size="small" @click="openCandidates(row)">添加资产设备</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="riqi" label="单据日期" width="104">
        <template #default="{ row }">{{ fmt(row.riqi) }}</template>
      </el-table-column>
      <el-table-column prop="zaiyao" label="摘要" min-width="150" show-overflow-tooltip />
      <el-table-column prop="bm" label="部门" width="120" show-overflow-tooltip />
      <el-table-column prop="caozuo" label="登记人" width="86" show-overflow-tooltip />
      <el-table-column prop="czriqi" label="登记日期" width="150">
        <template #default="{ row }">{{ fmt(row.czriqi, 16) }}</template>
      </el-table-column>
      <el-table-column label="图片" width="92">
        <template #default="{ row }">
          <div class="tps-cell">
            <a v-for="(u, i) in (row.tps || [])" :key="i" :href="u" target="_blank"
              rel="noopener" class="tp-link" :title="`图片 ${i + 1}`">
              <img :src="u" class="tp-thumb" />
            </a>
            <span v-if="!(row.tps || []).length" class="tp-empty">—</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="id" label="流水号" width="72" align="center" />
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[20, 60, 100]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>

    <!-- 添加 / 编辑报废单(照旧 #addDiv / #editDiv,共用弹窗 + tabs) -->
    <el-dialog v-model="dialog" :title="editingId ? '编辑报废单' : '添加报废单'"
      width="560px" top="7vh" class="std-dialog" :close-on-click-modal="false">
      <div class="bfd-card">
        <el-tabs v-model="activeTab">
          <el-tab-pane label="报废单信息" name="info">
            <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
              <el-form-item label="报废部门" prop="bmid">
                <el-select v-model="form.bmid" placeholder="请选择报废部门" filterable style="width: 100%">
                  <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
                </el-select>
              </el-form-item>
              <el-form-item label="报废日期" prop="riqi">
                <el-date-picker v-model="form.riqi" type="date" value-format="YYYY-MM-DD"
                  :editable="false" placeholder="选择报废日期" style="width: 100%" />
              </el-form-item>
              <el-form-item label="摘要" prop="zaiyao">
                <el-input v-model="form.zaiyao" type="textarea" :rows="4" placeholder="请输入摘要" />
              </el-form-item>
            </el-form>
          </el-tab-pane>
          <el-tab-pane label="图片" name="images">
            <div class="img-toolbar">
              <el-button size="small" type="primary" :loading="uploading" @click="pickFile">选择图片上传</el-button>
              <span class="img-tip">支持 jpg / jpeg / png，单张不超过 10MB</span>
              <input ref="fileInput" type="file" accept=".jpg,.jpeg,.png"
                class="hidden-file" @change="onFileChange" />
            </div>
            <div class="img-list">
              <div v-for="(im, i) in images" :key="im.dizhi" class="img-item">
                <a :href="im.url" target="_blank" rel="noopener" title="新窗口打开">
                  <img :src="im.url" class="img-thumb" />
                </a>
                <el-button link type="danger" size="small" @click="removeImage(i)">删除</el-button>
              </div>
              <div v-if="!images.length" class="img-empty">暂无图片</div>
            </div>
          </el-tab-pane>
        </el-tabs>
      </div>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitForm">
          {{ editingId ? '确定修改' : '确定增加' }}
        </el-button>
      </template>
    </el-dialog>

    <!-- 添加资产设备候选弹窗(照旧 Getmx;底部仅「关闭」,关闭刷新主表) -->
    <el-dialog v-model="candOpen" title="添加资产设备" width="min(1120px, 95vw)" top="6vh"
      class="std-dialog" :close-on-click-modal="false" @closed="load">
      <div class="cand-card">
        <div class="cand-search">
          <el-input v-model="candKeyword" placeholder="请输入名称或资产编号查询"
            clearable style="width: 260px" @keyup.enter="searchCandidates" />
          <el-button type="primary" size="small" @click="searchCandidates">查询</el-button>
          <span class="cand-hint">共 {{ candTotal }} 条候选资产</span>
        </div>
        <el-table :data="candRows" v-loading="candLoading" border stripe size="small"
          max-height="440" row-key="id" :row-class-name="expiredRowClass">
          <el-table-column label="报废/取消" width="82" align="center">
            <template #default="{ row }">
              <el-button v-if="row.can_add" link type="primary" size="small"
                @click="addCandidate(row)">报废</el-button>
              <el-button v-else link type="danger" size="small"
                @click="cancelCandidate(row)">取消</el-button>
            </template>
          </el-table-column>
          <el-table-column prop="baofeiqk" label="报废情况" width="82" show-overflow-tooltip />
          <el-table-column prop="bm" label="部门" width="100" show-overflow-tooltip />
          <el-table-column prop="nd" label="盘点年度" width="76" align="center" />
          <el-table-column prop="zccode" label="资产号" width="96" show-overflow-tooltip />
          <el-table-column prop="sbname" label="设备名称" min-width="120" show-overflow-tooltip />
          <el-table-column prop="guige" label="规格型号" width="100" show-overflow-tooltip />
          <el-table-column prop="lb" label="资产类别" width="96" show-overflow-tooltip />
          <el-table-column prop="sbbh" label="设备编号" width="96" show-overflow-tooltip />
          <el-table-column prop="num" label="数量" width="56" align="right" />
          <el-table-column prop="yz" label="原值" width="90" align="right">
            <template #default="{ row }">{{ money(row.yz) }}</template>
          </el-table-column>
          <el-table-column prop="qyrq" label="启用日期" width="100">
            <template #default="{ row }">{{ fmt(row.qyrq) }}</template>
          </el-table-column>
          <el-table-column prop="didian" label="在用地点" min-width="100" show-overflow-tooltip />
        </el-table>
        <div class="pager cand-pager">
          <el-pagination v-model:current-page="candPage" v-model:page-size="candSize"
            :total="candTotal" :page-sizes="[10, 60, 90]"
            layout="total, sizes, prev, pager, next, jumper"
            @current-change="loadCandidates" @size-change="searchCandidates" />
        </div>
      </div>
      <template #footer>
        <el-button @click="candOpen = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.bfz-page { display: flex; flex-direction: column; gap: 10px; }
.filter-card :deep(.el-card__body) { padding: 10px 14px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 12px; }
.filter-form :deep(.el-input__wrapper),
.filter-form :deep(.el-select__wrapper) {
  min-height: 32px !important; height: 32px; box-sizing: border-box;
}
.filter-form :deep(.el-input__inner) { height: 30px; line-height: 30px; }
.filter-form :deep(.el-form-item__label) { line-height: 32px; }
.filter-form :deep(.el-form-item__content) { line-height: 32px; }
.date-sep { margin: 0 6px; color: var(--el-text-color-regular, #606266); font-size: 13px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.toolbar :deep(.el-button) { height: 32px; }
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }

.tps-cell { display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.tp-link { display: inline-flex; }
.tp-thumb { width: 20px; height: 20px; object-fit: cover;
  border: 1px solid #dcdfe6; border-radius: 3px; display: block; }
.tp-empty { color: #c0c4cc; }

.mx-wrap { padding: 6px 10px 8px 36px; }
.mx-title { font-size: 12px; color: #909399; margin: 2px 0 6px; }

/* 灰底上的无边框白卡(与 .std-dialog 表单卡同口径) */
.bfd-card, .cand-card {
  background: #fff; border: none; border-radius: 12px;
  padding: 8px 16px 14px;
  box-shadow: 0 1px 2px rgba(16, 24, 40, .04), 0 4px 14px rgba(16, 24, 40, .05);
}
.cand-search { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.cand-search :deep(.el-input__wrapper) {
  min-height: 32px !important; height: 32px; box-sizing: border-box;
}
.cand-hint { margin-left: auto; color: #909399; font-size: 12px; }
.cand-pager { margin-top: 8px; }

.img-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.img-tip { color: #909399; font-size: 12px; }
.hidden-file { display: none; }
.img-list { display: flex; flex-wrap: wrap; gap: 12px; min-height: 60px; }
.img-item { display: flex; flex-direction: column; align-items: center; gap: 4px; }
.img-thumb { width: 88px; height: 88px; object-fit: cover;
  border: 1px solid #e4e7ed; border-radius: 8px; display: block; }
.img-empty { font-size: 12px; color: #909399; }
</style>

<!-- 到期资产行高亮:候选/明细表位于 teleport 到 body 的弹窗内,
     scoped 选择器够不到,故用全局唯一类名。rgba 浅底 + 主题文字变量,
     浅色/深色主题下文字都清晰。 -->
<style>
.bfz-expired-row td.el-table__cell { background: rgba(245, 158, 11, .16) !important; }
.bfz-expired-row td.el-table__cell .cell { color: var(--el-text-color-primary, #303133); }
</style>
