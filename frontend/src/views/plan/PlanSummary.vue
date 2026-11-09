<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  batchSummaryJhlb, batchSummaryLeibie, batchSummaryZb, changeSummaryStatus,
  checkRenumber, copyToOfficial, createSummary, deleteSummary, downloadSummaryTemplate,
  exportSummary, exportSummaryPage, getSummaryDicts, getSummaryItem,
  getSummaryLogs, importSummary, listSummary, renumber, setPlanLock, updateSummary,
} from '@/api/plan'
import PlanFormDialog from './PlanFormDialog.vue'
import SmsConfirmDialog from './SmsConfirmDialog.vue'
import { SUMMARY_STATUS, money, statusText, statusType, tzInfo } from './common'

const dicts = reactive({
  years: [], default_year: null, departments: [], hosts: [], zgys: [], categories: [],
  leibie: [], statuses: SUMMARY_STATUS, locks: { apply: false, summary: false },
  perms: { manage: false, admin: false },
})
const filters = reactive({ nd: null, jhlb: '更新改造', bumenid: null, zb: null, zgy: '', mohu: '', zt: '', px: false })
const rows = ref([])
const total = ref(0)
const tj = ref(0)
const tjtz = ref(0)
const counts = ref({})
const footer = ref([])
const page = ref(1)
const size = ref(30)
const loading = ref(false)
const selection = ref([])
let firstLoad = true

const selectedIds = computed(() => selection.value.map((r) => r.ID || r.id))

function catLabel(c) {
  const n = counts.value[c]
  return n ? `${c} (${n})` : c
}

function buildParams(withPage = true) {
  const p = {
    nd: filters.nd, jhlb: filters.jhlb, mohu: filters.mohu,
    bumenid: filters.bumenid || undefined, zb: filters.zb || undefined,
    zgy: filters.zgy || undefined, zt: filters.zt, px: filters.px, first_load: firstLoad,
  }
  if (withPage) { p.page = page.value; p.size = size.value }
  return p
}

async function load() {
  loading.value = true
  try {
    const data = await listSummary(buildParams())
    rows.value = data.rows
    total.value = data.total
    tj.value = data.tj
    tjtz.value = data.tjtz
    counts.value = data.counts || {}
    footer.value = data.footer || []
    if (firstLoad) {
      firstLoad = false
      if (data.default_zt) {
        filters.zt = data.default_zt
        loading.value = false
        return load()
      }
    }
  } finally {
    loading.value = false
  }
}

function search() { page.value = 1; firstLoad = false; load() }
function resetFilters() {
  Object.assign(filters, { nd: dicts.default_year, jhlb: '更新改造', bumenid: null, zb: null, zgy: '', mohu: '', zt: '售水待汇总', px: false })
  search()
}
function switchStatus(zt) {
  filters.zt = filters.zt === zt ? '' : zt
  search()
}
function onSelectionChange(val) { selection.value = val }

// ===== 添加 / 编辑 =====
const formOpen = ref(false)
const formEditing = ref(false)
const formItem = ref(null)
const editId = ref(null)

function openAdd() {
  formEditing.value = false
  editId.value = null
  formItem.value = null
  dicts.__opname = ''
  formOpen.value = true
}
async function openEdit(row) {
  if (!row) {
    if (selection.value.length !== 1) return ElMessage.warning('请选择一条记录')
    row = selection.value[0]
  }
  if (['删除', '已回退'].includes(row.zt)) return ElMessage.warning('已删除或已回退的记录无法编辑')
  const data = await getSummaryItem(row.ID || row.id)
  editId.value = data.id
  formItem.value = data
  dicts.__opname = data.opname
  formEditing.value = true
  formOpen.value = true
}
async function onSave(payload, action) {
  let r
  if (formEditing.value) {
    r = await updateSummary(editId.value, { ...payload, approve: action === 'approve' })
    if (r.ok && r.approve) await changeSummaryStatus({ ids: [editId.value], zt: '售水通过', iftel: false })
  } else {
    r = await createSummary(payload)
  }
  if (!r.ok) return ElMessage.warning(r.message)
  ElMessage.success(r.message || '保存成功')
  formOpen.value = false
  load()
}

async function onReturnFromForm(payload) {
  let pizhu = ''
  try {
    const { value } = await ElMessageBox.prompt('可填写回退批注（选填）', '回退营业所', {
      inputPlaceholder: '回退批注', confirmButtonText: '确定回退', cancelButtonText: '取消',
    })
    pizhu = value || ''
  } catch { return }
  // 照旧:先保存弹窗修改,再回退营业所
  const saved = await updateSummary(editId.value, { ...payload, approve: false })
  if (!saved.ok) return ElMessage.warning(saved.message)
  const r = await changeSummaryStatus({ ids: [editId.value], zt: '已回退', iftel: false, pizhu })
  if (!r.ok) return ElMessage.warning(r.message)
  ElMessage.success(r.message)
  formOpen.value = false
  load()
}

// ===== 确认弹窗(短信通知/批注) =====
const confirmState = reactive({
  visible: false, title: '', message: '', smsLabel: '', showComment: false, type: 'info',
})
let confirmHandler = null
function askConfirm(options, handler) {
  Object.assign(confirmState, {
    visible: true, title: '', message: '', smsLabel: '', showComment: false, type: 'info', ...options,
  })
  confirmHandler = handler
}
async function onConfirm({ sms, comment }) {
  const handler = confirmHandler
  confirmHandler = null
  if (handler) await handler(sms, comment)
}

// ===== 批量流转 =====
async function doApprove() {
  if (!selectedIds.value.length) return ElMessage.warning('请选择记录')
  try { await ElMessageBox.confirm('确定要通过选中的计划吗？', '通过计划', { type: 'info' }) } catch { return }
  const r = await changeSummaryStatus({ ids: selectedIds.value, zt: '售水通过', iftel: false })
  if (!r.ok) return ElMessage.warning(r.message)
  ElMessage.success(r.message); load()
}

function doReturnBumen() {
  if (!selectedIds.value.length) return ElMessage.warning('请选择记录')
  askConfirm({
    title: '回退营业所',
    message: selectedIds.value.length > 1
      ? `已选择 ${selectedIds.value.length} 条，将回退能回退的记录。`
      : '确定要回退到营业所吗？',
    smsLabel: '营业所', showComment: true,
  }, async (sms, comment) => {
    const r = await changeSummaryStatus({
      ids: selectedIds.value, zt: '已回退', iftel: sms, pizhu: comment,
    })
    if (!r.ok) return ElMessage.warning(r.message)
    ElMessage.success(r.message); load()
  })
}

function doReturnZgy() {
  if (!selectedIds.value.length) return ElMessage.warning('请选择记录')
  askConfirm({
    title: '回退专管员', message: '确定要回退专管员吗？',
    smsLabel: '专管员', type: 'warning',
  }, async (sms) => {
    const r = await changeSummaryStatus({ ids: selectedIds.value, zt: '专管员落实', iftel: sms })
    if (!r.ok) return ElMessage.warning(r.message)
    ElMessage.success(r.message); load()
  })
}

async function doRevert() {
  if (!selectedIds.value.length) return ElMessage.warning('请选择记录')
  try { await ElMessageBox.confirm('确定要收回通过，退回售水待汇总吗？', '收回通过', { type: 'warning' }) } catch { return }
  const r = await changeSummaryStatus({ ids: selectedIds.value, zt: '售水待汇总', iftel: false })
  if (!r.ok) return ElMessage.warning(r.message)
  ElMessage.success(r.message); load()
}

async function doDelete() {
  if (!selectedIds.value.length) return ElMessage.warning('请选择记录')
  try { await ElMessageBox.confirm('确定要删除数据吗？', '删除', { type: 'warning' }) } catch { return }
  const r = await deleteSummary(selectedIds.value)
  if (!r.ok) return ElMessage.warning(r.message)
  ElMessage.success(r.message); load()
}

// ===== 批量修改 =====
const zbDialog = ref(false); const zbValue = ref(null)
function openBatchZb() { if (!selectedIds.value.length) return ElMessage.warning('请选择记录'); zbValue.value = null; zbDialog.value = true }
async function submitBatchZb() {
  if (!zbValue.value) return ElMessage.warning('请选择主办部门')
  const r = await batchSummaryZb(selectedIds.value, zbValue.value)
  if (!r.ok) return ElMessage.warning(r.message)
  ElMessage.success(r.message); zbDialog.value = false; load()
}
const jhlbDialog = ref(false); const jhlbValue = ref('更新改造')
function openBatchJhlb() { if (!selectedIds.value.length) return ElMessage.warning('请选择记录'); jhlbValue.value = dicts.categories[0]; jhlbDialog.value = true }
async function submitBatchJhlb() {
  const r = await batchSummaryJhlb(selectedIds.value, jhlbValue.value)
  if (!r.ok) return ElMessage.warning(r.message)
  ElMessage.success(r.message); jhlbDialog.value = false; load()
}
const xlbDialog = ref(false); const xlbValue = ref('生产类')
function openBatchXlb() { if (!selectedIds.value.length) return ElMessage.warning('请选择记录'); xlbValue.value = dicts.leibie[0]; xlbDialog.value = true }
async function submitBatchXlb() {
  const r = await batchSummaryLeibie(selectedIds.value, xlbValue.value)
  if (!r.ok) return ElMessage.warning(r.message)
  ElMessage.success(r.message); xlbDialog.value = false; load()
}

// ===== 编序号 =====
const renumberDialog = ref(false)
const renumberInfo = reactive({ count: 0, allFilled: false })
const skipBenbu = ref(false)
async function openRenumber() {
  const info = await checkRenumber()
  Object.assign(renumberInfo, info)
  skipBenbu.value = info.allFilled
  renumberDialog.value = true
}
async function submitRenumber() {
  const r = await renumber(selectedIds.value, skipBenbu.value)
  if (!r.ok) return ElMessage.warning(r.message)
  ElMessage.success(r.message); renumberDialog.value = false; load()
}

// ===== 复制正式 =====
const copyDialog = ref(false)
const copyForm = reactive({ nd: null, lb: '更新改造' })
function openCopy() {
  copyForm.nd = filters.nd
  copyForm.lb = filters.jhlb
  copyDialog.value = true
}
async function submitCopy() {
  try {
    await ElMessageBox.confirm(
      `将把 ${copyForm.nd} 年度「${copyForm.lb}」已通过的计划复制到正式计划，正式库中该年度该类别的现有数据会先被删除重建，是否继续？`,
      '复制到正式计划', { type: 'warning' },
    )
  } catch { return }
  const r = await copyToOfficial(copyForm.nd, copyForm.lb)
  if (!r.ok) return ElMessage.warning(r.message)
  ElMessage.success(r.message); copyDialog.value = false
}

// ===== 锁定 =====
async function toggleLock(key, val) {
  if (!dicts.perms.admin) {
    dicts.locks[key] = !val
    return ElMessage.warning('没有锁定开关权限')
  }
  const r = await setPlanLock(key, val)
  if (r.ok) ElMessage.success('开关已更新')
  else dicts.locks[key] = !val
}

// ===== 导入导出 =====
const importFile = ref(null)
const uploading = ref(false)
function onImportChange(file) { importFile.value = file }
async function doImport() {
  if (!importFile.value?.raw) return ElMessage.warning('请选择文件')
  uploading.value = true
  try {
    const r = await importSummary(importFile.value.raw)
    if (!r.ok) return ElMessage.warning(r.message)
    ElMessage.success(r.message); importFile.value = null; load()
  } finally { uploading.value = false }
}
async function doExport() { await exportSummary(buildParams(false)); ElMessage.success('已导出') }
async function doExportPage() {
  if (!selectedIds.value.length) return ElMessage.warning('请选择记录')
  await exportSummaryPage(selectedIds.value, filters.jhlb); ElMessage.success('已导出选中记录')
}

// ===== 变更记录 =====
const logDrawer = ref(false); const logRows = ref([]); const logTitle = ref('')
async function openLogs(row) {
  const data = await getSummaryLogs(row.ID || row.id)
  logRows.value = data.rows
  logTitle.value = `变更记录 · ${row.daibanname || row.ID}`
  logDrawer.value = true
}

onMounted(async () => {
  const d = await getSummaryDicts()
  Object.assign(dicts, d)
  filters.nd = d.default_year
  load()
})
</script>

<template>
  <div class="plan-page">
    <el-card shadow="never" class="top-card">
      <div class="title-row">
        <div class="title">{{ filters.nd }}年度售水事业部计划汇总表</div>
        <div class="stats">总计金额：<b>{{ money(tj) }}</b> 万元　中期调整数：<b>{{ money(tjtz) }}</b> 万元</div>
        <div v-if="dicts.perms.admin" class="lock-row">
          <el-switch v-model="dicts.locks.apply" inline-prompt active-text="锁定申报" inactive-text="申报开"
            @change="(v) => toggleLock('apply', v)" />
          <el-switch v-model="dicts.locks.summary" inline-prompt active-text="锁定通过" inactive-text="通过开"
            @change="(v) => toggleLock('summary', v)" />
        </div>
      </div>
      <div class="status-row">
        <el-button size="small" :type="filters.zt === '' ? 'primary' : 'default'" plain
          @click="filters.zt = ''; search()">不限</el-button>
        <el-button v-for="s in dicts.statuses" :key="s.value" size="small"
          :type="filters.zt === s.value ? s.type : 'default'" :plain="filters.zt !== s.value"
          @click="switchStatus(s.value)">{{ s.label }}</el-button>
        <el-checkbox v-model="filters.px" @change="search">按序号排序</el-checkbox>
      </div>
      <div class="cat-row">
        <el-button v-for="c in dicts.categories" :key="c" size="small"
          :type="filters.jhlb === c ? 'primary' : 'default'" plain
          @click="filters.jhlb = c; search()">{{ catLabel(c) }}</el-button>
      </div>
      <el-form inline class="filter-form">
        <el-form-item label="关键字">
          <el-input v-model="filters.mohu" clearable style="width: 190px" @keyup.enter="search" />
        </el-form-item>
        <el-form-item label="年度">
          <el-select v-model="filters.nd" style="width: 100px" @change="search">
            <el-option v-for="y in dicts.years" :key="y" :label="y" :value="y" />
          </el-select>
        </el-form-item>
        <el-form-item label="部门">
          <el-select v-model="filters.bumenid" clearable filterable style="width: 140px" @change="search">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="专管员">
          <el-select v-model="filters.zgy" clearable filterable style="width: 130px" @change="search">
            <el-option v-for="z in dicts.zgys" :key="z" :label="z" :value="z" />
          </el-select>
        </el-form-item>
        <el-form-item label="主办">
          <el-select v-model="filters.zb" clearable filterable style="width: 150px" @change="search">
            <el-option v-for="d in dicts.hosts" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <div class="toolbar">
      <el-button size="small" type="primary" @click="openAdd">添加计划</el-button>
      <el-button size="small" @click="openEdit(null)">编辑</el-button>
      <el-button size="small" type="success" @click="doApprove">通过计划</el-button>
      <el-button size="small" type="danger" plain @click="doReturnBumen">回退营业所</el-button>
      <el-button size="small" type="warning" plain @click="doReturnZgy">回退专管员</el-button>
      <el-button size="small" @click="doRevert">收回通过</el-button>
      <el-button size="small" type="danger" @click="doDelete">删除</el-button>
      <el-button size="small" @click="openBatchZb">更改主办</el-button>
      <el-button size="small" @click="openBatchJhlb">更改计划类别</el-button>
      <el-button size="small" @click="openBatchXlb">批量改小类</el-button>
      <el-button size="small" @click="openRenumber">编序号</el-button>
      <el-button v-if="dicts.perms.admin" size="small" @click="openCopy">复制到正式计划</el-button>
      <span class="hint">共 {{ total }} 条 · 双击行编辑</span>
    </div>
    <div class="toolbar">
      <el-upload :auto-upload="false" :limit="1" :show-file-list="true" :on-change="onImportChange"
        accept=".xls,.xlsx" class="inline-upload">
        <el-button size="small">选择计划文件</el-button>
      </el-upload>
      <el-button size="small" :loading="uploading" @click="doImport">上传导入</el-button>
      <el-button size="small" @click="downloadSummaryTemplate">下载模板</el-button>
      <el-button size="small" @click="doExport">导出</el-button>
      <el-button size="small" @click="doExportPage">导出当前页</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe size="small" row-key="ID"
      height="calc(100vh - 420px)" @selection-change="onSelectionChange" @row-dblclick="openEdit">
      <el-table-column type="selection" width="42" fixed />
      <el-table-column label="历史" width="60" fixed>
        <template #default="{ row }">
          <el-button link type="primary" @click.stop="openLogs(row)">查看</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="xuhao" label="计划号" width="80" />
      <el-table-column prop="ssbm" label="所属部门" width="110" show-overflow-tooltip />
      <el-table-column prop="leibie" label="小类别" width="80" />
      <el-table-column prop="daibanname" label="项目名称" min-width="220" show-overflow-tooltip />
      <el-table-column prop="bz" label="项目说明" min-width="300" show-overflow-tooltip>
        <template #default="{ row }"><span class="bz-cell">{{ row.bz }}</span></template>
      </el-table-column>
      <el-table-column label="计划总投资" width="100" align="right">
        <template #default="{ row }">{{ money(row.jine) }}</template>
      </el-table-column>
      <el-table-column label="本年计划投资" width="110" align="right">
        <template #default="{ row }">{{ money(row.zongtouzi) }}</template>
      </el-table-column>
      <el-table-column label="年初金额(万)" width="110" align="right">
        <template #default="{ row }">{{ money(row.startjine) }}</template>
      </el-table-column>
      <el-table-column label="调增/调减" width="100">
        <template #default="{ row }">
          <span v-if="tzInfo(row)" :style="{ color: tzInfo(row).color, fontWeight: 600 }">{{ tzInfo(row).text }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="zb" label="主办" width="110" show-overflow-tooltip />
      <el-table-column prop="fzr" label="负责人" width="80" />
      <el-table-column prop="username" label="专管员" width="90" />
      <el-table-column prop="pizhu" label="批注" width="150" show-overflow-tooltip />
      <el-table-column prop="kgny" label="开工" width="80" />
      <el-table-column prop="jgny" label="竣工" width="80" />
      <el-table-column prop="xjxl" label="新建/续建" width="90" />
      <el-table-column prop="opname" label="上报员" width="90" />
      <el-table-column prop="dbtimep" label="最后操作日期" width="145" />
      <el-table-column prop="lastop" label="最后操作" width="90" />
      <el-table-column prop="nxuhao" label="排序号" width="75" />
      <el-table-column label="状态" width="110">
        <template #default="{ row }"><el-tag size="small" :type="statusType(row.zt)">{{ statusText(row.zt) }}</el-tag></template>
      </el-table-column>
      <el-table-column prop="niandu" label="计划年" width="75" />
      <el-table-column prop="jhlb" label="计划类别" width="95" />
      <el-table-column prop="ID" label="流水号" width="75" />
    </el-table>

    <div v-if="footer.length" class="footer-bar">
      <span>{{ footer[0].bz }}</span>
      <span>金额：<b>{{ money(footer[0].jine) }}</b></span>
      <span>本年计划投资：<b>{{ money(footer[0].zongtouzi) }}</b></span>
      <span>年初金额：<b>{{ money(footer[0].startjine) }}</b></span>
      <span>调增/调减：<b>{{ money(footer[0].tzty) }}</b></span>
      <span>{{ footer[0].pizhu }}</span>
    </div>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[30, 400, 1200]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>

    <PlanFormDialog v-model="formOpen" :initial="formItem" :dicts="dicts" mode="summary"
      :editing="formEditing" @save="onSave" @return="onReturnFromForm" />

    <SmsConfirmDialog v-model="confirmState.visible" :title="confirmState.title"
      :message="confirmState.message" :sms-label="confirmState.smsLabel"
      :show-comment="confirmState.showComment" :type="confirmState.type" @confirm="onConfirm" />

    <el-dialog v-model="zbDialog" title="更改主办部门" width="380px">
      <el-select v-model="zbValue" filterable style="width: 100%" placeholder="选择主办部门">
        <el-option v-for="d in dicts.hosts" :key="d.id" :label="d.name" :value="d.id" />
      </el-select>
      <template #footer>
        <el-button @click="zbDialog = false">取消</el-button>
        <el-button type="primary" @click="submitBatchZb">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="jhlbDialog" title="更改计划类别" width="380px">
      <el-select v-model="jhlbValue" style="width: 100%">
        <el-option v-for="c in dicts.categories" :key="c" :label="c" :value="c" />
      </el-select>
      <template #footer>
        <el-button @click="jhlbDialog = false">取消</el-button>
        <el-button type="primary" @click="submitBatchJhlb">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="xlbDialog" title="批量更改小类别" width="380px">
      <el-select v-model="xlbValue" style="width: 100%">
        <el-option v-for="l in dicts.leibie" :key="l" :label="l" :value="l" />
      </el-select>
      <template #footer>
        <el-button @click="xlbDialog = false">取消</el-button>
        <el-button type="primary" @click="submitBatchXlb">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="renumberDialog" title="编序号" width="480px">
      <el-alert type="info" :closable="false" show-icon class="mb10"
        title="将对当前年度「售水通过」的计划重新编号，是否继续？" />
      <p class="renumber-tip">
        售水本部大修理计划共 <b>{{ renumberInfo.count }}</b> 条，
        {{ renumberInfo.allFilled ? '已全部编号' : '存在未编号记录' }}
      </p>
      <el-checkbox v-model="skipBenbu">跳过售水本部大修理计划</el-checkbox>
      <template #footer>
        <el-button @click="renumberDialog = false">取消</el-button>
        <el-button type="primary" @click="submitRenumber">开始编号</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="copyDialog" title="复制到正式计划" width="420px">
      <el-form label-width="80px">
        <el-form-item label="年度">
          <el-select v-model="copyForm.nd" style="width: 100%">
            <el-option v-for="y in dicts.years" :key="y" :label="y" :value="y" />
          </el-select>
        </el-form-item>
        <el-form-item label="类别">
          <el-select v-model="copyForm.lb" style="width: 100%">
            <el-option v-for="c in dicts.categories" :key="c" :label="c" :value="c" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="copyDialog = false">取消</el-button>
        <el-button type="primary" @click="submitCopy">复制</el-button>
      </template>
    </el-dialog>

    <el-drawer v-model="logDrawer" :title="logTitle" size="520px">
      <el-empty v-if="!logRows.length" description="暂无变更记录" />
      <el-timeline v-else>
        <el-timeline-item v-for="(l, i) in logRows" :key="i" :timestamp="l.time" placement="top">
          <div class="log-field">{{ l.field_name }}</div>
          <div class="log-line"><span class="old">{{ l.old_value || '（空）' }}</span> → <span class="new">{{ l.new_value || '（空）' }}</span></div>
          <div class="log-user">操作人：{{ l.update_user }}</div>
        </el-timeline-item>
      </el-timeline>
    </el-drawer>
  </div>
</template>

<style scoped>
.plan-page { display: flex; flex-direction: column; gap: 8px; }
.top-card :deep(.el-card__body) { padding: 10px 14px; }
.title-row { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.title { font-size: 16px; font-weight: 700; color: #1c1e54; }
.stats { font-size: 13px; color: #385f8a; }
.lock-row { display: flex; gap: 12px; align-items: center; }
.status-row, .cat-row { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 8px; }
.filter-form { margin-top: 8px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 10px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.inline-upload { display: inline-block; }
.hint { margin-left: auto; color: #909399; font-size: 12px; }
.footer-bar { display: flex; flex-wrap: wrap; gap: 16px; padding: 6px 10px; background: #f5f7fa; border-radius: 4px; font-size: 13px; }
.pager { display: flex; justify-content: flex-end; }
.bz-cell { display: inline-block; background: rgba(28, 30, 84, 0.06); border: 1px solid rgba(164, 180, 201, 0.35); border-radius: 6px; padding: 2px 6px; text-indent: 1em; line-height: 1.5; }
.log-field { font-weight: 600; color: #1c1e54; }
.log-line { font-size: 13px; margin: 3px 0; }
.log-line .old { color: #c0392b; text-decoration: line-through; }
.log-line .new { color: #1e7e34; }
.log-user { color: #909399; font-size: 12px; }
.renumber-tip { margin: 10px 0; }
.mb10 { margin-bottom: 10px; }
</style>
