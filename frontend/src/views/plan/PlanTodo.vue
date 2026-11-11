<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  batchTodoJhlb, batchTodoLeibie, batchTodoZb, changeTodoStatus, createTodo,
  deleteTodo, exportTodo, exportTodoPage, getTodoDicts, getTodoItem, getTodoLogs,
  listTodo, sendTodoSms, updateTodo,
} from '@/api/plan'
import PlanFormDialog from './PlanFormDialog.vue'
import SmsConfirmDialog from './SmsConfirmDialog.vue'
import { TODO_STATUS, money, statusText, statusType, tzInfo } from './common'

const dicts = reactive({
  years: [], default_year: null, departments: [], hosts: [], zgys: [], categories: [],
  leibie: [], statuses: TODO_STATUS, default_all_zgy: false, perms: { manage: false },
})
const filters = reactive({ nd: null, jhlb: '', bumenid: null, zb: null, zgy: '', mohu: '', zt: '' })
const allZgy = ref(false)
const rows = ref([])
const total = ref(0)
const tj = ref(0)
const tjtz = ref(0)
const counts = ref({})
const page = ref(1)
const size = ref(20)
const loading = ref(false)
const selection = ref([])
let firstLoad = true

const statusTabs = computed(() => dicts.statuses)
const selectedIds = computed(() => selection.value.map((r) => r.ID || r.id))

function catLabel(c) {
  const n = counts.value[c]
  return n ? `${c} (${n})` : c
}

function buildParams(withPage = true) {
  const p = {
    nd: filters.nd, jhlb: filters.jhlb, mohu: filters.mohu,
    bumenid: filters.bumenid || undefined, zb: filters.zb || undefined,
    zgy: filters.zgy || undefined, zt: filters.zt,
    all_zgy: allZgy.value, first_load: firstLoad,
  }
  if (withPage) { p.page = page.value; p.size = size.value }
  return p
}

async function load() {
  loading.value = true
  try {
    const data = await listTodo(buildParams())
    rows.value = data.rows
    total.value = data.total
    tj.value = data.tj
    tjtz.value = data.tjtz
    counts.value = data.counts || {}
    if (firstLoad) {
      firstLoad = false
      if (data.default_zt) filters.zt = data.default_zt
      if (data.nd) filters.nd = data.nd
      if (data.default_zt || data.nd) {
        loading.value = false
        return load()
      }
    }
    if (data.zt) filters.zt = data.zt
  } finally {
    loading.value = false
  }
}

function search() { page.value = 1; firstLoad = false; load() }

function resetFilters() {
  Object.assign(filters, { nd: dicts.default_year, jhlb: '', bumenid: null, zb: null, zgy: '', mohu: '', zt: '专管员落实' })
  allZgy.value = dicts.default_all_zgy
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
  if (['删除', '已回退'].includes(row.zt)) return ElMessage.warning('该状态无法编辑')
  const data = await getTodoItem(row.ID || row.id)
  editId.value = data.id
  formItem.value = data
  dicts.__opname = data.opname
  formEditing.value = true
  formOpen.value = true
}

async function onSave(payload, action) {
  const submit = action === 'submit'
  let r
  if (formEditing.value) {
    r = await updateTodo(editId.value, { ...payload, submit })
  } else {
    r = await createTodo({ ...payload, submit })
  }
  if (!r.ok) return ElMessage.warning(r.message)
  ElMessage.success(r.message || '保存成功')
  formOpen.value = false
  load()
}

// ===== 确认弹窗(短信通知/批注) =====
const confirmState = reactive({
  visible: false, title: '', message: '', smsLabel: '', showComment: false,
})
let confirmHandler = null
function askConfirm(options, handler) {
  Object.assign(confirmState, {
    visible: true, title: '', message: '', smsLabel: '', showComment: false, ...options,
  })
  confirmHandler = handler
}
async function onConfirm({ sms, comment }) {
  const handler = confirmHandler
  confirmHandler = null
  if (handler) await handler(sms, comment)
}

// ===== 批量操作 =====
function doSubmit() {
  if (!selectedIds.value.length) return ElMessage.warning('请选择要提交的计划')
  askConfirm({
    title: '提交汇总', message: '确定要提交到售水待汇总吗？', smsLabel: '计划汇总',
  }, async (sms) => {
    const r = await changeTodoStatus({ ids: selectedIds.value, zt: '售水待汇总', iftel: sms })
    if (!r.ok) return ElMessage.warning(r.message)
    ElMessage.success(r.message)
    load()
  })
}

function doReturn() {
  if (!selectedIds.value.length) return ElMessage.warning('请选择要回退的计划')
  askConfirm({
    title: '回退营业所', message: '确定要回退到营业所吗？',
    smsLabel: '营业所', showComment: true,
  }, async (sms, comment) => {
    const r = await changeTodoStatus({
      ids: selectedIds.value, zt: '已回退', iftel: sms, pizhu: comment,
    })
    if (!r.ok) return ElMessage.warning(r.message)
    ElMessage.success(r.message)
    load()
  })
}

// ===== 发送提醒短信(照旧 jhssdb/SendMsm) =====
const SMS_PRESETS = [
  '我转了计划给您，请及时处理！',
  '您有未提交的计划，请尽快提交！',
  '如有未报的计划，请尽快提交！',
]
const smsDialog = ref(false)
const smsTarget = ref('')
const smsContent = ref(SMS_PRESETS[0])
const smsSending = ref(false)
function openSms(row) {
  if (!row?.username) return ElMessage.warning('该计划没有专管员')
  smsTarget.value = row.username
  smsContent.value = SMS_PRESETS[0]
  smsDialog.value = true
}
async function submitSms() {
  if (!smsContent.value) return ElMessage.warning('请选择短信内容')
  smsSending.value = true
  try {
    const r = await sendTodoSms({ zgy: smsTarget.value, nr: smsContent.value })
    if (!r.ok) return ElMessage.warning(r.message)
    ElMessage.success(r.message)
    smsDialog.value = false
  } finally {
    smsSending.value = false
  }
}

const zbDialog = ref(false)
const zbValue = ref(null)
function openBatchZb() {
  if (!selectedIds.value.length) return ElMessage.warning('请选择记录')
  zbValue.value = null
  zbDialog.value = true
}
async function submitBatchZb() {
  if (!zbValue.value) return ElMessage.warning('请选择主办部门')
  const r = await batchTodoZb(selectedIds.value, zbValue.value)
  if (!r.ok) return ElMessage.warning(r.message)
  ElMessage.success(r.message); zbDialog.value = false; load()
}

const jhlbDialog = ref(false)
const jhlbValue = ref('更新改造')
function openBatchJhlb() {
  if (!selectedIds.value.length) return ElMessage.warning('请选择记录')
  jhlbValue.value = dicts.categories[0]
  jhlbDialog.value = true
}
async function submitBatchJhlb() {
  const r = await batchTodoJhlb(selectedIds.value, jhlbValue.value)
  if (!r.ok) return ElMessage.warning(r.message)
  ElMessage.success(r.message); jhlbDialog.value = false; load()
}

const xlbDialog = ref(false)
const xlbValue = ref('生产类')
function openBatchXlb() {
  if (!selectedIds.value.length) return ElMessage.warning('请选择记录')
  xlbValue.value = dicts.leibie[0]
  xlbDialog.value = true
}
async function submitBatchXlb() {
  const r = await batchTodoLeibie(selectedIds.value, xlbValue.value)
  if (!r.ok) return ElMessage.warning(r.message)
  ElMessage.success(r.message); xlbDialog.value = false; load()
}

async function doDelete() {
  if (!selectedIds.value.length) return ElMessage.warning('请选择记录')
  try { await ElMessageBox.confirm('确定要删除数据吗？', '删除', { type: 'warning' }) } catch { return }
  const r = await deleteTodo(selectedIds.value)
  if (!r.ok) return ElMessage.warning(r.message)
  ElMessage.success(r.message)
  load()
}

// ===== 变更记录 =====
const logDrawer = ref(false)
const logRows = ref([])
const logTitle = ref('')
async function openLogs(row) {
  const data = await getTodoLogs(row.ID || row.id)
  logRows.value = data.rows
  logTitle.value = `变更记录 · ${row.daibanname || row.ID}`
  logDrawer.value = true
}

async function doExport() { await exportTodo(buildParams(false)); ElMessage.success('已导出') }
async function doExportPage() {
  if (!selectedIds.value.length) return ElMessage.warning('请选择记录')
  await exportTodoPage(selectedIds.value, filters.jhlb)
  ElMessage.success('已导出当前页选中记录')
}

onMounted(async () => {
  const d = await getTodoDicts()
  Object.assign(dicts, d)
  filters.nd = d.default_year
  allZgy.value = d.default_all_zgy
  load()
})
</script>

<template>
  <div class="plan-page">
    <el-card shadow="never" class="top-card">
      <!-- 第 1 行：标题 / 汇总 / 所有专管员计划 -->
      <div class="bar">
        <div class="title">{{ filters.nd }}年度售水事业部计划申报明细表</div>
        <div class="stats">总计金额：<b>{{ money(tj) }}</b> 万元　中期调整数：<b>{{ money(tjtz) }}</b> 万元</div>
        <el-checkbox v-model="allZgy" class="all-zgy" @change="search">所有专管员计划</el-checkbox>
      </div>
      <!-- 第 2 行：查询条件 -->
      <div class="bar">
        <div class="grp">
          <el-input v-model="filters.mohu" size="small" clearable placeholder="计划模糊查询" class="w-kw"
            @keyup.enter="search" @clear="search" />
          <el-button size="small" @click="search">查询</el-button>
          <el-button size="small" @click="resetFilters">重置</el-button>
        </div>
        <span class="sep" />
        <div class="field">
          <span class="lbl">年度</span>
          <el-select v-model="filters.nd" size="small" class="w-year" @change="search">
            <el-option v-for="y in dicts.years" :key="y" :label="y" :value="y" />
          </el-select>
        </div>
        <div class="field">
          <span class="lbl">部门</span>
          <el-select v-model="filters.bumenid" size="small" clearable filterable class="w-dept"
            placeholder="全部" @change="search">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </div>
        <div class="field">
          <span class="lbl">主办</span>
          <el-select v-model="filters.zb" size="small" clearable filterable class="w-zb"
            placeholder="全部" @change="search">
            <el-option v-for="d in dicts.hosts" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </div>
        <div class="field">
          <span class="lbl">专管员</span>
          <el-select v-model="filters.zgy" size="small" clearable filterable class="w-zgy"
            placeholder="全部" @change="search">
            <el-option v-for="z in dicts.zgys" :key="z" :label="z" :value="z" />
          </el-select>
        </div>
      </div>
      <!-- 第 3 行：状态 / 计划类别 快捷筛选 -->
      <div class="bar">
        <div class="field">
          <span class="lbl">状态</span>
          <div class="tags">
            <el-button v-for="s in statusTabs" :key="s.value" size="small"
              :type="filters.zt === s.value ? s.type : 'default'"
              :plain="filters.zt !== s.value" @click="switchStatus(s.value)">
              {{ s.label }}
            </el-button>
          </div>
        </div>
        <span class="sep" />
        <div class="field">
          <span class="lbl">类别</span>
          <div class="tags">
            <el-button v-for="c in dicts.categories" :key="c" size="small"
              :type="filters.jhlb === c ? 'primary' : 'default'" :plain="filters.jhlb !== c"
              @click="filters.jhlb = filters.jhlb === c ? '' : c; search()">
              {{ catLabel(c) }}
            </el-button>
          </div>
        </div>
      </div>
    </el-card>

    <div class="toolbar">
      <el-button size="small" type="primary" @click="openAdd">添加计划</el-button>
      <el-button size="small" @click="openEdit(null)">编辑</el-button>
      <el-button size="small" type="success" plain @click="doSubmit">提交汇总</el-button>
      <el-button size="small" type="danger" plain @click="doReturn">回退营业所</el-button>
      <el-button size="small" @click="openBatchZb">更改主办</el-button>
      <el-button size="small" @click="openBatchJhlb">更改计划类别</el-button>
      <el-button size="small" @click="openBatchXlb">批量更改小类别</el-button>
      <el-button size="small" type="danger" @click="doDelete">删除</el-button>
      <el-button size="small" @click="doExport">导出全部</el-button>
      <el-button size="small" @click="doExportPage">导出当前页</el-button>
      <span class="hint">共 {{ total }} 条 · 双击行编辑</span>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe size="small" row-key="ID"
      height="calc(100vh - 320px)" @selection-change="onSelectionChange" @row-dblclick="openEdit">
      <el-table-column type="selection" width="42" fixed />
      <el-table-column label="历史" width="60" fixed>
        <template #default="{ row }">
          <el-button link type="primary" @click.stop="openLogs(row)">查看</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="xuhao" label="计划号" width="80" />
      <el-table-column prop="leibie" label="小类别" width="80" />
      <el-table-column prop="ssbm" label="所属部门" width="110" show-overflow-tooltip />
      <el-table-column prop="daibanname" label="项目名称" min-width="220" />
      <el-table-column prop="bz" label="项目说明" min-width="450">
        <template #default="{ row }"><span class="bz-cell">{{ row.bz }}</span></template>
      </el-table-column>
      <el-table-column label="计划总投资" width="100" align="right">
        <template #default="{ row }">{{ money(row.jine) }}</template>
      </el-table-column>
      <el-table-column label="本年计划投资" width="110" align="right">
        <template #default="{ row }">{{ money(row.zongtouzi) }}</template>
      </el-table-column>
      <el-table-column prop="zb" label="主办" width="110" show-overflow-tooltip />
      <el-table-column prop="fzr" label="负责人" width="80" />
      <el-table-column label="专管员" width="118">
        <template #default="{ row }">
          <span>{{ row.username }}</span>
          <el-button v-if="row.username" link type="primary" size="small"
            style="margin-left: 4px" @click.stop="openSms(row)">短信</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="kgny" label="开工" width="80" />
      <el-table-column prop="jgny" label="竣工" width="80" />
      <el-table-column prop="xjxl" label="新建/续建" width="90" />
      <el-table-column prop="opname" label="上报员" width="90" />
      <el-table-column label="状态" width="110">
        <template #default="{ row }"><el-tag size="small" :type="statusType(row.zt)">{{ statusText(row.zt) }}</el-tag></template>
      </el-table-column>
      <el-table-column label="年初金额(万)" width="110" align="right">
        <template #default="{ row }">{{ money(row.startjine) }}</template>
      </el-table-column>
      <el-table-column label="调增/调减" width="100">
        <template #default="{ row }">
          <span v-if="tzInfo(row)" :style="{ color: tzInfo(row).color, fontWeight: 600 }">{{ tzInfo(row).text }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="lastop" label="最后操作" width="90" />
      <el-table-column prop="pizhu" label="批注" width="150" show-overflow-tooltip />
      <el-table-column prop="dbtimep" label="最后操作日期" width="145" />
      <el-table-column prop="niandu" label="计划年" width="75" />
      <el-table-column prop="jhlb" label="计划类别" width="95" />
      <el-table-column prop="ID" label="流水号" width="75" />
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[20, 100, 200]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>

    <PlanFormDialog v-model="formOpen" :initial="formItem" :dicts="dicts" mode="todo"
      :editing="formEditing" @save="onSave" />

    <SmsConfirmDialog v-model="confirmState.visible" :title="confirmState.title"
      :message="confirmState.message" :sms-label="confirmState.smsLabel"
      :show-comment="confirmState.showComment" @confirm="onConfirm" />

    <el-dialog v-model="smsDialog" title="发送提醒短信" width="420px">
      <p class="sms-to">发送给：{{ smsTarget }}</p>
      <el-select v-model="smsContent" style="width: 100%">
        <el-option v-for="msg in SMS_PRESETS" :key="msg" :label="msg" :value="msg" />
      </el-select>
      <template #footer>
        <el-button @click="smsDialog = false">关闭</el-button>
        <el-button type="primary" :loading="smsSending" @click="submitSms">发送</el-button>
      </template>
    </el-dialog>

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
/* ===== 紧凑三行：标题行 / 查询行 / 状态+类别标签行（参考旧系统 jhssdb 的 north 区）
   统一栅格：控件高 28px、圆角 6px、字号 13px；组内间距 8px、组间距 12px ===== */
.bar { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; min-height: 28px; }
.bar + .bar { margin-top: 8px; }
.grp { display: flex; align-items: center; gap: 8px; }
.field { display: flex; align-items: center; gap: 8px; }
.tags { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.bar :deep(.el-input__wrapper),
.bar :deep(.el-select__wrapper) { min-height: 28px; box-sizing: border-box; border-radius: 6px; }
.bar :deep(.el-input__inner),
.bar :deep(.el-select__wrapper),
.bar :deep(.el-select__placeholder),
.bar :deep(.el-select__selected-item),
.bar :deep(.el-button),
.toolbar :deep(.el-button) { font-size: 13px; }
.bar :deep(.el-button),
.toolbar :deep(.el-button) { height: 28px; min-height: 28px; padding: 0 10px; border-radius: 6px; }
/* Element 相邻按钮默认 margin-left:12px，会与 flex gap 叠加，统一清零由 gap 控制间距 */
.grp :deep(.el-button + .el-button),
.tags :deep(.el-button + .el-button),
.toolbar :deep(.el-button + .el-button) { margin-left: 0; }
.title { font-size: 15px; font-weight: 700; color: #1c1e54; white-space: nowrap; }
.bar .stats { margin-left: auto; }
.stats { font-size: 13px; color: #385f8a; white-space: nowrap; }
.all-zgy { flex-shrink: 0; height: 28px; margin-right: 0; }
.all-zgy :deep(.el-checkbox__label) { font-size: 13px; color: #385f8a; }
.lbl { font-size: 13px; color: #5b6b7f; white-space: nowrap; }
.sep { width: 1px; height: 16px; background: rgba(164, 180, 201, 0.55); flex-shrink: 0; }
.w-kw { width: 200px; }
.w-year { width: 96px; }
.w-dept { width: 132px; }
.w-zb { width: 142px; }
.w-zgy { width: 116px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }
.bz-cell { display: inline-block; background: rgba(28, 30, 84, 0.06); border: 1px solid rgba(164, 180, 201, 0.35); border-radius: 6px; padding: 2px 6px; text-indent: 1em; line-height: 1.5; white-space: normal; word-break: break-word; }
.log-field { font-weight: 600; color: #1c1e54; }
.log-line { font-size: 13px; margin: 3px 0; }
.log-line .old { color: #c0392b; text-decoration: line-through; }
.log-line .new { color: #1e7e34; }
.log-user { color: #909399; font-size: 12px; }
</style>
