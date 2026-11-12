<script setup>
/** 稽查单(照旧 jcdan/Index.cshtml + addFrmShow.cshtml 1:1 复刻) */
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  addJcdan, deleteJcdan, getJcdanDicts, getJcdanPz, listJcdan, updateJcdan,
} from '@/api/jcxt'

const filters = reactive({ sousou: '', rq: yearStart(), rqend: today(), bmid: null })
function yearStart() {
  return `${new Date().getFullYear()}-01-01`
}
function today() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const rows = ref([])
const total = ref(0)
const page = reactive({ current: 1, size: 30 })
const loading = ref(false)
const dicts = reactive({ jbleibie: [] })

async function load() {
  loading.value = true
  try {
    const res = await listJcdan({
      ...filters, bmid: filters.bmid || undefined,
      page: page.current, size: page.size,
    })
    rows.value = res.items
    total.value = res.total
  } finally {
    loading.value = false
  }
}
function doSearch() { page.current = 1; load() }
function resetFilters() {
  Object.assign(filters, { sousou: '', rq: yearStart(), rqend: today(), bmid: null })
  doSearch()
}

// 子表格
const expandRows = reactive({})
async function onExpand(row, expanded) {
  if (!expanded.includes(row.ID)) return
  try {
    const res = await getJcdanPz(row.ID)
    expandRows[row.ID] = res.items
  } catch {
    expandRows[row.ID] = []
  }
}

// 添加/编辑弹窗
const dlg = ref(false)
const dlgMode = ref('add')
const saving = ref(false)
const formRef = ref()
const form = reactive(emptyForm())
function emptyForm() {
  return {
    id: null, gongdanhao: '', bianhao: '', weizhangdanwei: '', jbleibie: '',
    jbren: '', fstime: '', didian: '', nr: '', bz: '', wzren: '',
    weizhangdianhua: '', kpren: '', usname: '',
  }
}
const rules = { fstime: [{ required: true, message: '发生时间为必填项', trigger: 'change' }] }

function openAdd() {
  Object.assign(form, emptyForm())
  dlgMode.value = 'add'
  dlg.value = true
}
async function openEdit(row) {
  Object.assign(form, emptyForm(), {
    id: row.id,
    gongdanhao: row.gongdanhao || '',
    bianhao: row.bianhao || '',
    weizhangdanwei: row.weizhangdanwei || '',
    jbleibie: row.jbleibie || '',
    jbren: row.jbren || '',
    fstime: (row.fstime || '').slice(0, 10),
    didian: row.didian || '',
    nr: row.nr || '',
    bz: row.bz || '',
    wzren: row.wzren || '',
    weizhangdianhua: row.weizhangdianhua || '',
    kpren: row.kpren || '',
    usname: row.usname || '',
  })
  dlgMode.value = 'edit'
  dlg.value = true
}
async function save() {
  if (saving.value) return  // 防双击重复提交
  try { await formRef.value.validate() } catch { return }
  saving.value = true
  try {
    const payload = { ...form }
    delete payload.id
    if (dlgMode.value === 'add') await addJcdan(payload)
    else await updateJcdan(form.id, payload)
    ElMessage.success('保存成功')
    dlg.value = false
    load()
  } catch { /* */ } finally { saving.value = false }
}
async function onDelete() {
  const sel = tableRef.value?.getSelectionRows() || []
  if (sel.length !== 1) return ElMessage.warning('请勾选一条记录')
  try {
    await ElMessageBox.confirm('确定删除该稽查单?', '提示', { type: 'warning' })
  } catch { return }
  try {
    await deleteJcdan(sel[0].id)
    ElMessage.success('已删除')
    load()
  } catch { /* */ }
}

const tableRef = ref()
onMounted(async () => {
  try {
    const res = await getJcdanDicts()
    Object.assign(dicts, res)
  } catch { /* */ }
  load()
})
</script>

<template>
  <div class="jcdan-page">
    <el-card shadow="never" class="filter-card">
      <div class="filter-title">稽查单汇总表</div>
      <div class="filter-grid">
        <el-input v-model="filters.sousou" placeholder="模糊查询" clearable
          style="width: 220px" @keyup.enter="doSearch" @clear="doSearch" />
        <el-date-picker v-model="filters.rq" type="date" value-format="YYYY-MM-DD"
          placeholder="开始日期" style="width: 130px" @change="doSearch" />
        <el-date-picker v-model="filters.rqend" type="date" value-format="YYYY-MM-DD"
          placeholder="结束日期" style="width: 130px" @change="doSearch" />
        <div class="btns">
          <el-button type="primary" size="small" @click="doSearch">查询</el-button>
          <el-button size="small" @click="resetFilters">重置</el-button>
        </div>
      </div>
      <div class="toolbar">
        <el-button size="small" type="primary" @click="openAdd">添加</el-button>
        <el-button size="small" type="warning" @click="openEdit(tableRef?.getSelectionRows()?.[0] || {})">
          编辑
        </el-button>
        <el-button size="small" type="danger" @click="onDelete">删除</el-button>
      </div>
    </el-card>

    <el-table ref="tableRef" :data="rows" v-loading="loading" row-key="ID"
      height="calc(100vh - 300px)" border
      :row-class-name="({ row }) => (row.colo !== '0' ? 'row-linked' : '')"
      @expand-change="onExpand" @row-dblclick="openEdit">
      <el-table-column type="expand">
        <template #default="{ row }">
          <el-table :data="expandRows[row.ID] || []" size="small" border>
            <el-table-column prop="weizhangriqi" label="违章日期" width="90" />
            <el-table-column prop="weizhangren" label="违章单位" min-width="140" />
            <el-table-column prop="weizhangdizhi" label="违章地点" min-width="150" />
            <el-table-column prop="weizhangneirong" label="违章内容" min-width="180" />
            <el-table-column prop="weizhangdianhua" label="违章电话" width="100" />
            <el-table-column prop="chuliriqi" label="处理日期" width="90" />
            <el-table-column prop="zhuijiaoshuiliang" label="追缴水量" width="80" />
            <el-table-column prop="zhuijiaoshuifei" label="追缴水费" width="80" />
            <el-table-column prop="zhuijiaogongliaofei" label="追缴工料费" width="90" />
          </el-table>
        </template>
      </el-table-column>
      <el-table-column type="selection" width="38" />
      <el-table-column prop="ID" label="流水号" width="60" />
      <el-table-column prop="bm" label="部门" width="90" />
      <el-table-column prop="gongdanhao" label="工单号" width="90" />
      <el-table-column prop="bianhao" label="编号" width="90" />
      <el-table-column prop="fstime" label="发生时间" width="140" />
      <el-table-column prop="weizhangdanwei" label="违章单位(者)" min-width="160" show-overflow-tooltip />
      <el-table-column prop="weizhangdianhua" label="违章电话" width="100" />
      <el-table-column prop="didian" label="违章地点" min-width="160" show-overflow-tooltip />
      <el-table-column prop="nr" label="违章情况描述" min-width="200" show-overflow-tooltip />
      <el-table-column prop="bz" label="备注" min-width="160" show-overflow-tooltip />
      <el-table-column prop="jbleibie" label="举报类别" width="85" />
      <el-table-column prop="jbren" label="举报人" width="80" />
      <el-table-column prop="wzren" label="违章签收人" width="90" />
      <el-table-column prop="kpren" label="开票人" width="80" />
      <el-table-column prop="addtime" label="建单日期" width="150" />
      <el-table-column prop="edtime" label="编辑日期" width="150" />
      <el-table-column prop="usname" label="登记人" width="80" />
    </el-table>
    <el-pagination v-model:current-page="page.current" v-model:page-size="page.size"
      :total="total" :page-sizes="[30, 120, 300]" layout="total, sizes, prev, pager, next"
      @change="load" />

    <el-dialog v-model="dlg" :title="dlgMode === 'add' ? '添加稽查单' : '修改稽查单'"
      width="760px" class="jc-form-dialog" :close-on-click-modal="false">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="90px" size="small">
        <el-tabs>
          <el-tab-pane label="稽查单信息">
            <div class="grid2">
              <el-form-item label="工单号"><el-input v-model="form.gongdanhao" /></el-form-item>
              <el-form-item label="编号"><el-input v-model="form.bianhao" /></el-form-item>
              <el-form-item label="违章单位(者)"><el-input v-model="form.weizhangdanwei" /></el-form-item>
              <el-form-item label="举报类别">
                <el-select v-model="form.jbleibie" clearable style="width: 100%">
                  <el-option v-for="j in dicts.jbleibie" :key="j" :label="j" :value="j" />
                </el-select>
              </el-form-item>
              <el-form-item label="举报人"><el-input v-model="form.jbren" /></el-form-item>
              <el-form-item label="发生时间" required prop="fstime">
                <el-date-picker v-model="form.fstime" type="date" value-format="YYYY-MM-DD"
                  style="width: 100%" />
              </el-form-item>
              <el-form-item label="违章地点" class="span2"><el-input v-model="form.didian" /></el-form-item>
              <el-form-item label="违章情况描述" class="span2">
                <el-input v-model="form.nr" type="textarea" :rows="3" />
              </el-form-item>
            </div>
          </el-tab-pane>
          <el-tab-pane label="违章人">
            <div class="grid2">
              <el-form-item label="备注"><el-input v-model="form.bz" /></el-form-item>
              <el-form-item label="违章签收人"><el-input v-model="form.wzren" /></el-form-item>
              <el-form-item label="违章人电话"><el-input v-model="form.weizhangdianhua" /></el-form-item>
              <el-form-item label="开票人"><el-input v-model="form.kpren" /></el-form-item>
            </div>
          </el-tab-pane>
        </el-tabs>
      </el-form>
      <template #footer>
        <el-button @click="dlg = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style>
.jcdan-page { padding: 12px; }
.jcdan-page .filter-card { margin-bottom: 10px; }
.jcdan-page .filter-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.jcdan-page .filter-grid { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.jcdan-page .btns { display: flex; gap: 4px; }
.jcdan-page .toolbar { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; }
.jcdan-page .row-linked { background: var(--el-color-success-light-9); }
.jcdan-page .grid2 { display: grid; grid-template-columns: 1fr 1fr; gap: 0 16px; }
.jcdan-page .grid2 .span2 { grid-column: span 2; }
</style>
