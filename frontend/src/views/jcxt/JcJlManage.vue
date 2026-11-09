<script setup>
/** 稽查奖励(照旧 JcJl/Index.cshtml 1:1 复刻):月度奖励汇总 + 按人分配 */
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  assignJcjl, deleteJcjlFp, getJcjlDicts, getJcjlNames, getJcjlRemain,
  listJcjl, listJcjlFps,
} from '@/api/jcxt'

const filters = reactive({ rq: `${new Date().getFullYear()}-01-01`, rqend: today(), bmid: null })
function today() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

const dicts = reactive({ departments: [], hideDept: false })
const rows = ref([])
const total = ref(0)
const page = reactive({ current: 1, size: 30 })
const loading = ref(false)

async function load() {
  loading.value = true
  try {
    const res = await listJcjl({
      ...filters, bmid: filters.bmid || undefined,
      page: page.current, size: page.size,
    })
    rows.value = res.items
    total.value = res.total
    // 单部门用户隐藏部门筛选(照旧 xsbm=="无部门")
    dicts.hideDept = dicts.departments.length < 2
  } finally {
    loading.value = false
  }
}
function doSearch() { page.current = 1; load() }

const expandRows = reactive({})
async function onExpand(row, expanded) {
  if (!expanded.includes(row.ID)) return
  try {
    const res = await listJcjlFps(row.ID)
    expandRows[row.ID] = res.items
  } catch {
    expandRows[row.ID] = []
  }
}

function rowClass({ row }) {
  if (row.bm === '售水事业部' && row.zjbutie === row.jianglijine) return 'row-gold'
  return ''
}
function zjbutieFmt(row) {
  const v = row.zjbutie
  if (v == null) return ''
  return row.bm === '售水事业部' ? `${v}(核对售水总奖励金额)` : String(v)
}

// 分配弹窗
const fpDlg = ref(false)
const fp = reactive({ jlid: null, fpname: '', fpjine: null, remain: 0 })
const nameOptions = ref([])
const saving = ref(false)

async function addFenpei(row) {
  fp.jlid = row.ID
  fp.fpname = ''
  fp.fpjine = null
  try {
    const names = await getJcjlNames(row.ID)
    nameOptions.value = names.map(n => ({ value: n.fpname }))
    const remain = await getJcjlRemain(row.ID)
    fp.remain = remain.remain
  } catch { /* */ }
  fpDlg.value = true
}
async function saveFenpei() {
  if (!fp.fpname) return ElMessage.warning('请选择分配姓名')
  if (fp.fpjine == null || fp.fpjine <= 0) return ElMessage.warning('请输入分配金额')
  if (fp.fpjine > fp.remain) {
    return ElMessage.warning(`分配金额超过奖励金额(差额 ${fp.remain})`)
  }
  saving.value = true
  try {
    await assignJcjl({ jlid: fp.jlid, fpname: fp.fpname, fpjine: fp.fpjine })
    const remain = await getJcjlRemain(fp.jlid)
    fp.remain = remain.remain
    await load()
    if (fp.remain === 0) {
      fpDlg.value = false
      ElMessage.success('该条奖励金额分配完毕')
    } else {
      ElMessage.success('分配成功')
      // 刷新姓名下拉(剔除刚分配过的)
      const names = await getJcjlNames(fp.jlid)
      nameOptions.value = names.map(n => ({ value: n.fpname }))
      fp.fpname = ''
      fp.fpjine = null
    }
  } catch { /* */ } finally { saving.value = false }
}
async function delFp(row) {
  try {
    await ElMessageBox.confirm('确定要删除吗?', '提示', { type: 'warning' })
  } catch { return }
  try {
    await deleteJcjlFp(row.id)
    ElMessage.success('已删除')
    load()
  } catch { /* */ }
}

onMounted(async () => {
  try {
    const res = await getJcjlDicts()
    Object.assign(dicts, res)
  } catch { /* */ }
  load()
})
</script>

<template>
  <div class="jcjl-page">
    <el-card shadow="never" class="filter-card">
      <div class="filter-title">稽查奖励分配</div>
      <div class="filter-grid">
        <el-date-picker v-model="filters.rq" type="date" value-format="YYYY-MM-DD"
          placeholder="开始日期" style="width: 130px" @change="doSearch" />
        <el-date-picker v-model="filters.rqend" type="date" value-format="YYYY-MM-DD"
          placeholder="结束日期" style="width: 130px" @change="doSearch" />
        <el-select v-if="!dicts.hideDept" v-model="filters.bmid" placeholder="===选择部门==="
          clearable style="width: 150px" @change="doSearch">
          <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
        </el-select>
        <div class="btns">
          <el-button type="primary" size="small" @click="doSearch">查询</el-button>
        </div>
      </div>
    </el-card>

    <el-table :data="rows" v-loading="loading" row-key="ID" height="calc(100vh - 320px)"
      border :row-class-name="rowClass" @expand-change="onExpand">
      <el-table-column type="expand">
        <template #default="{ row }">
          <el-table :data="expandRows[row.ID] || []" size="small" border>
            <el-table-column width="60" label="操作">
              <template #default="p">
                <el-link type="danger" :underline="false" title="删除分配"
                  @click="delFp(p.row)">✕</el-link>
              </template>
            </el-table-column>
            <el-table-column prop="fpname" label="分配姓名" width="110" />
            <el-table-column prop="fpjine" label="金额(元)" width="100" />
            <el-table-column prop="uname" label="操作员" width="100" />
            <el-table-column prop="utime" label="分配日期" width="150" />
          </el-table>
        </template>
      </el-table-column>
      <el-table-column label="分配奖励" width="90">
        <template #default="{ row }">
          <el-link v-if="row.operation !== 0" type="primary" :underline="false"
            title="分配奖励" @click="addFenpei(row)">💰</el-link>
        </template>
      </el-table-column>
      <el-table-column prop="num" label="已分配人数" width="90" />
      <el-table-column prop="wfp" label="未分配金额" width="100" />
      <el-table-column prop="zjshuifei" label="追缴水费金额" width="110" />
      <el-table-column prop="jbjiangli" label="举报奖励" width="90" />
      <el-table-column prop="zjbutie_int" label="追缴补贴" width="90" />
      <el-table-column prop="jianglijine" label="奖励金额" width="100" />
      <el-table-column label="追缴补贴(小数)" width="190">
        <template #default="{ row }">{{ zjbutieFmt(row) }}</template>
      </el-table-column>
      <el-table-column prop="usname" label="操作用户" width="90" />
      <el-table-column prop="utime" label="操作日期" width="150" />
      <el-table-column prop="ID" label="流水号" width="70" />
      <el-table-column prop="nd" label="年度" width="70" />
      <el-table-column prop="yue" label="月份" width="60" />
      <el-table-column prop="bm" label="部门名称" min-width="110" />
    </el-table>
    <el-pagination v-model:current-page="page.current" v-model:page-size="page.size"
      :total="total" :page-sizes="[30, 120, 300]" layout="total, sizes, prev, pager, next"
      @change="load" />

    <el-dialog v-model="fpDlg" title="分配费用项目" width="440px"
      class="jc-form-dialog" :close-on-click-modal="false">
      <div class="remain-line">剩余额度:<span class="remain">{{ fp.remain }}</span></div>
      <el-form label-width="90px" size="small">
        <el-form-item label="分配姓名" required>
          <el-select v-model="fp.fpname" filterable allow-create default-first-option
            placeholder="选择或输入姓名" style="width: 100%">
            <el-option v-for="n in nameOptions" :key="n.value" :label="n.value" :value="n.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="分配金额" required>
          <el-input-number v-model="fp.fpjine" :precision="0" :controls="false"
            style="width: 100%" @keyup.enter="saveFenpei" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="fpDlg = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveFenpei">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style>
.jcjl-page { padding: 12px; }
.jcjl-page .filter-card { margin-bottom: 10px; }
.jcjl-page .filter-title { font-size: 16px; font-weight: 600; margin-bottom: 8px; }
.jcjl-page .filter-grid { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.jcjl-page .btns { display: flex; gap: 4px; }
.jcjl-page .row-gold { background: rgba(217, 154, 43, 0.12); }
.jcjl-page .remain-line { margin-bottom: 10px; font-size: 13px; }
.jcjl-page .remain { color: var(--el-color-danger); font-weight: 600; }
</style>
