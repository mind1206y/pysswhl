<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createWeizhang, deleteWeizhang, exportWeizhang, getLatestWzDetail, getWeizhang,
  getWeizhangDicts, getWeizhangDriver, listWeizhang, searchWeizhangContents,
  searchWeizhangVehicles, updateWeizhang,
} from '@/api/weizhang'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const username = computed(() => auth.user?.username || '')
const isSuper = computed(() => !!auth.user?.is_superuser)

// ===== 字典 =====
const dicts = reactive({ departments: [], years: [] })

// ===== 列表与筛选(照旧 GetData) =====
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
    const data = await listWeizhang(buildParams())
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
function money(v) { return v ? `¥${Number(v).toFixed(2)}` : '' }
function fmt(v, len = 10) { return v ? String(v).slice(0, len) : '' }

onMounted(async () => {
  const d = await getWeizhangDicts()
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

// ===== 驾驶员悬浮名片(照旧 GetSjByChehao) =====
const driverCache = reactive({})
const driverText = ref('')
async function showDriver(chehao) {
  if (!chehao) { driverText.value = ''; return }
  if (driverCache[chehao]) { driverText.value = driverCache[chehao]; return }
  driverText.value = '加载中...'
  try {
    const data = await getWeizhangDriver(chehao)
    driverCache[chehao] = data?.jiashiyuan
      ? `系统登记的驾驶员是 ${data.jiashiyuan}`
      : '未找到该车牌信息'
  } catch {
    driverCache[chehao] = '未找到该车牌信息'
  }
  driverText.value = driverCache[chehao]
}

// ===== 车辆远程检索(照旧 GetVehicles) =====
const vehicleOptions = ref([])
const vehicleLoading = ref(false)
async function searchVehicles(q) {
  vehicleLoading.value = true
  try { vehicleOptions.value = await searchWeizhangVehicles(q) }
  finally { vehicleLoading.value = false }
}

// ===== 违章内容联想(照旧 SearchWzContent + GetLatestWzDetail) =====
async function fetchContents(q, cb) {
  if (!q) { cb([]); return }
  try {
    const list = await searchWeizhangContents(q)
    cb(list.map((i) => ({ value: i.text })))
  } catch { cb([]) }
}
async function onWzSelect(item) {
  if (!item?.value) return
  const res = await getLatestWzDetail(item.value)
  form.fen = res.fen || 0
  form.jine = res.jine || 0
}

// ===== 新增 / 编辑(照旧 dlg) =====
const dialog = ref(false)
const editingId = ref(null)
const formRef = ref()
const formLocked = ref(false)
const blankForm = () => ({
  cheid: null, wzriqi: '', lu: '', wz: '', fen: null, jine: null,
  xingming: '', gongli: null,
})
const form = reactive(blankForm())
const rules = {
  cheid: [{ required: true, message: '请选择车辆', trigger: 'change' }],
  wzriqi: [{ required: true, message: '请选择违章日期', trigger: 'change' }],
  lu: [{ required: true, message: '请输入违章路段', trigger: 'blur' }],
}

async function openCreate() {
  editingId.value = null
  formLocked.value = false
  Object.assign(form, blankForm())
  await searchVehicles('')
  dialog.value = true
}
async function openEdit(row) {
  const data = await getWeizhang(row.id)
  editingId.value = data.id
  Object.assign(form, blankForm(), {
    cheid: data.cheid, wzriqi: data.wzriqi || '', lu: data.lu || '',
    wz: data.wz || '', fen: data.fen, jine: data.jine,
    xingming: data.xingming || '', gongli: data.gongli,
  })
  vehicleOptions.value = [{ id: data.cheid, text: data.chehao || '' }]
  formLocked.value = !isSuper.value && (data.dj || '') !== username.value
  dialog.value = true
}
function buildPayload() {
  return {
    cheid: form.cheid,
    wzriqi: form.wzriqi || null,
    lu: form.lu,
    wz: form.wz,
    fen: form.fen === '' ? null : form.fen,
    jine: form.jine === '' ? null : form.jine,
    xingming: form.xingming,
    gongli: form.gongli === '' ? null : form.gongli,
  }
}
async function submitForm() {
  await formRef.value.validate()
  const payload = buildPayload()
  if (editingId.value) await updateWeizhang(editingId.value, payload)
  else await createWeizhang(payload)
  ElMessage.success(editingId.value ? '修改成功' : '保存成功')
  dialog.value = false
  load()
}

// ===== 删除(照旧只有本人可删) =====
async function doDelete() {
  const row = requireOne(); if (!row) return
  if (!isSuper.value && (row.dj || '') !== username.value) {
    ElMessage.warning('只能删除自己录入的记录'); return
  }
  await ElMessageBox.confirm('确定要删除这条记录吗？', '确认', { type: 'warning' })
  await deleteWeizhang(row.id)
  ElMessage.success('删除成功')
  load()
}
async function doExport() {
  await exportWeizhang(buildParams(false))
  ElMessage.success('已导出 Excel')
}
</script>

<template>
  <div class="weizhang-page">
    <!-- 查询条件(照旧 GetData 筛选) -->
    <el-card shadow="never" class="filter-card">
      <div class="filter-title">车辆违章信息表</div>
      <el-form inline class="filter-form">
        <el-form-item label="关键字">
          <el-input v-model="filters.keyword" placeholder="车牌号、违章人、路段、内容、登记人"
            clearable style="width: 260px" @keyup.enter="search" />
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
      <span class="toolbar-hint">共 {{ total }} 条 · 双击行可编辑 · 车牌号气泡可筛选该车全部违章</span>
    </div>

    <!-- 主表格(照旧 datagrid 12 列) -->
    <el-table v-loading="loading" :data="rows" border stripe size="small"
      height="calc(100vh - 290px)" row-key="id"
      @selection-change="onSelectionChange" @row-dblclick="openEdit">
      <el-table-column type="selection" width="42" />
      <el-table-column prop="bumen" label="所属部门" width="120" show-overflow-tooltip />
      <el-table-column label="车牌号" width="150">
        <template #default="{ row }">
          <el-tooltip placement="top" :content="driverText" :disabled="!driverText">
            <span class="chehao-wrap" @mouseenter="showDriver(row.chehao)">
              {{ row.chehao }}
              <span v-if="row.wzCount > 1" class="wz-bubble"
                title="点击筛选该车全部违章"
                @click.stop="filterByChehao(row.chehao)">{{ row.wzCount }}</span>
            </span>
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column prop="gongli" label="公里数" width="90" />
      <el-table-column prop="xingming" label="违章人" width="100" show-overflow-tooltip />
      <el-table-column prop="wzriqi" label="违章日期" width="110">
        <template #default="{ row }">{{ fmt(row.wzriqi) }}</template>
      </el-table-column>
      <el-table-column prop="lu" label="违章路段" min-width="180" show-overflow-tooltip />
      <el-table-column prop="wz" label="违章内容" min-width="220" show-overflow-tooltip />
      <el-table-column prop="jine" label="罚款金额" width="110">
        <template #default="{ row }">{{ money(row.jine) }}</template>
      </el-table-column>
      <el-table-column prop="fen" label="扣分" width="70" />
      <el-table-column prop="dj" label="登记人" width="100" />
      <el-table-column prop="djriqi" label="登记日期" width="160">
        <template #default="{ row }">{{ fmt(row.djriqi, 16) }}</template>
      </el-table-column>
      <el-table-column prop="zhriqi" label="最后更新日期" width="160">
        <template #default="{ row }">{{ fmt(row.zhriqi, 16) }}</template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[30, 60, 120]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>

    <!-- 添加 / 编辑(照旧 dlg 单列字段顺序) -->
    <el-dialog v-model="dialog" :title="editingId ? '违章信息' : '添加违章信息'"
      width="520px" :close-on-click-modal="false">
      <el-alert v-if="formLocked" type="info" show-icon :closable="false"
        title="该记录由他人登记，仅可修改违章人和公里数" class="lock-tip" />
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
        <el-form-item label="车牌号" prop="cheid">
          <el-select v-model="form.cheid" filterable remote :remote-method="searchVehicles"
            :loading="vehicleLoading" :disabled="formLocked"
            placeholder="输入车牌号搜索" style="width: 100%">
            <el-option v-for="o in vehicleOptions" :key="o.id" :label="o.text" :value="o.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="违章日期" prop="wzriqi">
          <el-date-picker v-model="form.wzriqi" type="date" value-format="YYYY-MM-DD"
            :disabled="formLocked" placeholder="选择违章日期" style="width: 100%" />
        </el-form-item>
        <el-form-item label="违章路段" prop="lu">
          <el-input v-model="form.lu" :disabled="formLocked" placeholder="请输入违章路段" />
        </el-form-item>
        <el-form-item label="违章内容">
          <el-autocomplete v-model="form.wz" :disabled="formLocked"
            :fetch-suggestions="fetchContents" :trigger-on-focus="false"
            placeholder="输入违章内容…" style="width: 100%" @select="onWzSelect" />
        </el-form-item>
        <el-form-item label="扣分">
          <el-input-number v-model="form.fen" :precision="0" :min="0"
            :disabled="formLocked" controls-position="right" style="width: 100%" />
        </el-form-item>
        <el-form-item label="罚款金额">
          <el-input-number v-model="form.jine" :precision="2" :min="0"
            :disabled="formLocked" controls-position="right" style="width: 100%" />
        </el-form-item>
        <el-form-item label="违章人">
          <el-input v-model="form.xingming" />
        </el-form-item>
        <el-form-item label="公里数">
          <el-input-number v-model="form.gongli" :precision="0" :min="0"
            controls-position="right" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" @click="submitForm">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.weizhang-page { display: flex; flex-direction: column; gap: 10px; }
.filter-card :deep(.el-card__body) { padding: 10px 14px; }
.filter-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 12px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.toolbar-hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }
.chehao-wrap { position: relative; display: inline-block; padding-right: 18px; cursor: default; }
.wz-bubble {
  position: absolute; top: -6px; right: 0; width: 18px; height: 18px; line-height: 18px;
  text-align: center; font-size: 12px; color: #000; background: #f5d75e;
  border-radius: 50%; cursor: pointer;
}
.lock-tip { margin-bottom: 12px; }
</style>
