<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createApply, deleteApply, downloadApplyTemplate, exportApply, exportReported,
  getApplyDetail, getApplyDicts, getApplyItem, importApply, listApply, listReported,
  submitApply, updateApply,
} from '@/api/plan'
import SmsConfirmDialog from './SmsConfirmDialog.vue'
import { CATEGORIES, MIDDLE_CATEGORIES, money, statusText, statusType, tzInfo } from './common'

const dicts = reactive({
  years: [], default_year: null, departments: [], all_departments: [], zgys: [],
  categories: CATEGORIES, default_bmid: null, locked: false,
  perms: { manage: true, summary: false, readonly: false },
})
const mode = ref('unreported') // unreported | reported | water
const filters = reactive({ nd: null, jhlb: '更新改造', mohu: '', bmid: null })
const rows = ref([])
const total = ref(0)
const tj = ref(0)
const tjtz = ref(0)
const page = ref(1)
const size = ref(30)
const loading = ref(false)
const selection = ref([])

const selectedIds = computed(() => selection.value.map((r) => r.ID))
const readonly = computed(() => dicts.perms.readonly || mode.value === 'water')

function buildParams(withPage = true) {
  const p = {
    nd: filters.nd, jhlb: filters.jhlb, mohu: filters.mohu,
    bmid: filters.bmid || undefined,
  }
  if (withPage) { p.page = page.value; p.size = size.value }
  return p
}

async function load() {
  loading.value = true
  try {
    let data
    if (mode.value === 'water') {
      data = await listReported(buildParams())
    } else {
      data = await listApply({ ...buildParams(), ck: mode.value === 'reported' })
    }
    rows.value = data.rows
    total.value = data.total
    tj.value = data.tj
    tjtz.value = data.tjtz
    if (data.locked !== undefined) dicts.locked = data.locked
  } finally {
    loading.value = false
  }
}

function search() { page.value = 1; load() }
function switchMode(m) { mode.value = m; selection.value = []; page.value = 1; load() }
function resetFilters() {
  Object.assign(filters, { nd: dicts.default_year, jhlb: '更新改造', mohu: '', bmid: null })
  search()
}
function onSelectionChange(val) { selection.value = val }
function clearSelection() { selection.value = [] }

function rowClass({ row }) {
  if (row.zt === '删除' || row.zt === '已回退') return 'row-muted'
  if (row.zt === '售水通过') return 'row-approved'
  return ''
}

// ===== 添加 / 编辑 =====
const formOpen = ref(false)
const formEditing = ref(false)
const editId = ref(null)
const form = reactive({
  bmid: null, jhlb: '更新改造', zgy: '', faqiname: '', bz: '', jine: null,
  startjine: null, zongtouzi: null, kgny: '', jgny: '', xjxl: '', pizhu: '',
})
const isGxgz = computed(() => form.jhlb === '更新改造')
const isMid = computed(() => MIDDLE_CATEGORIES.includes(form.jhlb))
const tz = computed(() => tzInfo({ jine: form.jine, startjine: form.startjine }))

function openAdd() {
  Object.assign(form, {
    bmid: dicts.default_bmid || dicts.all_departments?.[0]?.id || null,
    jhlb: filters.jhlb || '更新改造', zgy: '', faqiname: '', bz: '', jine: null,
    startjine: null, zongtouzi: null, kgny: '', jgny: '', xjxl: '', pizhu: '',
  })
  formEditing.value = false
  editId.value = null
  formOpen.value = true
}

async function openEdit(row) {
  if (!row) {
    if (selection.value.length !== 1) return ElMessage.warning('请选择一条记录')
    row = selection.value[0]
  }
  if (row.zt === '售水专管审批') return ElMessage.warning('已提交售水审核，不能修改')
  const data = await getApplyItem(row.ID)
  Object.assign(form, {
    bmid: data.bmid ?? dicts.default_bmid, jhlb: data.jhlb || '更新改造',
    zgy: data.zgy || '', faqiname: data.faqiname || '', bz: data.bz || '',
    jine: data.jine ?? null, startjine: data.startjine ?? null,
    zongtouzi: data.zongtouzi ?? null, kgny: data.kgny || '', jgny: data.jgny || '',
    xjxl: data.xjxl || '', pizhu: data.pizhu || '',
  })
  formEditing.value = true
  editId.value = data.id
  formOpen.value = true
}

async function saveForm() {
  if (!form.zgy) return ElMessage.warning('请选择专管员')
  if (!form.faqiname) return ElMessage.warning('请输入项目名称')
  if (form.jine === null || form.jine === undefined) return ElMessage.warning('请输入计划总投资')
  const payload = { ...form, niandu: filters.nd }
  let r
  if (formEditing.value) r = await updateApply(editId.value, payload)
  else r = await createApply(payload)
  if (!r.ok) return ElMessage.warning(r.message)
  ElMessage.success(r.message || '保存成功')
  formOpen.value = false
  load()
}

async function doDelete() {
  if (!selectedIds.value.length) return ElMessage.warning('请选择记录')
  try { await ElMessageBox.confirm('确定要删除选中的计划吗？', '删除', { type: 'warning' }) } catch { return }
  const r = await deleteApply(selectedIds.value)
  if (!r.ok) return ElMessage.warning(r.message)
  ElMessage.success(r.message); load()
}

const smsConfirmVisible = ref(false)
function doSubmit() {
  if (!selectedIds.value.length) return ElMessage.warning('请选择要提交的计划')
  if (dicts.locked) return ElMessage.warning('售水计划提交已锁定，现无法提交计划')
  smsConfirmVisible.value = true
}
async function onConfirmSubmit({ sms }) {
  const r = await submitApply(selectedIds.value, sms)
  if (!r.ok) return ElMessage.warning(r.message)
  ElMessage.success(r.message); load()
}

// ===== 明细抽屉 =====
const detailDrawer = ref(false)
const detail = ref(null)
const detailId = ref('')
async function openDetail(row) {
  const data = await getApplyDetail(row.ID, row.unlinked ? 1 : 0)
  detail.value = data
  detailId.value = `计划明细记录 · ${row.faqiname || row.ID}`
  detailDrawer.value = true
}

// ===== 导入导出 =====
const importFile = ref(null)
const uploading = ref(false)
function onImportChange(file) { importFile.value = file }
async function doImport() {
  if (!importFile.value?.raw) return ElMessage.warning('请选择文件')
  uploading.value = true
  try {
    const r = await importApply(importFile.value.raw)
    if (!r.ok) return ElMessage.warning(r.message)
    ElMessage.success(r.message); importFile.value = null; load()
  } finally { uploading.value = false }
}
async function doExport() {
  if (mode.value === 'water') await exportReported(buildParams(false))
  else await exportApply(buildParams(false))
  ElMessage.success('已导出')
}

onMounted(async () => {
  const d = await getApplyDicts()
  Object.assign(dicts, d)
  filters.nd = d.default_year
  load()
})
</script>

<template>
  <div class="plan-page">
    <el-card shadow="never" class="top-card">
      <div class="title-row">
        <div class="title">
          {{ filters.nd }}年度{{ dicts.perms.summary ? (filters.bmid ? dicts.all_departments.find(d => d.id === filters.bmid)?.name : '全部部门') : (dicts.departments[0]?.name || '') }}计划申报明细表
          <span v-if="mode === 'water'" class="water-tag">售水填报记录（只读）</span>
        </div>
        <div class="stats">总计金额：<b>{{ money(tj) }}</b> 万元　中期调整数：<b>{{ money(tjtz) }}</b> 万元</div>
        <el-tag :type="dicts.locked ? 'danger' : 'success'" size="small">
          {{ dicts.locked ? '售水计划提交已锁定' : '现可提交计划' }}
        </el-tag>
      </div>
      <div class="mode-row">
        <el-radio-group v-model="mode" @change="switchMode">
          <el-radio-button label="unreported">未报售水计划</el-radio-button>
          <el-radio-button label="reported">已报售水计划</el-radio-button>
          <el-radio-button label="water">售水填报记录</el-radio-button>
        </el-radio-group>
      </div>
      <div class="cat-row">
        <el-button v-for="c in dicts.categories" :key="c" size="small"
          :type="filters.jhlb === c ? 'primary' : 'default'" plain
          @click="filters.jhlb = c; search()">{{ c }}</el-button>
      </div>
      <el-form inline class="filter-form">
        <el-form-item label="关键字">
          <el-input v-model="filters.mohu" clearable style="width: 200px" @keyup.enter="search" />
        </el-form-item>
        <el-form-item label="年度">
          <el-select v-model="filters.nd" style="width: 100px" @change="search">
            <el-option v-for="y in dicts.years" :key="y" :label="y" :value="y" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="dicts.perms.summary" label="部门">
          <el-select v-model="filters.bmid" clearable filterable style="width: 160px" @change="search">
            <el-option v-for="d in dicts.all_departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <div class="toolbar">
      <template v-if="mode !== 'water' && !dicts.perms.readonly">
        <el-button size="small" type="primary" @click="openAdd">添加计划</el-button>
        <el-button size="small" @click="openEdit(null)">编辑</el-button>
        <el-button size="small" type="danger" @click="doDelete">删除</el-button>
        <el-button size="small" type="success" :disabled="dicts.locked" @click="doSubmit">提交售水</el-button>
        <el-button size="small" @click="clearSelection">取消所有勾选</el-button>
      </template>
      <template v-if="mode !== 'water' && !dicts.perms.readonly">
        <el-upload :auto-upload="false" :limit="1" :on-change="onImportChange" accept=".xls,.xlsx"
          class="inline-upload">
          <el-button size="small">选择更新改造计划</el-button>
        </el-upload>
        <el-button size="small" :loading="uploading" @click="doImport">上传导入</el-button>
        <el-button size="small" @click="downloadApplyTemplate">下载模板</el-button>
      </template>
      <el-button size="small" @click="doExport">{{ mode === 'water' ? '导出填报记录' : '导出计划记录' }}</el-button>
      <span class="hint">共 {{ total }} 条 · 双击行编辑 · 点击「售水处理」查看明细</span>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe size="small" row-key="ID"
      height="calc(100vh - 370px)" :row-class-name="rowClass"
      @selection-change="onSelectionChange" @row-dblclick="(row) => !readonly && openEdit(row)">
      <el-table-column v-if="!dicts.perms.readonly && mode !== 'water'" type="selection" width="42" fixed />
      <el-table-column label="售水处理" width="80" fixed>
        <template #default="{ row }">
          <el-button link type="primary" @click.stop="openDetail(row)">查看</el-button>
        </template>
      </el-table-column>
      <el-table-column v-if="mode === 'water'" prop="xuhao" label="计划号" width="80" />
      <el-table-column prop="faqiname" label="项目名称" min-width="220" show-overflow-tooltip />
      <el-table-column prop="bz" label="项目说明" min-width="300" show-overflow-tooltip>
        <template #default="{ row }"><span class="bz-cell">{{ row.bz }}</span></template>
      </el-table-column>
      <el-table-column label="计划总投资" width="100" align="right">
        <template #default="{ row }">{{ money(row.jine) }}</template>
      </el-table-column>
      <el-table-column label="年初金额(万)" width="110" align="right">
        <template #default="{ row }">{{ money(row.startjine) }}</template>
      </el-table-column>
      <el-table-column label="调增/调减" width="100">
        <template #default="{ row }">
          <span v-if="tzInfo(row)" :style="{ color: tzInfo(row).color, fontWeight: 600 }">{{ tzInfo(row).text }}</span>
        </template>
      </el-table-column>
      <el-table-column v-if="mode === 'water'" prop="zb" label="主办单位" width="110" show-overflow-tooltip />
      <el-table-column v-if="mode === 'water'" prop="fzr" label="负责人" width="80" />
      <el-table-column v-if="mode !== 'water'" prop="pizhu" label="售水批注" width="150" show-overflow-tooltip />
      <el-table-column prop="niandu" label="年度" width="70" />
      <el-table-column prop="zgy" label="专管员" width="90" />
      <el-table-column prop="op" label="操作员" width="90" />
      <el-table-column label="状态" width="100">
        <template #default="{ row }"><el-tag size="small" :type="statusType(row.zt)">{{ statusText(row.zt) }}</el-tag></template>
      </el-table-column>
      <el-table-column v-if="mode !== 'water'" label="售水状态" width="110">
        <template #default="{ row }">
          <el-tag v-if="row.szzt" size="small" :type="statusType(row.szzt)">{{ statusText(row.szzt) }}</el-tag>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column prop="jhlb" label="计划类别" width="95" />
      <el-table-column prop="bm" label="所属部门" width="110" show-overflow-tooltip />
      <el-table-column prop="beginTime" label="初始日期" width="145" />
      <el-table-column prop="fqtimep" label="最后操作日期" width="145" />
      <el-table-column prop="lastop" label="最后操作" width="90" />
      <el-table-column label="本年计划投资" width="110" align="right">
        <template #default="{ row }">{{ money(row.zongtouzi) }}</template>
      </el-table-column>
      <el-table-column prop="kgny" label="开工" width="80" />
      <el-table-column prop="jgny" label="竣工" width="80" />
      <el-table-column prop="xjxl" label="新建/续建" width="90" />
      <el-table-column prop="ID" label="编号" width="75" />
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[30, 60, 90]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>

    <!-- 添加/编辑 -->
    <el-dialog v-model="formOpen" :title="formEditing ? '编辑计划' : '添加计划'" width="900px"
      :close-on-click-modal="false">
      <el-form label-width="110px">
        <div class="form-grid">
          <el-form-item label="计划类别" class="span2">
            <el-radio-group v-model="form.jhlb">
              <el-radio-button v-for="c in dicts.categories" :key="c" :label="c">{{ c }}</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-form-item v-if="dicts.perms.summary || !dicts.default_bmid" label="所属部门">
            <el-select v-model="form.bmid" filterable style="width: 100%">
              <el-option v-for="d in (dicts.perms.summary ? dicts.all_departments : dicts.departments)"
                :key="d.id" :label="d.name" :value="d.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="专管员">
            <el-select v-model="form.zgy" filterable allow-create default-first-option
              style="width: 100%" placeholder="选择或输入姓名">
              <el-option v-for="z in dicts.zgys" :key="z" :label="z" :value="z" />
            </el-select>
          </el-form-item>
          <el-form-item label="项目名称" class="span2">
            <el-input v-model="form.faqiname" />
          </el-form-item>
          <el-form-item label="计划总投资(万)">
            <el-input-number v-model="form.jine" :precision="2" :min="0" style="width: 100%" />
          </el-form-item>
          <el-form-item v-if="isGxgz" label="本年计划投资(万)">
            <el-input-number v-model="form.zongtouzi" :precision="2" :min="0" style="width: 100%" />
          </el-form-item>
          <el-form-item v-if="isGxgz" label="开工年月">
            <el-date-picker v-model="form.kgny" type="month" value-format="YYYY-MM" style="width: 100%" />
          </el-form-item>
          <el-form-item v-if="isGxgz" label="竣工年月">
            <el-date-picker v-model="form.jgny" type="month" value-format="YYYY-MM" style="width: 100%" />
          </el-form-item>
          <el-form-item v-if="isGxgz" label="新建/续建">
            <el-select v-model="form.xjxl" clearable style="width: 100%">
              <el-option label="新建" value="新建" />
              <el-option label="续建" value="续建" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="isMid" label="年初金额(万)">
            <el-input-number v-model="form.startjine" :precision="2" :min="0" style="width: 100%" />
          </el-form-item>
          <el-form-item v-if="isMid" label="调增/调减">
            <span :style="{ color: tz?.color || '#999', fontWeight: 600 }">{{ tz?.text || '—' }}</span>
          </el-form-item>
          <el-form-item v-if="formEditing" label="售水批注" class="span2">
            <el-input v-model="form.pizhu" disabled />
          </el-form-item>
          <el-form-item label="项目说明" class="span2">
            <el-input v-model="form.bz" type="textarea" :rows="4" />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="formOpen = false">取消</el-button>
        <el-button type="primary" @click="saveForm">保存</el-button>
      </template>
    </el-dialog>

    <!-- 明细抽屉 -->
    <SmsConfirmDialog v-model="smsConfirmVisible" title="提交售水"
      message="确定要把选中的计划提交给售水专管员吗？" sms-label="专管员"
      confirm-text="确定提交" @confirm="onConfirmSubmit" />

    <el-drawer v-model="detailDrawer" :title="detailId" size="620px">
      <template v-if="detail?.current">
        <div class="detail-card">
          <div class="detail-title">
            <span>{{ detail.current.daibanname }}</span>
            <el-tag size="small" :type="statusType(detail.current.zt)">{{ statusText(detail.current.zt) }}</el-tag>
          </div>
          <div class="detail-money" :class="{ big: (detail.current.jine || 0) >= 5000 }">
            {{ money(detail.current.jine) }} 万元
          </div>
          <div class="detail-bz">{{ detail.current.bz }}</div>
          <el-descriptions :column="2" border size="small">
            <el-descriptions-item label="序号">{{ detail.current.xuhao || '—' }}</el-descriptions-item>
            <el-descriptions-item label="年度">{{ detail.current.niandu }}</el-descriptions-item>
            <el-descriptions-item label="计划类别">{{ detail.current.jhlb }}</el-descriptions-item>
            <el-descriptions-item label="小类别">{{ detail.current.leibie || '—' }}</el-descriptions-item>
            <el-descriptions-item label="所属部门">{{ detail.current.ssbm || '—' }}</el-descriptions-item>
            <el-descriptions-item label="主办部门">{{ detail.current.zb || '—' }}</el-descriptions-item>
            <el-descriptions-item label="专管员">{{ detail.current.zgy || '—' }}</el-descriptions-item>
            <el-descriptions-item label="上报员">{{ detail.current.opname || '—' }}</el-descriptions-item>
            <el-descriptions-item label="负责人">{{ detail.current.fzr || '—' }}</el-descriptions-item>
            <el-descriptions-item label="年初金额">{{ money(detail.current.startjine) }}</el-descriptions-item>
            <el-descriptions-item label="本年计划投资">{{ money(detail.current.zongtouzi) }}</el-descriptions-item>
            <el-descriptions-item label="开工/竣工">{{ detail.current.kgny || '—' }} / {{ detail.current.jgny || '—' }}</el-descriptions-item>
            <el-descriptions-item label="新建/续建">{{ detail.current.xjxl || '—' }}</el-descriptions-item>
            <el-descriptions-item label="批注">{{ detail.current.pizhu || '—' }}</el-descriptions-item>
            <el-descriptions-item label="最后操作时间" :span="2">{{ detail.current.dbtimep }}</el-descriptions-item>
          </el-descriptions>
        </div>
        <div class="detail-section">变更记录（{{ detail.logs?.length || 0 }}）</div>
        <el-empty v-if="!detail.logs?.length" description="暂无变更记录" :image-size="48" />
        <el-timeline v-else>
          <el-timeline-item v-for="(l, i) in detail.logs" :key="i" :timestamp="l.time" placement="top">
            <div class="log-field">{{ l.field_name }}</div>
            <div class="log-line"><span class="old">{{ l.old_value || '（空）' }}</span> → <span class="new">{{ l.new_value || '（空）' }}</span></div>
            <div class="log-user">操作人：{{ l.update_user }}</div>
          </el-timeline-item>
        </el-timeline>
        <template v-if="detail.rows?.length">
          <div class="detail-section">历史快照（{{ detail.rows.length }}）</div>
          <el-collapse>
            <el-collapse-item v-for="(h, i) in detail.rows" :key="i" :title="`${h.dbtimep} · ${h.zt} · ${money(h.jine)} 万元`">
              <div class="history-text">{{ h.daibanname }} —— {{ h.bz }}</div>
              <div class="history-meta">专管员：{{ h.zgy || '—' }} · 所属部门：{{ h.ssbm || '—' }} · 批注：{{ h.pizhu || '—' }}</div>
            </el-collapse-item>
          </el-collapse>
        </template>
      </template>
      <el-empty v-else description="尚无可查看的售水处理记录" />
    </el-drawer>
  </div>
</template>

<style scoped>
.plan-page { display: flex; flex-direction: column; gap: 8px; }
.top-card :deep(.el-card__body) { padding: 10px 14px; }
.title-row { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px; }
.title { font-size: 16px; font-weight: 700; color: #1c1e54; }
.water-tag { margin-left: 8px; font-size: 12px; color: #1e7e34; font-weight: 500; }
.stats { font-size: 13px; color: #385f8a; }
.mode-row { margin-top: 8px; }
.cat-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
.filter-form { margin-top: 8px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 10px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.inline-upload { display: inline-block; }
.hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }
.bz-cell { display: inline-block; background: rgba(28, 30, 84, 0.06); border: 1px solid rgba(164, 180, 201, 0.35); border-radius: 6px; padding: 2px 6px; text-indent: 1em; line-height: 1.5; }
.form-grid { display: grid; grid-template-columns: 1fr 1fr; column-gap: 18px; }
.span2 { grid-column: span 2; }
.detail-card { background: #f8f9fc; border-radius: 8px; padding: 12px; }
.detail-title { display: flex; justify-content: space-between; font-size: 16px; font-weight: 700; color: #1c1e54; }
.detail-money { font-size: 22px; font-weight: 800; color: #1e7e34; margin: 8px 0; }
.detail-money.big { color: #c0392b; }
.detail-bz { background: #fff; border-radius: 6px; padding: 8px 10px; margin-bottom: 10px; color: #444; line-height: 1.6; }
.detail-section { margin: 16px 0 8px; font-weight: 700; color: #1c1e54; }
.history-text { color: #333; line-height: 1.6; }
.history-meta { color: #909399; font-size: 12px; margin-top: 4px; }
.log-field { font-weight: 600; color: #1c1e54; }
.log-line { font-size: 13px; margin: 3px 0; }
.log-line .old { color: #c0392b; text-decoration: line-through; }
.log-line .new { color: #1e7e34; }
.log-user { color: #909399; font-size: 12px; }
:deep(.row-muted) { color: #b0b3b8; }
:deep(.row-approved) { background: #f0f9eb; }
</style>
