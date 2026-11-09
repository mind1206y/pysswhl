<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  adjustStock, deleteInStock, deleteMaterial, deleteMaterialImage, exportInOutRecords,
  exportStockCheck, getMaterial, getMaterialDicts, getMaterialImages,
  listInOut, listStocks, saveInStock, saveMaterial, submitStockCheck,
  getStockWarning, uploadMaterialImages,
} from '@/api/material'

const dicts = reactive({
  departments: [], categories: [], specs: [], materials: [],
  perms: { view: true, manage: false },
})
const activeTab = ref('stock')

// ==================== 关键字高亮(黄荧光笔,照旧) ====================
const searchKey = ref('')
const searchKey2 = ref('')

function escapeReg(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}
function highlight(text, key) {
  if (text == null || text === '') return ''
  const k = (key || '').trim()
  if (!k) return String(text)
  const keys = Array.from(new Set(k.split(/[\s,，]+/).map((s) => s.trim()).filter(Boolean)))
  let out = String(text)
  keys.forEach((kw) => {
    out = out.replace(new RegExp(escapeReg(kw), 'gi'),
      (m) => `<span class="hl">${m}</span>`)
  })
  return out
}

// ==================== 材料库存 ====================
const stockLoading = ref(false)
const stockRows = ref([])
const stockTotal = ref(0)
const stockPage = ref(1)
const stockSize = ref(30)
const stockKeyword = ref('')
const stockBmid = ref(null)
const chkDakoujing = ref(false)

async function loadStock() {
  stockLoading.value = true
  try {
    const params = { page: stockPage.value, size: stockSize.value }
    if (stockKeyword.value) params.mohu = stockKeyword.value
    if (stockBmid.value) params.bmid = stockBmid.value
    const data = await listStocks(params)
    stockRows.value = data.rows
    stockTotal.value = data.total
  } finally {
    stockLoading.value = false
  }
}

function stockSearch() {
  searchKey.value = stockKeyword.value
  stockPage.value = 1
  loadStock()
}
function clearStockFilter() {
  stockKeyword.value = ''
  stockBmid.value = null
  stockSearch()
}

// 盘点数量单元格编辑(照旧点击单元格进入编辑,回车/失焦提交)
const editingKey = ref(null)
function diffOf(row) {
  if (row.CheckNum == null || row.CheckNum === '') return null
  return Math.round((row.CheckNum - (row.num || 0)) * 10) / 10
}
function commitCheck(row) {
  editingKey.value = null
  if (row.CheckNum != null && row.CheckNum !== '') {
    row.CheckNum = Math.round(row.CheckNum * 10) / 10
  }
}

async function submitCheck() {
  const list = stockRows.value
    .filter((r) => r.CheckNum != null && r.CheckNum !== '' && r.CheckNum !== r.num)
    .map((r) => ({ MaterialId: r.id, CheckNum: r.CheckNum }))
  if (!list.length) {
    ElMessage.warning('没有库存变化，无需提交')
    return
  }
  await submitStockCheck(list)
  ElMessage.success('盘点完成')
  loadStock()
  if (activeTab.value === 'stock') loadInOut()
}

function doExportStockCheck() {
  exportStockCheck(chkDakoujing.value ? 'on' : '')
  ElMessage.success('盘点表已导出')
}

// ==================== 材料信息弹窗 ====================
const matDialog = ref(false)
const matFormRef = ref()
const matForm = reactive({
  id: 0, MaterialName: '', biaoji: '', Alias1: '', Alias2: '', Alias3: '',
  Model: '', Spec: '', Unit: '', dakoujing: false, yujing: null, Remark: '',
})
const matRules = {
  MaterialName: [{ required: true, message: '请输入材料名称', trigger: 'blur' }],
  Model: [{ required: true, message: '请输入或选择型号类别', trigger: 'change' }],
  Spec: [{ required: true, message: '请输入或选择规格', trigger: 'change' }],
  Unit: [{ required: true, message: '请输入单位', trigger: 'blur' }],
}
const matTab = ref('base')
const imgList = ref([])
const uploadFiles = ref([])
const previewVisible = ref(false)
const previewUrl = ref('')

function resetMatForm() {
  Object.assign(matForm, {
    id: 0, MaterialName: '', biaoji: '', Alias1: '', Alias2: '', Alias3: '',
    Model: '', Spec: '', Unit: '', dakoujing: false, yujing: null, Remark: '',
  })
}

function openAddMaterial() {
  resetMatForm()
  matTab.value = 'base'
  imgList.value = []
  uploadFiles.value = []
  matDialog.value = true
}

async function openEditMaterial(row) {
  const d = await getMaterial(row.id)
  Object.assign(matForm, {
    id: d.id, MaterialName: d.MaterialName, biaoji: d.biaoji,
    Alias1: d.Alias1, Alias2: d.Alias2, Alias3: d.Alias3,
    Model: d.Model, Spec: d.Spec, Unit: d.Unit,
    dakoujing: d.dakoujing === 'on',
    yujing: d.yujing, Remark: d.Remark,
  })
  matTab.value = 'base'
  await loadImages(d.id)
  uploadFiles.value = []
  matDialog.value = true
}

async function loadImages(materialId) {
  imgList.value = await getMaterialImages(materialId)
}

function onMatTabChange(name) {
  if (name === 'images' && !matForm.id) {
    matTab.value = 'base'
    ElMessage.warning('请先保存材料基本信息')
  }
}

async function saveMaterialSubmit() {
  await matFormRef.value.validate()
  const res = await saveMaterial({
    id: matForm.id,
    MaterialName: matForm.MaterialName,
    biaoji: matForm.biaoji,
    Alias1: matForm.Alias1,
    Alias2: matForm.Alias2,
    Alias3: matForm.Alias3,
    Model: matForm.Model,
    Spec: matForm.Spec,
    Unit: matForm.Unit,
    dakoujing: matForm.dakoujing ? 'on' : null,
    yujing: matForm.yujing == null || matForm.yujing === '' ? null : Number(matForm.yujing),
    Remark: matForm.Remark,
  })
  ElMessage.success('已保存！')
  matForm.id = res.id
  loadStock()
  // 照旧:保存后自动切到图片管理页签
  matTab.value = 'images'
  await loadImages(res.id)
  loadDicts()
}

async function doUploadImages() {
  if (!matForm.id) {
    ElMessage.warning('请先保存材料再上传图片')
    return
  }
  const files = (uploadFiles.value || []).map((f) => f.raw)
  if (!files.length) return
  await uploadMaterialImages(matForm.id, files)
  ElMessage.success('图片已上传')
  uploadFiles.value = []
  await loadImages(matForm.id)
  loadStock()
}

async function doDeleteImage(img) {
  await deleteMaterialImage(img.id)
  await loadImages(matForm.id)
  loadStock()
}

async function doDeleteMaterial(row) {
  try {
    await ElMessageBox.confirm(`确定要删除材料「${row.MaterialName}」吗？`, '确认', { type: 'warning' })
  } catch { return }
  try {
    await deleteMaterial(row.id)
    ElMessage.success('删除成功！')
    loadStock()
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || '删除失败')
  }
}

function onStockRowDblClick(row) {
  if (!dicts.perms.manage) {
    ElMessage.info('您没有权限编辑')
    return
  }
  openEditMaterial(row)
}

// ==================== 库存预警 ====================
const warningDialog = ref(false)
const warningRows = ref([])

async function showStockWarning() {
  warningDialog.value = true
  warningRows.value = await getStockWarning()
}

// ==================== 进出库记录 ====================
const inOutLoading = ref(false)
const inOutRows = ref([])
const inOutTotal = ref(0)
const inOutPage = ref(1)
const inOutSize = ref(30)
const inOutKeyword = ref('')
const inOutBmid = ref(null)
const inOutDir = ref('')
const inOutDates = ref([])
const currentInOutRow = ref(null)

function inOutParams(withPage = true) {
  const p = {}
  if (withPage) { p.page = inOutPage.value; p.size = inOutSize.value }
  if (inOutKeyword.value) p.mohu = inOutKeyword.value
  if (inOutBmid.value) p.bmid = inOutBmid.value
  if (inOutDir.value) p.direction = inOutDir.value
  if (inOutDates.value && inOutDates.value.length === 2) {
    p.StartDate = inOutDates.value[0]
    p.EndDate = inOutDates.value[1]
  }
  return p
}

async function loadInOut() {
  inOutLoading.value = true
  try {
    const data = await listInOut(inOutParams())
    inOutRows.value = data.rows
    inOutTotal.value = data.total
  } finally {
    inOutLoading.value = false
  }
}

function inOutSearch() {
  searchKey2.value = inOutKeyword.value
  inOutPage.value = 1
  loadInOut()
}
function clearInOutFilter() {
  inOutKeyword.value = ''
  inOutBmid.value = null
  inOutDir.value = ''
  inOutDates.value = []
  searchKey2.value = ''
  inOutPage.value = 1
  loadInOut()
}

async function doExportInOut() {
  await exportInOutRecords(inOutParams(false))
  ElMessage.success('进出库记录已导出')
}

// ==================== 入库弹窗 ====================
const inStockDialog = ref(false)
const inStockFormRef = ref()
const inStockForm = reactive({ MaterialId: null, Quantity: null, Remark: '' })
const inStockRules = {
  MaterialId: [{ required: true, message: '请选择材料', trigger: 'change' }],
  Quantity: [{ required: true, message: '请输入入库数量', trigger: 'blur' }],
}

function openInStock() {
  Object.assign(inStockForm, { MaterialId: null, Quantity: null, Remark: '' })
  inStockDialog.value = true
}

async function submitInStock() {
  await inStockFormRef.value.validate()
  await saveInStock({
    id: 0,
    MaterialId: inStockForm.MaterialId,
    Quantity: Number(inStockForm.Quantity),
    Remark: inStockForm.Remark,
  })
  ElMessage.success('已保存！')
  inStockDialog.value = false
  loadInOut()
  loadStock()
}

async function doDeleteInStock(row) {
  if (!row) {
    ElMessage.warning('请先选择一条入库记录！')
    return
  }
  if (row.Direction === '出库') {
    ElMessage.warning('出库记录来自工单领料，不能在此删除')
    return
  }
  try {
    await ElMessageBox.confirm('确定要删除这条入库记录吗？删除后库存会同步减少。', '确认', { type: 'warning' })
  } catch { return }
  await deleteInStock(row.Id ?? row.id)
  ElMessage.success('删除成功！')
  currentInOutRow.value = null
  loadInOut()
  loadStock()
}

// ==================== 库存调整弹窗 ====================
const adjustDialog = ref(false)
const adjustFormRef = ref()
const adjustForm = reactive({ materialId: null, adjustQuantity: null, reason: '' })
const adjustRules = {
  materialId: [{ required: true, message: '请选择材料', trigger: 'change' }],
  adjustQuantity: [{ required: true, message: '请输入调整数量(可负数)', trigger: 'blur' }],
  reason: [{ required: true, message: '请输入调整原因', trigger: 'blur' }],
}

function openAdjust() {
  Object.assign(adjustForm, { materialId: null, adjustQuantity: null, reason: '' })
  adjustDialog.value = true
}

async function submitAdjust() {
  await adjustFormRef.value.validate()
  await adjustStock({
    materialId: adjustForm.materialId,
    adjustQuantity: Number(adjustForm.adjustQuantity),
    reason: adjustForm.reason,
  })
  ElMessage.success('库存调整成功！')
  adjustDialog.value = false
  loadInOut()
  loadStock()
}

// ==================== 字典 ====================
async function loadDicts() {
  const d = await getMaterialDicts()
  Object.assign(dicts, d)
}

onMounted(async () => {
  await loadDicts()
  loadStock()
  loadInOut()
})
</script>

<template>
  <div class="mat-page">
    <el-tabs v-model="activeTab" class="mat-tabs">
      <!-- ==================== 材料库存 ==================== -->
      <el-tab-pane label="材料库存" name="stock">
        <div class="toolbar">
          <template v-if="dicts.perms.manage">
            <el-button type="primary" size="small" @click="openAddMaterial">添加材料</el-button>
          </template>
          <el-button size="small" @click="showStockWarning">库存预警</el-button>
          <el-button type="success" size="small" @click="submitCheck">盘点提交</el-button>
          <el-button size="small" @click="doExportStockCheck">导出盘点表</el-button>
          <span class="search-group">
            <el-input v-model="stockKeyword" clearable style="width: 220px" size="small"
              placeholder="请输入关键字搜索" @keyup.enter="stockSearch" @clear="stockSearch" />
            <el-select v-model="stockBmid" clearable filterable size="small" style="width: 150px"
              placeholder="选择部门" @change="stockSearch">
              <el-option v-for="d in dicts.departments" :key="d.id" :label="d.bm" :value="d.id" />
            </el-select>
            <el-checkbox v-model="chkDakoujing" size="small">导出大口径</el-checkbox>
            <el-button size="small" @click="clearStockFilter">清空部门</el-button>
          </span>
          <span class="toolbar-hint">双击行编辑材料(需管理权限) · 点击「盘点数量」单元格录入盘点</span>
        </div>

        <el-table v-loading="stockLoading" :data="stockRows" border stripe size="small"
          height="calc(100vh - 280px)" row-key="id" @row-dblclick="onStockRowDblClick">
          <el-table-column prop="id" label="ID" width="55" />
          <el-table-column label="材料名称" min-width="150">
            <template #default="{ row }">
              <span v-html="highlight(row.MaterialName, searchKey)" />
            </template>
          </el-table-column>
          <el-table-column label="别名1" min-width="100" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-html="highlight(row.Alias1, searchKey)" />
            </template>
          </el-table-column>
          <el-table-column label="拼音首字母" width="90">
            <template #default="{ row }">
              <span v-html="highlight(row.biaoji, searchKey)" />
            </template>
          </el-table-column>
          <el-table-column label="型号类别" min-width="110" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-html="highlight(row.Model, searchKey)" />
            </template>
          </el-table-column>
          <el-table-column label="规格" min-width="110" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-html="highlight(row.Spec, searchKey)" />
            </template>
          </el-table-column>
          <el-table-column label="大口径" width="70" align="center">
            <template #default="{ row }">
              <span v-if="row.dakoujing === 'on'" class="dakoujing-badge">是</span>
            </template>
          </el-table-column>
          <el-table-column prop="num" label="库存数" width="80" align="right" />
          <el-table-column label="盘点数量" width="110" align="center">
            <template #default="{ row }">
              <el-input-number v-if="editingKey === `s-${row.id}`" v-model="row.CheckNum"
                :precision="1" :min="0" :controls="false" size="small" style="width: 90px"
                @change="commitCheck(row)" @blur="commitCheck(row)" @keyup.enter="commitCheck(row)" />
              <span v-else class="check-cell" @click="editingKey = `s-${row.id}`">
                {{ row.CheckNum ?? '' }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="差异" width="70" align="right">
            <template #default="{ row }">
              <span :class="{ 'diff-warn': diffOf(row) !== null && diffOf(row) !== 0 }">
                {{ diffOf(row) === null ? '' : diffOf(row).toFixed(1) }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="预警数" width="75" align="right">
            <template #default="{ row }">{{ row.yujing ?? '' }}</template>
          </el-table-column>
          <el-table-column prop="Unit" label="单位" width="60" />
          <el-table-column label="备注" min-width="130" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-html="highlight(row.Remark, searchKey)" />
            </template>
          </el-table-column>
          <el-table-column label="图片" width="130">
            <template #default="{ row }">
              <div class="img-strip">
                <el-image v-for="img in row.Images" :key="img.id" :src="img.ThumbPath"
                  :preview-src-list="[img.FilePath]" preview-teleported fit="cover"
                  class="img-thumb" :hide-on-click-modal="true" />
              </div>
            </template>
          </el-table-column>
          <el-table-column v-if="dicts.perms.manage" label="删除" width="60" align="center">
            <template #default="{ row }">
              <el-button link type="danger" size="small" @click.stop="doDeleteMaterial(row)">
                <el-icon><Delete /></el-icon>
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <div class="pager">
          <el-pagination v-model:current-page="stockPage" v-model:page-size="stockSize"
            :total="stockTotal" :page-sizes="[30, 60, 120]"
            layout="total, sizes, prev, pager, next, jumper"
            @current-change="loadStock" @size-change="stockSearch" />
        </div>
      </el-tab-pane>

      <!-- ==================== 进出库记录 ==================== -->
      <el-tab-pane label="进出库记录" name="inout">
        <div class="toolbar">
          <el-button type="primary" size="small" @click="openInStock">添加入库</el-button>
          <el-button v-if="dicts.perms.manage" type="danger" plain size="small"
            @click="doDeleteInStock(currentInOutRow)">删除</el-button>
          <el-button size="small" @click="openAdjust">库存调整</el-button>
          <el-button size="small" @click="doExportInOut">导出进出库记录</el-button>
          <span class="search-group">
            <el-input v-model="inOutKeyword" clearable style="width: 170px" size="small"
              placeholder="请输入关键字搜索" @keyup.enter="inOutSearch" @clear="inOutSearch" />
            <el-date-picker v-model="inOutDates" type="daterange" size="small"
              value-format="YYYY-MM-DD" start-placeholder="开始日期" end-placeholder="结束日期"
              style="width: 230px" @change="inOutSearch" />
            <el-select v-model="inOutBmid" clearable filterable size="small" style="width: 140px"
              placeholder="选择部门" @change="inOutSearch">
              <el-option v-for="d in dicts.departments" :key="d.id" :label="d.bm" :value="d.id" />
            </el-select>
            <el-select v-model="inOutDir" size="small" style="width: 90px" @change="inOutSearch">
              <el-option label="全部" value="" />
              <el-option label="入库" value="入库" />
              <el-option label="出库" value="出库" />
            </el-select>
            <el-button type="primary" size="small" @click="inOutSearch">搜索</el-button>
            <el-button size="small" @click="clearInOutFilter">清空</el-button>
          </span>
        </div>

        <el-table v-loading="inOutLoading" :data="inOutRows" border stripe size="small"
          highlight-current-row height="calc(100vh - 280px)"
          :row-class-name="({ row }) => (row.Quantity < 0 ? 'out-row' : '')"
          @current-change="(r) => (currentInOutRow = r)">
          <el-table-column prop="Id" label="ID" width="70" />
          <el-table-column label="材料名称" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-html="highlight(row.MaterialName, searchKey2)" />
            </template>
          </el-table-column>
          <el-table-column label="型号类别" min-width="110" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-html="highlight(row.Model, searchKey2)" />
            </template>
          </el-table-column>
          <el-table-column label="规格" min-width="110" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-html="highlight(row.Spec, searchKey2)" />
            </template>
          </el-table-column>
          <el-table-column label="大口径" width="70" align="center">
            <template #default="{ row }">
              <span v-if="row.dakoujing === 'on'" class="dakoujing-badge">是</span>
            </template>
          </el-table-column>
          <el-table-column label="数量" width="80" align="right">
            <template #default="{ row }">
              <span :class="{ 'qty-out': row.Quantity < 0 }">{{ Number(row.Quantity).toFixed(1) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="Unit" label="单位" width="60" />
          <el-table-column prop="Direction" label="类型" width="90" />
          <el-table-column prop="RecordTime" label="时间" width="150" />
          <el-table-column prop="Remark" label="备注" min-width="150" show-overflow-tooltip />
          <el-table-column prop="Operator" label="操作人" width="90" />
          <el-table-column prop="RefNo" label="关联单号" width="110" show-overflow-tooltip />
        </el-table>

        <div class="pager">
          <el-pagination v-model:current-page="inOutPage" v-model:page-size="inOutSize"
            :total="inOutTotal" :page-sizes="[30, 60, 120]"
            layout="total, sizes, prev, pager, next, jumper"
            @current-change="loadInOut" @size-change="inOutSearch" />
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- ==================== 材料信息弹窗(基本信息 + 图片管理) ==================== -->
    <el-dialog v-model="matDialog" :title="matForm.id ? '编辑材料' : '添加材料'"
      width="840px" :close-on-click-modal="false" top="6vh">
      <el-tabs v-model="matTab" @tab-change="onMatTabChange">
        <el-tab-pane label="基本信息" name="base">
          <el-form ref="matFormRef" :model="matForm" :rules="matRules" label-width="92px"
            class="mat-form">
            <div class="form-grid">
              <el-form-item label="材料名称" prop="MaterialName">
                <el-input v-model="matForm.MaterialName" style="width: 240px" />
              </el-form-item>
              <el-form-item label="拼音首字母">
                <el-input v-model="matForm.biaoji" style="width: 240px" />
              </el-form-item>
              <el-form-item label="别名1">
                <el-input v-model="matForm.Alias1" style="width: 240px" />
              </el-form-item>
              <el-form-item label="别名2">
                <el-input v-model="matForm.Alias2" style="width: 240px" />
              </el-form-item>
              <el-form-item label="别名3">
                <el-input v-model="matForm.Alias3" style="width: 240px" />
              </el-form-item>
              <el-form-item label="型号类别" prop="Model">
                <el-select v-model="matForm.Model" filterable allow-create default-first-option
                  style="width: 240px" placeholder="选择或输入">
                  <el-option v-for="c in dicts.categories" :key="c.value" :label="c.text" :value="c.value" />
                </el-select>
              </el-form-item>
              <el-form-item label="规格" prop="Spec">
                <el-select v-model="matForm.Spec" filterable allow-create default-first-option
                  style="width: 240px" placeholder="选择或输入">
                  <el-option v-for="c in dicts.specs" :key="c.value" :label="c.text" :value="c.value" />
                </el-select>
              </el-form-item>
              <el-form-item label="单位" prop="Unit">
                <el-input v-model="matForm.Unit" style="width: 240px" />
              </el-form-item>
              <el-form-item label="大口径">
                <el-switch v-model="matForm.dakoujing" active-text="是" inactive-text="否" />
              </el-form-item>
              <el-form-item label="预警数">
                <el-input-number v-model="matForm.yujing" :precision="1" :min="0"
                  :controls="false" style="width: 240px" />
              </el-form-item>
            </div>
            <el-form-item label="备注">
              <el-input v-model="matForm.Remark" type="textarea" :rows="3" style="width: 580px" />
            </el-form-item>
          </el-form>
        </el-tab-pane>
        <el-tab-pane label="图片管理" name="images">
          <div class="img-upload-bar">
            <el-upload v-model:file-list="uploadFiles" multiple accept="image/*"
              :auto-upload="false" :show-file-list="true">
              <el-button size="small">选择图片</el-button>
            </el-upload>
            <el-button type="primary" size="small" @click="doUploadImages">上传图片</el-button>
          </div>
          <div class="img-grid">
            <div v-for="img in imgList" :key="img.id" class="img-item">
              <img :src="img.ThumbPath" loading="lazy" @click="() => { previewUrl = img.FilePath; previewVisible = true }">
              <div class="img-actions">
                <a title="删除" @click.prevent="doDeleteImage(img)">×</a>
                <a :href="img.FilePath" target="_blank" title="下载原图">↓</a>
              </div>
            </div>
            <div v-if="!imgList.length" class="img-empty">暂无图片</div>
          </div>
        </el-tab-pane>
      </el-tabs>
      <template #footer>
        <el-button @click="matDialog = false">取消</el-button>
        <el-button type="primary" @click="saveMaterialSubmit">保存</el-button>
      </template>
    </el-dialog>

    <!-- 图片预览 -->
    <el-dialog v-model="previewVisible" title="图片预览" width="800px" top="6vh">
      <img :src="previewUrl" style="width: 100%; object-fit: contain; max-height: 70vh">
    </el-dialog>

    <!-- ==================== 入库记录弹窗 ==================== -->
    <el-dialog v-model="inStockDialog" title="添加入库记录" width="480px" :close-on-click-modal="false">
      <el-form ref="inStockFormRef" :model="inStockForm" :rules="inStockRules" label-width="92px">
        <el-form-item label="材料" prop="MaterialId">
          <el-select v-model="inStockForm.MaterialId" filterable style="width: 280px"
            placeholder="按名称/别名检索">
            <el-option v-for="m in dicts.materials" :key="m.Id" :label="m.DisplayText" :value="m.Id" />
          </el-select>
        </el-form-item>
        <el-form-item label="入库数量" prop="Quantity">
          <el-input-number v-model="inStockForm.Quantity" :precision="1" :min="0"
            :controls="false" style="width: 280px" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="inStockForm.Remark" type="textarea" :rows="2" style="width: 280px" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="inStockDialog = false">取消</el-button>
        <el-button type="primary" @click="submitInStock">保存</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 库存调整弹窗 ==================== -->
    <el-dialog v-model="adjustDialog" title="库存调整" width="460px" :close-on-click-modal="false">
      <el-form ref="adjustFormRef" :model="adjustForm" :rules="adjustRules" label-width="92px">
        <el-form-item label="材料" prop="materialId">
          <el-select v-model="adjustForm.materialId" filterable style="width: 280px"
            placeholder="按名称/别名检索">
            <el-option v-for="m in dicts.materials" :key="m.Id" :label="m.DisplayText" :value="m.Id" />
          </el-select>
        </el-form-item>
        <el-form-item label="调整数量" prop="adjustQuantity">
          <el-input-number v-model="adjustForm.adjustQuantity" :precision="1"
            :controls="false" style="width: 280px" />
        </el-form-item>
        <el-form-item label="调整原因" prop="reason">
          <el-input v-model="adjustForm.reason" style="width: 280px" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="adjustDialog = false">取消</el-button>
        <el-button type="primary" @click="submitAdjust">保存</el-button>
      </template>
    </el-dialog>

    <!-- ==================== 库存预警弹窗 ==================== -->
    <el-dialog v-model="warningDialog" title="库存预警" width="850px" top="6vh">
      <div style="margin-bottom: 8px">
        <el-button size="small" @click="showStockWarning">刷新</el-button>
        <span class="toolbar-hint">共 {{ warningRows.length }} 项低于预警值</span>
      </div>
      <el-table :data="warningRows" border stripe size="small" max-height="420">
        <el-table-column prop="MaterialName" label="材料名称" min-width="150" />
        <el-table-column prop="Model" label="型号" width="110" />
        <el-table-column prop="Spec" label="规格" width="110" />
        <el-table-column prop="StockQuantity" label="库存数量" width="90" align="right" />
        <el-table-column prop="yujing" label="预警数量" width="90" align="right" />
        <el-table-column prop="Unit" label="单位" width="70" align="right" />
        <el-table-column prop="Remark" label="备注" min-width="180" show-overflow-tooltip />
      </el-table>
    </el-dialog>
  </div>
</template>

<style scoped>
.mat-page {
  background: #fff;
  border-radius: 6px;
  padding: 6px 12px 12px;
}
.mat-tabs :deep(.el-tabs__header) {
  margin-bottom: 8px;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
}
.search-group {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px 10px;
  margin-left: 16px;
}
.toolbar-hint {
  margin-left: auto;
  color: #909399;
  font-size: 12px;
}
.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}
.hl {
  background-color: rgba(255, 208, 84, 0.45);
  font-weight: bold;
  color: #3f3118;
}
.dakoujing-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 12px;
  background-color: #d99a2b;
  color: #fffaf0;
  font-size: 12px;
}
.check-cell {
  cursor: pointer;
  display: inline-block;
  min-width: 60px;
  min-height: 18px;
}
.diff-warn {
  background: rgba(255, 208, 84, 0.45);
  font-weight: bold;
  padding: 0 4px;
}
.qty-out {
  color: #ff6b6b;
}
:deep(.out-row) {
  color: #ff6b6b;
}
.img-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
}
.img-thumb {
  width: 44px;
  height: 44px;
  border-radius: 4px;
  border: 1px solid #dcdfe6;
}
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
}
.img-upload-bar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.img-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 8px;
  border: 1px dashed #dcdfe6;
  border-radius: 6px;
  min-height: 200px;
  max-height: 300px;
  overflow: auto;
  background: #fafafa;
}
.img-item {
  width: 110px;
  height: 110px;
  border-radius: 8px;
  overflow: hidden;
  position: relative;
  border: 1px solid #e4e7ed;
  background: #fff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}
.img-item img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  cursor: pointer;
  transition: transform 0.3s;
}
.img-item img:hover {
  transform: scale(1.15);
}
.img-actions {
  position: absolute;
  top: 4px;
  right: 4px;
  display: flex;
  gap: 2px;
}
.img-actions a {
  display: inline-block;
  width: 20px;
  height: 20px;
  line-height: 20px;
  text-align: center;
  border-radius: 50%;
  background: rgba(0, 0, 0, 0.55);
  color: #fff;
  font-size: 12px;
  cursor: pointer;
  text-decoration: none;
}
.img-actions a:hover {
  background: #f56c6c;
}
.img-empty {
  color: #909399;
  align-self: center;
  margin: auto;
}
</style>
