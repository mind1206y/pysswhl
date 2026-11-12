<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createChuxian, createChuxianImageToken, deleteChuxian, exportChuxian,
  getChuxian, getChuxianCarExtra, getChuxianDicts, listChuxian,
  searchChuxianVehicles, updateChuxian,
} from '@/api/chuxian'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const username = computed(() => auth.user?.username || '')
const isSuper = computed(() => !!auth.user?.is_superuser)

// ===== 字典 =====
const dicts = reactive({ departments: [], zeren: [], years: [] })

// ===== 列表与筛选(照旧 Getcl) =====
const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(30)
const filters = reactive({ keyword: '', years: [], dept: null })

function buildParams(withPage = true) {
  const p = {}
  if (withPage) { p.page = page.value; p.size = size.value }
  if (filters.keyword) p.keyword = filters.keyword
  if (filters.years.length) p.years = filters.years.join(',')
  if (filters.dept) p.dept = filters.dept
  return p
}
async function load() {
  loading.value = true
  try {
    const data = await listChuxian(buildParams())
    rows.value = data.items
    total.value = data.total
  } finally { loading.value = false }
}
function search() { page.value = 1; load() }
function resetFilters() {
  Object.assign(filters, { keyword: '', years: [], dept: null })
  search()
}
function showAll() {
  Object.assign(filters, { keyword: '', years: [], dept: null })
  page.value = 1
  load()
}
function filterByChehao(chehao) {
  filters.keyword = chehao
  search()
}
function money(v) { return Number(v || 0).toFixed(2).replace(/\.00$/, '') }
function fmt(v, len = 10) { return v ? String(v).slice(0, len) : '' }

onMounted(async () => {
  const d = await getChuxianDicts()
  Object.assign(dicts, d)
  load()
})

// ===== 勾选 =====
const selection = ref([])
function onSelectionChange(v) { selection.value = v }
function requireOne() {
  if (selection.value.length !== 1) { ElMessage.warning('请选中且仅选中一条记录'); return null }
  return selection.value[0]
}

// ===== 车辆远程检索(照旧 GetVehicles) =====
const vehicleOptions = ref([])
const vehicleLoading = ref(false)
async function searchVehicles(q) {
  vehicleLoading.value = true
  try { vehicleOptions.value = await searchChuxianVehicles(q) }
  finally { vehicleLoading.value = false }
}

// ===== 新增 / 编辑(照旧 dlg) =====
const dialog = ref(false)
const editingId = ref(null)
const saving = ref(false)
const formRef = ref()
const formLocked = ref(false)
const blankForm = () => ({
  cheid: null, riqi: '', zeren: '', dizhi: '', miaoshu: '',
  jine: null, jiashiyuan: '', gongli: null,
})
const form = reactive(blankForm())
const rules = {
  cheid: [{ required: true, message: '请选择车辆', trigger: 'change' }],
  zeren: [{ required: true, message: '请选择责任', trigger: 'change' }],
  riqi: [{ required: true, message: '请选择出险日期', trigger: 'change' }],
  dizhi: [{ required: true, message: '请输入违章路段', trigger: 'blur' }],
}

async function openCreate() {
  editingId.value = null
  formLocked.value = false
  Object.assign(form, blankForm())
  await searchVehicles('')
  dialog.value = true
}
async function openEdit(row) {
  const data = await getChuxian(row.id)
  editingId.value = data.id
  Object.assign(form, blankForm(), {
    cheid: data.cheid, riqi: data.riqi || '', zeren: data.zeren || '',
    dizhi: data.dizhi || '', miaoshu: data.miaoshu || '',
    jine: data.jine, jiashiyuan: data.jiashiyuan || '', gongli: data.gongli,
  })
  vehicleOptions.value = [{ id: data.cheid, text: data.chehao || '' }]
  formLocked.value = !isSuper.value && (data.caozuo || '') !== username.value
  dialog.value = true
}
async function fetchCarExtra() {
  if (!form.cheid || !form.riqi) { ElMessage.warning('请先选择车牌号和日期'); return }
  const res = await getChuxianCarExtra(form.cheid, form.riqi)
  if (!form.jiashiyuan && res.jiashiyuan) form.jiashiyuan = res.jiashiyuan
  if ((form.gongli === null || form.gongli === '') && res.gongli != null) form.gongli = res.gongli
  ElMessage.success('已从车辆/用车记录中获取数据，请核实')
}
function buildPayload() {
  return {
    cheid: form.cheid,
    riqi: form.riqi || null,
    zeren: form.zeren,
    dizhi: form.dizhi,
    miaoshu: form.miaoshu,
    jine: form.jine === '' ? null : form.jine,
    jiashiyuan: form.jiashiyuan,
    gongli: form.gongli === '' ? null : form.gongli,
  }
}
async function submitForm() {
  if (saving.value) return  // 防双击重复提交
  saving.value = true
  try {
    await formRef.value.validate()
    const payload = buildPayload()
    if (editingId.value) await updateChuxian(editingId.value, payload)
    else await createChuxian(payload)
    ElMessage.success(editingId.value ? '修改成功' : '保存成功')
    dialog.value = false
    load()
  } finally { saving.value = false }
}

// ===== 删除(照旧只有本人可删) =====
async function doDelete() {
  const row = requireOne(); if (!row) return
  if (!isSuper.value && (row.caozuo || '') !== username.value) {
    ElMessage.warning('只能删除自己录入的记录'); return
  }
  await ElMessageBox.confirm('确定要删除这条记录吗？', '确认', { type: 'warning' })
  await deleteChuxian(row.id)
  ElMessage.success('删除成功')
  load()
}
async function doExport() {
  await exportChuxian(buildParams(false))
  ElMessage.success('已导出 Excel')
}

// ===== 图片查看(短令牌直链) =====
const imageDialog = ref(false)
const imageList = ref([])
async function openImages(row) {
  const list = []
  for (const img of row.tps || []) {
    let src = ''
    try { src = (await createChuxianImageToken(img.id)).url } catch { /* 忽略 */ }
    list.push({ ...img, src, error: false })
  }
  imageList.value = list
  imageDialog.value = true
}
</script>

<template>
  <div class="chuxian-page">
    <!-- 查询条件(照旧 Getcl 筛选) -->
    <el-card shadow="never" class="filter-card">
      <div class="filter-title">车辆出险信息表</div>
      <el-form inline class="filter-form">
        <el-form-item label="关键字">
          <el-input v-model="filters.keyword" placeholder="车牌号、驾驶人、描述、责任"
            clearable style="width: 220px" @keyup.enter="search" />
        </el-form-item>
        <el-form-item label="年度">
          <el-select v-model="filters.years" multiple collapse-tags collapse-tags-tooltip
            placeholder="选择年度（可多选）" clearable style="width: 180px">
            <el-option v-for="y in dicts.years" :key="y" :label="`${y}年`" :value="y" />
          </el-select>
        </el-form-item>
        <el-form-item label="部门">
          <el-select v-model="filters.dept" placeholder="（全部部门）" clearable filterable
            style="width: 160px">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <!-- 工具栏(照旧 toolbar) -->
    <div class="toolbar">
      <el-button type="primary" size="small" @click="openCreate">添加</el-button>
      <el-button size="small" @click="() => { const r = requireOne(); if (r) openEdit(r) }">编辑</el-button>
      <el-button size="small" @click="doDelete">删除</el-button>
      <el-button size="small" @click="doExport">导出excel</el-button>
      <el-button size="small" @click="showAll">显示全部</el-button>
      <span class="toolbar-hint">共 {{ total }} 条 · 双击行可编辑 · 车牌号气泡可筛选该车全部出险</span>
    </div>

    <!-- 主表格(照旧 datagrid 12 列) -->
    <el-table v-loading="loading" :data="rows" border stripe size="small"
      height="calc(100vh - 290px)" row-key="id"
      @selection-change="onSelectionChange" @row-dblclick="openEdit">
      <el-table-column type="selection" width="42" />
      <el-table-column prop="bumen" label="部门" width="110" show-overflow-tooltip>
        <template #default="{ row }">{{ row.bm || row.bumen }}</template>
      </el-table-column>
      <el-table-column label="车牌号" width="150">
        <template #default="{ row }">
          <span v-if="row.cxCount > 1" class="chehao-wrap">
            {{ row.chehao }}
            <span class="cx-bubble" title="点击筛选该车全部出险"
              @click.stop="filterByChehao(row.chehao)">{{ row.cxCount }}</span>
          </span>
          <span v-else>{{ row.chehao }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="jiashiyuan" label="责任人" width="100" show-overflow-tooltip />
      <el-table-column prop="riqi" label="日期" width="110">
        <template #default="{ row }">{{ fmt(row.riqi) }}</template>
      </el-table-column>
      <el-table-column prop="zeren" label="责任" width="100" />
      <el-table-column prop="dizhi" label="地点" min-width="160" show-overflow-tooltip />
      <el-table-column prop="miaoshu" label="描述" min-width="220" show-overflow-tooltip />
      <el-table-column prop="jine" label="金额（元）" width="110">
        <template #default="{ row }">{{ money(row.jine) }}</template>
      </el-table-column>
      <el-table-column prop="caozuo" label="记录人" width="100" />
      <el-table-column prop="zuihou" label="最后操作日期" width="160">
        <template #default="{ row }">{{ fmt(row.zuihou, 16) }}</template>
      </el-table-column>
      <el-table-column prop="gongli" label="公里" width="90" />
      <el-table-column label="图片" width="90">
        <template #default="{ row }">
          <el-button v-if="row.tps?.length" link type="primary" size="small"
            @click="openImages(row)">{{ row.tps.length }} 张</el-button>
          <span v-else>-</span>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[30, 60, 120]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>

    <!-- 添加 / 编辑(照旧 dlg 单列字段顺序) -->
    <el-dialog v-model="dialog" :title="editingId ? '出险信息' : '添加出险信息'"
      width="520px" :close-on-click-modal="false">
      <el-alert v-if="formLocked" type="info" show-icon :closable="false"
        title="该记录由他人登记，仅可查看" class="lock-tip" />
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px"
        :disabled="formLocked">
        <el-form-item label="车牌号" prop="cheid">
          <el-select v-model="form.cheid" filterable remote :remote-method="searchVehicles"
            :loading="vehicleLoading" placeholder="输入车牌号搜索" style="width: 100%">
            <el-option v-for="o in vehicleOptions" :key="o.id" :label="o.text" :value="o.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="责任" prop="zeren">
          <el-select v-model="form.zeren" clearable placeholder="请选择责任" style="width: 100%">
            <el-option v-for="z in dicts.zeren" :key="z" :label="z" :value="z" />
          </el-select>
        </el-form-item>
        <el-form-item label="日期" prop="riqi">
          <el-date-picker v-model="form.riqi" type="date" value-format="YYYY-MM-DD"
            placeholder="选择出险日期" style="width: 100%" />
        </el-form-item>
        <el-form-item label="地址" prop="dizhi">
          <el-input v-model="form.dizhi" placeholder="请输入违章路段" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.miaoshu" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="金额">
          <el-input-number v-model="form.jine" :precision="2" :min="0"
            controls-position="right" style="width: 100%" />
        </el-form-item>
        <el-form-item label="驾驶人">
          <div class="jsr-row">
            <el-input v-model="form.jiashiyuan" style="flex: 1" />
            <el-button :disabled="formLocked" @click="fetchCarExtra">获取</el-button>
          </div>
        </el-form-item>
        <el-form-item label="公里数">
          <el-input-number v-model="form.gongli" :precision="0" :min="0"
            controls-position="right" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button v-if="!formLocked" type="primary" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>

    <!-- 出险图片 -->
    <el-dialog v-model="imageDialog" title="出险图片" width="700px">
      <div class="img-grid">
        <div v-for="img in imageList" :key="img.id" class="img-item">
          <img v-if="img.src && !img.error" :src="img.src" @error="img.error = true" />
          <div v-else class="img-missing">图片文件缺失<br /><small>需从旧系统服务器拷贝 Upload 目录</small></div>
        </div>
      </div>
      <div v-if="!imageList.length" class="tip">暂无图片</div>
    </el-dialog>
  </div>
</template>

<style scoped>
.chuxian-page { display: flex; flex-direction: column; gap: 10px; }
.filter-card :deep(.el-card__body) { padding: 10px 14px; }
.filter-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 12px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }
.chehao-wrap { display: inline-flex; align-items: center; gap: 6px; }
.cx-bubble {
  display: inline-flex; align-items: center; justify-content: center;
  flex: none; min-width: 18px; height: 18px; padding: 0 5px; box-sizing: border-box;
  font-size: 12px; line-height: 1; color: #000; background: #f5d75e;
  border-radius: 9px; cursor: pointer;
}
.lock-tip { margin-bottom: 12px; }
.jsr-row { display: flex; align-items: center; gap: 6px; width: 100%; }
.img-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.img-item { border: 1px solid #e4e7ed; border-radius: 4px; padding: 4px; text-align: center; }
.img-item img { width: 100%; height: 150px; object-fit: cover; display: block; }
.img-missing { height: 150px; display: flex; flex-direction: column; align-items: center;
  justify-content: center; color: #b3261e; font-size: 12px; background: #fafafa; }
.tip { color: #909399; font-size: 13px; padding: 8px 0; }
</style>
