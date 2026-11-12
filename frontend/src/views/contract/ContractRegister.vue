<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createAttachmentToken,
  createContract,
  deleteAttachment,
  deleteContract,
  exportContracts,
  getContract,
  getContractDicts,
  getDuixiangOptions,
  listContracts,
  listRegisterYears,
  lockContract,
  unlockContract,
  updateContract,
  uploadContractAttachments,
} from '@/api/contract'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const isSuper = computed(() => !!auth.user?.is_superuser)
const canManage = computed(() => auth.hasPerm('contract:manage'))

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(30)
const selection = ref([])
const filters = reactive({ mohu: '', nd: [] })
const years = ref([])
const dicts = reactive({
  lvxingqingkuang: [], leibie: [], zhaobiaofangshi: [],
  departments: [], my_departments: [], current_year: new Date().getFullYear(),
})

const deptOptions = computed(() =>
  isSuper.value ? dicts.departments : dicts.my_departments
)

function buildParams() {
  return {
    page: page.value,
    size: size.value,
    mohu: filters.mohu,
    nd: filters.nd.join(','),
  }
}

async function load() {
  loading.value = true
  try {
    const data = await listContracts(buildParams())
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

function resetFilters() {
  filters.mohu = ''
  filters.nd = []
  page.value = 1
  load()
}

function onSelectionChange(v) {
  selection.value = v
}

function fmtMoney(v) {
  if (v === null || v === undefined || v === '') return ''
  return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function fmtSize(v) {
  const n = Number(v || 0)
  if (!n) return ''
  if (n >= 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)}M`
  if (n >= 1024) return `${(n / 1024).toFixed(0)}K`
  return `${n}B`
}

async function openAttachment(tp) {
  try {
    const data = await createAttachmentToken(tp.id)
    window.open(data.url, '_blank')
  } catch { /* 错误消息已由拦截器提示 */ }
}

async function toggleLock(row, checked) {
  try {
    if (checked) await lockContract(row.id)
    else await unlockContract(row.id)
    ElMessage.success(checked ? '锁定成功' : '解锁成功')
  } finally {
    load()
  }
}

// ===== 新增 / 编辑 =====
const dialogVisible = ref(false)
const dialogTitle = ref('')
const submitSaving = ref(false)
const dialogTab = ref('reg')
const editingId = ref(null)
const formRef = ref()
const form = reactive({})
const suppliers = ref([])
const existingAttachments = ref([])
const localFiles = ref([])
const fileInput = ref()
const supplierSelection = ref([])
const wjdwManual = ref(false)
const duixiangOptions = ref([])

function blankForm() {
  return {
    niandu: dicts.current_year,
    bumenid: deptOptions.value[0]?.id || null,
    lvxingqingkuang: '合同签约',
    leibie: '',
    name: '',
    biaodi: '',
    nr: '',
    qddate: '',
    duixiang: '',
    jine: null,
    ssdate: '',
    zzdate: '',
    beizhu: '',
    zhaobiaofangshi: '',
    kongzhijia: null,
    sfwjdw: false,
    zt: '待归集',
  }
}

function resetForm() {
  Object.keys(form).forEach((k) => delete form[k])
  Object.assign(form, blankForm())
  suppliers.value = []
  existingAttachments.value = []
  localFiles.value = []
  supplierSelection.value = []
  wjdwManual.value = false
}

const isCollectedEdit = computed(() => !!editingId.value && form.zt === '已归集')
const isZonghe = computed(() => (form.zhaobiaofangshi || '').includes('综合评分法'))

const rules = computed(() => {
  if (isCollectedEdit.value) return {}
  const required = (msg) => [{ required: true, message: msg, trigger: ['blur', 'change'] }]
  return {
    niandu: required('请填写合同年度'),
    name: required('请填写合同名称'),
    biaodi: required('请填写合同标的'),
    nr: required('请填写简要内容'),
    qddate: required('请选择签订时间'),
    duixiang: required('请填写签订对象'),
    jine: required('请填写金额'),
    ssdate: required('请选择实施时间'),
  }
})

watch(
  () => [form.jine, form.zhaobiaofangshi],
  () => {
    if (wjdwManual.value) return
    const n = Number(form.jine)
    form.sfwjdw = !Number.isNaN(n) && form.jine !== null && form.jine !== ''
      && n >= 50000 && n <= 100000
      && !!form.zhaobiaofangshi && form.zhaobiaofangshi !== '直接采购'
  }
)

function onSfwjdwChange() {
  wjdwManual.value = true
}

function queryDuixiang(query, cb) {
  getDuixiangOptions(query || '').then((list) => cb(list.map((v) => ({ value: v }))))
}

async function openAdd() {
  editingId.value = null
  resetForm()
  form.niandu = dicts.current_year
  form.bumenid = deptOptions.value[0]?.id || null
  dialogTitle.value = '添加合同'
  dialogTab.value = 'reg'
  dialogVisible.value = true
  queryDuixiang('', (list) => (duixiangOptions.value = list))
}

async function openEdit() {
  if (selection.value.length !== 1) {
    ElMessage.warning('请选择且仅选择一条要修改的合同')
    return
  }
  const row = selection.value[0]
  const data = await getContract(row.id)
  editingId.value = row.id
  Object.keys(form).forEach((k) => delete form[k])
  Object.assign(form, blankForm(), data)
  form.jine = data.jine
  form.kongzhijia = data.kongzhijia
  suppliers.value = (data.suppliers || []).map((s) => ({ ...s, _key: Math.random() }))
  existingAttachments.value = data.tps || []
  localFiles.value = []
  supplierSelection.value = []
  wjdwManual.value = data.sfwjdw !== null && data.sfwjdw !== undefined
  form.sfwjdw = !!data.sfwjdw
  dialogTitle.value = '编辑合同'
  dialogTab.value = 'reg'
  dialogVisible.value = true
  queryDuixiang('', (list) => (duixiangOptions.value = list))
}

function addSupplier() {
  suppliers.value.push({
    _key: Math.random(), gongyingshang: '', toubiaojia: null, zuizhongjia: null,
    paixu: suppliers.value.length + 1, sfzb: false, swfs: null, jsfs: null, jgfs: null, beizhu: '',
  })
}

function onSupplierSelection(v) {
  supplierSelection.value = v
}

function removeSuppliers() {
  if (!supplierSelection.value.length) {
    ElMessage.warning('请先勾选要删除的供应商行')
    return
  }
  const keys = new Set(supplierSelection.value.map((r) => r._key))
  suppliers.value = suppliers.value.filter((r) => !keys.has(r._key))
  supplierSelection.value = []
}

function rowTotal(row) {
  const vals = [row.swfs, row.jsfs, row.jgfs]
    .filter((v) => v !== null && v !== undefined && v !== '')
    .map(Number)
    .filter((v) => !Number.isNaN(v))
  return vals.length ? Number(vals.reduce((a, b) => a + b, 0).toFixed(2)) : null
}

function toNumber(v) {
  if (v === null || v === undefined || v === '') return null
  const n = Number(v)
  return Number.isNaN(n) ? null : n
}

function supplierPayload() {
  return suppliers.value.map((s) => ({
    gongyingshang: s.gongyingshang || '',
    toubiaojia: toNumber(s.toubiaojia),
    zuizhongjia: toNumber(s.zuizhongjia),
    paixu: toNumber(s.paixu),
    sfzb: !!s.sfzb,
    swfs: toNumber(s.swfs),
    jsfs: toNumber(s.jsfs),
    jgfs: toNumber(s.jgfs),
    zfs: rowTotal(s),
    beizhu: s.beizhu || '',
  }))
}

function pickFiles() {
  fileInput.value?.click()
}

function onFilesPicked(e) {
  const picked = Array.from(e.target.files || [])
  for (const f of picked) {
    if (!f.name.toLowerCase().endsWith('.pdf')) {
      ElMessage.error(`${f.name}: 只允许上传 PDF 文件`)
      continue
    }
    if (f.size > 50 * 1024 * 1024) {
      ElMessage.error(`${f.name}: 文件超过 50MB`)
      continue
    }
    localFiles.value.push({ name: f.name, size: f.size, raw: f })
  }
  e.target.value = ''
}

function removeLocalFile(index) {
  localFiles.value.splice(index, 1)
}

async function removeExistingAttachment(tp) {
  try {
    await ElMessageBox.confirm(`确定删除附件「${tp.oldname || '未命名'}」吗?`, '提示', { type: 'warning' })
  } catch {
    return
  }
  await deleteAttachment(tp.id)
  existingAttachments.value = existingAttachments.value.filter((x) => x.id !== tp.id)
  ElMessage.success('附件已删除')
  load()
}

async function submit() {
  if (submitSaving.value) return  // 防双击重复提交
  try {
    await formRef.value.validate()
  } catch {
    return
  }
  submitSaving.value = true
  try {
    const payload = {
      ...form,
      niandu: Number(form.niandu),
      bumenid: form.bumenid || null,
      jine: toNumber(form.jine),
      kongzhijia: toNumber(form.kongzhijia),
      qddate: form.qddate || null,
      ssdate: form.ssdate || null,
      zzdate: form.zzdate || null,
      suppliers: supplierPayload(),
    }
    let id = editingId.value
    let created = null
    if (id) {
      await updateContract(id, payload)
    } else {
      created = await createContract(payload)
      id = created.id
      editingId.value = id
    }
    if (localFiles.value.length) {
      await uploadContractAttachments(id, localFiles.value.map((f) => f.raw))
    }
    dialogVisible.value = false
    if (created) {
      ElMessage.success(`添加成功!本次合同编号为:${created.allbh}`)
    } else {
      ElMessage.success('已修改记录')
    }
    load()
    refreshYears()
  } finally {
    submitSaving.value = false
  }
}

async function removeContract() {
  if (selection.value.length !== 1) {
    ElMessage.warning('请选择且仅选择一条要删除的合同')
    return
  }
  const row = selection.value[0]
  if (row.zt !== '待归集') {
    ElMessage.error('已归集或者已锁定,无法删除')
    return
  }
  try {
    await ElMessageBox.confirm('确定要删除该合同及其附件吗?', '提示', { type: 'warning' })
  } catch {
    return
  }
  await deleteContract(row.id)
  ElMessage.success('已删除')
  load()
  refreshYears()
}

async function refreshYears() {
  years.value = await listRegisterYears()
}

async function doExport() {
  await exportContracts({
    mohu: filters.mohu,
    nd: filters.nd.join(','),
  })
}

async function uploadPdfForRow() {
  if (selection.value.length !== 1) {
    ElMessage.warning('请选择且仅选择一条需要上传 PDF 的合同')
    return
  }
  const row = selection.value[0]
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'application/pdf'
  input.multiple = true
  input.onchange = async () => {
    const files = Array.from(input.files || [])
    if (!files.length) return
    const bad = files.find((f) => !f.name.toLowerCase().endsWith('.pdf') || f.size > 50 * 1024 * 1024)
    if (bad) {
      ElMessage.error('只允许上传小于 50MB 的 PDF 文件')
      return
    }
    await uploadContractAttachments(row.id, files)
    ElMessage.success('上传成功')
    load()
  }
  input.click()
}

onMounted(async () => {
  Object.assign(dicts, await getContractDicts())
  await refreshYears()
  load()
})
</script>

<template>
  <div class="page">
    <el-card shadow="never" class="filter-card">
      <div class="banner">售水内控合同登记表</div>
      <div class="filters">
        <el-input
          v-model="filters.mohu"
          placeholder="输入合同模糊查询"
          clearable
          style="width: 260px"
          @keyup.enter="search"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select
          v-model="filters.nd"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="选择年度(可多选)"
          style="width: 220px"
        >
          <el-option v-for="y in years" :key="y" :label="y" :value="y" />
        </el-select>
        <el-button @click="search"><el-icon><Search /></el-icon>查询</el-button>
        <el-button @click="resetFilters"><el-icon><Refresh /></el-icon>重置</el-button>
        <el-button v-if="canManage" type="primary" @click="openAdd"><el-icon><Plus /></el-icon>添加</el-button>
        <el-button v-if="canManage" @click="openEdit">编辑</el-button>
        <el-button v-if="canManage" type="danger" plain @click="removeContract">删除</el-button>
        <el-button v-if="canManage" @click="uploadPdfForRow">上传PDF</el-button>
        <el-button @click="doExport"><el-icon><Download /></el-icon>导出记录</el-button>
      </div>
    </el-card>

    <el-card shadow="never" class="table-card">
      <el-table
        v-loading="loading"
        :data="rows"
        border
        stripe
        height="calc(100vh - 300px)"
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="45" fixed="left" />
        <el-table-column label="是否锁定" width="105" align="center">
          <template #default="{ row }">
            <el-switch
              :model-value="row.locked != null"
              :disabled="row.zt !== '已归集' || !canManage"
              active-text="已锁"
              inactive-text="已解锁"
              inline-prompt
              @change="(v) => toggleLock(row, v)"
            />
          </template>
        </el-table-column>
        <el-table-column prop="allbh" label="合同编号" width="130" show-overflow-tooltip />
        <el-table-column prop="name" label="合同名称" min-width="240" show-overflow-tooltip />
        <el-table-column prop="duixiang" label="签订对象" min-width="220" show-overflow-tooltip />
        <el-table-column prop="biaodi" label="合同标的" min-width="200" show-overflow-tooltip />
        <el-table-column label="金额(元)" width="130" align="right">
          <template #default="{ row }">{{ fmtMoney(row.jine) }}</template>
        </el-table-column>
        <el-table-column prop="niandu" label="年度" width="70" align="center" />
        <el-table-column prop="qddate" label="签订日期" width="105" align="center" />
        <el-table-column prop="leibie" label="合同类别" width="110" show-overflow-tooltip />
        <el-table-column prop="zhaobiaofangshi" label="招标方式" width="150" show-overflow-tooltip />
        <el-table-column prop="lvxingqingkuang" label="履行情况" width="100" />
        <el-table-column prop="djdate" label="登记日期" width="155" />
        <el-table-column prop="editdate" label="最后编辑日期" width="155" />
        <el-table-column prop="zt" label="状态" width="85" align="center">
          <template #default="{ row }">
            <el-tag :type="row.zt === '已归集' ? 'success' : 'info'" size="small">{{ row.zt }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="spdate" label="归集日期" width="155" />
        <el-table-column label="附件" width="120">
          <template #default="{ row }">
            <el-button
              v-for="tp in row.tps"
              :key="tp.id"
              link
              type="primary"
              :title="`${tp.oldname || '未命名'} ${fmtSize(tp.fsize)}`"
              @click="openAttachment(tp)"
            >
              <el-icon><Paperclip /></el-icon>
            </el-button>
            <span v-if="!row.tps?.length" class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="sp" label="归集人" width="90" />
        <el-table-column prop="bm" label="部门" width="110" show-overflow-tooltip />
        <el-table-column prop="user" label="提交人" width="90" />
      </el-table>
      <div class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          :page-sizes="[30, 60, 120]"
          :total="total"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="load"
          @size-change="search"
        />
      </div>
    </el-card>

    <el-dialog v-model="dialogVisible" :title="dialogTitle" width="1040px" top="5vh" destroy-on-close
      class="std-dialog contract-form-dialog">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="110px">
        <el-tabs v-model="dialogTab">
          <el-tab-pane label="合同登记" name="reg">
            <el-row :gutter="20">
              <el-col :span="12">
                <el-form-item label="合同年度" prop="niandu">
                  <el-input-number v-model="form.niandu" :min="1900" :max="2100" :disabled="!!editingId" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item v-if="isSuper || dicts.my_departments.length > 1" label="所属部门">
                  <el-select v-model="form.bumenid" :disabled="!!editingId" style="width: 100%">
                    <el-option v-for="d in deptOptions" :key="d.id" :label="d.name" :value="d.id" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="履行情况">
                  <el-select v-model="form.lvxingqingkuang" style="width: 100%">
                    <el-option v-for="v in dicts.lvxingqingkuang" :key="v" :label="v" :value="v" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="12">
                <el-form-item label="合同类别">
                  <el-select v-model="form.leibie" :disabled="isCollectedEdit" style="width: 100%">
                    <el-option v-for="v in dicts.leibie" :key="v" :label="v" :value="v" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="24">
                <el-form-item label="合同名称" prop="name">
                  <el-input v-model="form.name" maxlength="500" show-word-limit :disabled="isCollectedEdit" />
                </el-form-item>
              </el-col>
              <el-col :span="24">
                <el-form-item label="合同标的" prop="biaodi">
                  <el-input v-model="form.biaodi" maxlength="1000" show-word-limit :disabled="isCollectedEdit" />
                </el-form-item>
              </el-col>
              <el-col :span="24">
                <el-form-item label="简要内容" prop="nr">
                  <el-input v-model="form.nr" type="textarea" :rows="3" maxlength="2000" show-word-limit :disabled="isCollectedEdit" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="签订时间" prop="qddate">
                  <el-date-picker v-model="form.qddate" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="16">
                <el-form-item label="签订对象" prop="duixiang">
                  <el-autocomplete
                    v-model="form.duixiang"
                    :fetch-suggestions="queryDuixiang"
                    :disabled="isCollectedEdit"
                    placeholder="输入可联想历史签订对象"
                    style="width: 100%"
                  />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="金额(元)" prop="jine">
                  <el-input-number v-model="form.jine" :precision="2" :min="0" :controls="false" :disabled="isCollectedEdit" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="实施时间" prop="ssdate">
                  <el-date-picker v-model="form.ssdate" type="date" value-format="YYYY-MM-DD" :disabled="isCollectedEdit" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="8">
                <el-form-item label="终止时间">
                  <el-date-picker v-model="form.zzdate" type="date" value-format="YYYY-MM-DD" clearable style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="24">
                <el-form-item label="备注描述">
                  <el-input v-model="form.beizhu" type="textarea" :rows="2" maxlength="1000" show-word-limit :disabled="isCollectedEdit" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-alert
              v-if="isCollectedEdit"
              type="warning"
              :closable="false"
              show-icon
              title="该合同已归集:只能修改履行情况、签订时间、终止时间和招标信息"
            />
          </el-tab-pane>

          <el-tab-pane label="招标信息" name="bid">
            <el-row :gutter="20">
              <el-col :span="10">
                <el-form-item label="招标方式">
                  <el-select v-model="form.zhaobiaofangshi" clearable placeholder="(未填写)" style="width: 100%">
                    <el-option v-for="v in dicts.zhaobiaofangshi" :key="v" :label="v" :value="v" />
                  </el-select>
                </el-form-item>
              </el-col>
              <el-col :span="7">
                <el-form-item label="控制价(元)">
                  <el-input-number v-model="form.kongzhijia" :precision="2" :min="0" :controls="false" style="width: 100%" />
                </el-form-item>
              </el-col>
              <el-col :span="7">
                <el-form-item label="中标价(元)">
                  <div class="mirror">{{ form.jine === null || form.jine === '' ? '—' : fmtMoney(form.jine) }}</div>
                  <div class="muted small">(即合同金额)</div>
                </el-form-item>
              </el-col>
            </el-row>
            <el-checkbox v-model="form.sfwjdw" @change="onSfwjdwChange">
              是否属于单次采购金额5-10万元(含)非直接采购项目
            </el-checkbox>
            <div class="supplier-toolbar">
              <el-button size="small" @click="addSupplier"><el-icon><Plus /></el-icon>新增供应商</el-button>
              <el-button size="small" @click="removeSuppliers">删除选中行</el-button>
            </div>
            <el-table :data="suppliers" border size="small" height="360" @selection-change="onSupplierSelection">
              <el-table-column type="selection" width="42" />
              <el-table-column label="供应商名称" min-width="200">
                <template #default="{ row }"><el-input v-model="row.gongyingshang" /></template>
              </el-table-column>
              <el-table-column label="投标报价(元)" width="120">
                <template #default="{ row }"><el-input-number v-model="row.toubiaojia" :precision="2" :controls="false" style="width: 100%" /></template>
              </el-table-column>
              <el-table-column label="最终出价(元)" width="120">
                <template #default="{ row }"><el-input-number v-model="row.zuizhongjia" :precision="2" :controls="false" style="width: 100%" /></template>
              </el-table-column>
              <el-table-column label="排序" width="80">
                <template #default="{ row }"><el-input-number v-model="row.paixu" :precision="0" :controls="false" style="width: 100%" /></template>
              </el-table-column>
              <el-table-column label="是否中标" width="80" align="center">
                <template #default="{ row }"><el-checkbox v-model="row.sfzb" /></template>
              </el-table-column>
              <template v-if="isZonghe">
                <el-table-column label="商务分" width="90">
                  <template #default="{ row }"><el-input-number v-model="row.swfs" :precision="2" :controls="false" style="width: 100%" /></template>
                </el-table-column>
                <el-table-column label="技术分" width="90">
                  <template #default="{ row }"><el-input-number v-model="row.jsfs" :precision="2" :controls="false" style="width: 100%" /></template>
                </el-table-column>
                <el-table-column label="价格分" width="90">
                  <template #default="{ row }"><el-input-number v-model="row.jgfs" :precision="2" :controls="false" style="width: 100%" /></template>
                </el-table-column>
                <el-table-column label="总分" width="90" align="center">
                  <template #default="{ row }">{{ rowTotal(row) ?? '' }}</template>
                </el-table-column>
              </template>
              <el-table-column label="备注" min-width="140">
                <template #default="{ row }"><el-input v-model="row.beizhu" /></template>
              </el-table-column>
            </el-table>
          </el-tab-pane>

          <el-tab-pane label="合同PDF上传" name="pdf">
            <div class="pdf-actions">
              <el-button @click="pickFiles"><el-icon><Upload /></el-icon>选择 PDF 文件</el-button>
              <input ref="fileInput" type="file" accept="application/pdf" multiple hidden @change="onFilesPicked" />
              <span class="muted">单个文件小于 50MB</span>
            </div>
            <div class="attach-list">
              <div v-for="tp in existingAttachments" :key="tp.id" class="attach-item">
                <el-icon class="pdf-icon"><Document /></el-icon>
                <span class="attach-name" :title="tp.oldname">{{ tp.oldname || '未命名' }}</span>
                <span class="muted">{{ fmtSize(tp.fsize) }}</span>
                <el-button link type="primary" @click="openAttachment(tp)">查看</el-button>
                <el-button v-if="canManage" link type="danger" @click="removeExistingAttachment(tp)">删除</el-button>
              </div>
              <div v-for="(f, i) in localFiles" :key="i" class="attach-item">
                <el-icon class="pdf-icon"><Document /></el-icon>
                <span class="attach-name">{{ f.name }}</span>
                <span class="muted">{{ fmtSize(f.size) }}</span>
                <el-tag type="warning" size="small">待上传</el-tag>
                <el-button link type="danger" @click="removeLocalFile(i)">移除</el-button>
              </div>
              <el-empty v-if="!existingAttachments.length && !localFiles.length" description="暂无附件" :image-size="60" />
            </div>
          </el-tab-pane>
        </el-tabs>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">{{ editingId ? '确定修改' : '确定增加' }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.page { display: flex; flex-direction: column; gap: 12px; }
.banner {
  background: #1c1e54;
  color: #fff;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: 2px;
  text-align: center;
  padding: 12px 0;
  border-radius: 4px;
  margin-bottom: 12px;
}
.filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.table-card :deep(.el-card__body) { padding: 12px; }
.pager { display: flex; justify-content: flex-end; margin-top: 12px; }
.muted { color: #94a3b8; }
.small { font-size: 12px; }
.mirror { font-weight: 600; color: #64748d; line-height: 32px; }
.supplier-toolbar { display: flex; gap: 8px; margin: 10px 0; }
.pdf-actions { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; }
.attach-list { max-height: 420px; overflow: auto; }
.attach-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid #eef2f7;
  border-radius: 6px;
  margin-bottom: 8px;
}
.attach-name { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pdf-icon { color: #e5484d; }

/* 合同登记弹窗:多 tab + 供应商表内容较长,让弹窗 body 内部滚动,底栏常驻 */
.contract-form-dialog :deep(.el-dialog__body) {
  max-height: calc(100vh - 200px);
  overflow-y: auto;
}
/* 放宽内边距与行距,避免整体过于紧凑(控件 32px 高度沿用全局规范) */
.contract-form-dialog :deep(.el-dialog__body > .el-form) {
  padding: 24px 30px;
}
.contract-form-dialog :deep(.el-form-item) {
  margin-bottom: 24px;
}
.contract-form-dialog :deep(.el-form-item__error) {
  padding-top: 2px;
}
.contract-form-dialog :deep(.el-tabs__header) {
  margin-bottom: 28px;
}
.contract-form-dialog :deep(.el-tabs__item) {
  font-size: 13px;
  height: 38px;
  line-height: 38px;
}
.contract-form-dialog :deep(.el-textarea__inner) {
  min-height: 80px;
}
.contract-form-dialog :deep(.el-input-number) {
  width: 100%;
}
/* 底栏按钮上下留出呼吸空间,避免贴边 */
.contract-form-dialog :deep(.el-dialog__footer) {
  min-height: 64px !important;
  padding: 12px 16px !important;
}
</style>
