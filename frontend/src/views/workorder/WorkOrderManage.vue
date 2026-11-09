<script setup>
/**
 * 工单领料管理 —— 照旧 WorkOrder/Index.cshtml 1:1 复刻
 * 顶部: 领料工单信息(工单号/班组/领料类别/备注 + 地址回显)
 * 中部: 左「材料库存」右「已选材料(领料单)」,加入/取消/提交领料
 * 下部: 工单列表(查询/导出/只看未领用/全屏),展开看明细、编辑、删除、附件
 * 抽屉: 外部工单详情、附件管理
 */
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  deleteAttachment, deleteWorkOrder, exportWorkOrderStatistics,
  getExternalImages, getExternalWorkOrder, getOrderByNo, getOrderByNo2,
  getOrderDetails, getWorkOrderDicts, listAttachments, listWorkOrders,
  listWorkOrderStocks, submitWorkOrder, uploadAttachment,
} from '@/api/workorder'

// ==================== 字典 ====================
const dicts = reactive({
  banzu: [], lingliaotypes: [], filterTypes: [], emptySentinel: '__EMPTY__',
  departments: [], perms: { view: true, manage: false },
})

// ==================== 领料工单信息(表头) ====================
const header = reactive({ workOrderNo: '', banzu: '', lingliaotype: '', beizhu: '' })
const address = ref('')
const addressVisible = ref(false)
const oldWorkOrderNo = ref('')
const currentOrderId = ref(null) // null=新增,否则编辑既有领料单
const noInput = ref(null)

// ==================== 材料库存 ====================
const stockRows = ref([])
const stockTotal = ref(0)
const stockPage = ref(1)
const stockSize = ref(10) // 每页 10 条,正好一屏放得下,不出表格滚动条
const stockKeyword = ref('')
const stockLoading = ref(false)
const stockQty = reactive({}) // 行级待加入数量
let stockTimer = null

// ==================== 视口自适应:整页不出现滚动条 ====================
// 三段卡片按剩余高度 flex 分配,表格高度用 ResizeObserver 实测父容器,
// 给 el-table 传数值高度(百分比高度在 flex 容器里不可靠)。
const winWidth = ref(window.innerWidth)
const wide = computed(() => winWidth.value >= 1500) // 窄屏隐藏次要列,避免横向滚动条
const stockWrap = ref(null)
const cartWrap = ref(null)
const orderWrap = ref(null)
const stockTableH = ref(200)
const cartTableH = ref(200)
const orderTableH = ref(200)
let tableObserver = null

function fitTables() {
  if (stockWrap.value) stockTableH.value = Math.max(120, stockWrap.value.clientHeight)
  if (cartWrap.value) cartTableH.value = Math.max(120, cartWrap.value.clientHeight)
  if (orderWrap.value) orderTableH.value = Math.max(120, orderWrap.value.clientHeight)
}
function onWindowResize() {
  winWidth.value = window.innerWidth
  fitTables()
}

async function loadStocks() {
  stockLoading.value = true
  try {
    const data = await listWorkOrderStocks({
      page: stockPage.value, size: stockSize.value, mohu: stockKeyword.value.trim(),
    })
    stockRows.value = data.rows || []
    stockTotal.value = data.total || 0
    stockRows.value.forEach((r) => {
      if (stockQty[r.Id] == null) stockQty[r.Id] = '1.0'
    })
  } finally {
    stockLoading.value = false
  }
}

function onStockKeyword() {
  clearTimeout(stockTimer)
  stockTimer = setTimeout(() => {
    stockPage.value = 1
    loadStocks()
  }, 300)
}

function normQty(v) {
  let n = parseFloat(v)
  if (isNaN(n) || n < 0.1) n = 0.1
  return Math.round(n * 10) / 10
}

function formatStockQty(row) {
  const n = normQty(stockQty[row.Id])
  stockQty[row.Id] = n.toFixed(1)
}

// 旧系统「只增减整数部分,小数部分保持不变」
function stepQty(value, delta) {
  const val = normQty(value)
  const integer = Math.floor(val)
  const decimal = val - integer
  let next = integer + delta + decimal
  if (integer + delta < 0) next = decimal
  if (next < 0.1) next = 0.1
  return (Math.round(next * 10) / 10).toFixed(1)
}

function changeStockQty(row, delta) {
  stockQty[row.Id] = stepQty(stockQty[row.Id], delta)
}

function addToCart(row) {
  const qty = normQty(stockQty[row.Id])
  const exist = cart.value.find((x) => x.Id === row.Id)
  if (exist) {
    exist.Qty = (Math.round((normQty(exist.Qty) + qty) * 10) / 10).toFixed(1)
  } else {
    cart.value.push({
      Id: row.Id, MaterialName: row.MaterialName, Model: row.Model,
      Spec: row.Spec, Qty: qty.toFixed(1), Unit: row.Unit,
    })
  }
}

// ==================== 已选材料(领料单 / 购物车) ====================
const cart = ref([])
function removeCart(index) {
  cart.value.splice(index, 1)
}
function changeCartQty(item, delta) {
  item.Qty = stepQty(item.Qty, delta)
}
function formatCartQty(item) {
  item.Qty = normQty(item.Qty).toFixed(1)
}
const cartTotalQty = computed(() =>
  cart.value.reduce((sum, i) => sum + normQty(i.Qty), 0).toFixed(1))

// ==================== 工单号失焦:地址回显 + 历史领料记录加载 ====================
function showAddress(text) {
  address.value = text || ''
  addressVisible.value = !!text
}

function fillFromDetails(details, no) {
  cart.value = details.map((d) => ({
    Id: d.MaterialId, MaterialName: d.MaterialName, Model: d.Model,
    Spec: d.Spec, Qty: Number(d.Quantity || 0).toFixed(1), Unit: d.Unit,
  }))
  header.workOrderNo = no
  header.banzu = details[0].banzu || ''
  header.lingliaotype = details[0].lingliaotype || ''
  header.beizhu = details[0].beizhu || ''
  currentOrderId.value = details[0].WorkOrderId
  oldWorkOrderNo.value = no
}

async function onWorkOrderNoBlur() {
  const no = (header.workOrderNo || '').trim()
  if (no === oldWorkOrderNo.value) return
  if (currentOrderId.value != null) {
    // 编辑模式:工单号不得为空,且不得与其它领料单冲突
    if (!no) {
      ElMessage.warning('工单号不能为空')
      header.workOrderNo = oldWorkOrderNo.value
      return
    }
    const res = await getOrderByNo(no)
    const details = res.details || []
    if (details.length && details[0].WorkOrderId !== currentOrderId.value) {
      ElMessage.warning('工单号已被其他领料单使用，请重新输入')
      header.workOrderNo = oldWorkOrderNo.value
    } else {
      oldWorkOrderNo.value = no
      showAddress(res.address)
    }
    return
  }
  if (!no) return
  const res = await getOrderByNo(no)
  showAddress(res.address)
  const details = res.details || []
  if (!details.length) {
    oldWorkOrderNo.value = no
    return
  }
  try {
    await ElMessageBox.confirm('已找到该工单的领料记录，是否加载到购物车供修改？', '提示', {
      confirmButtonText: '加载记录', cancelButtonText: '取消', type: 'info',
    })
    fillFromDetails(details, no)
  } catch {
    // 旧系统:取消加载则整单清空,不能继续添加材料
    resetEntry(true)
    ElMessage.info('已取消加载工单，不能继续添加材料')
  }
}

// ==================== 重置 / 提交领料 ====================
function resetEntry(clearHeader = false) {
  cart.value = []
  header.workOrderNo = ''
  header.beizhu = ''
  oldWorkOrderNo.value = ''
  currentOrderId.value = null
  showAddress('')
  if (clearHeader) {
    header.banzu = ''
    header.lingliaotype = ''
  }
  stockKeyword.value = ''
  loadStocks()
  loadOrders()
  // 连续录入时焦点回到工单号
  setTimeout(() => noInput.value?.focus(), 60)
}

const submitting = ref(false)
async function submitEntry() {
  const no = (header.workOrderNo || '').trim()
  if (!no || !header.banzu || !header.lingliaotype || !cart.value.length) {
    ElMessage.warning('请填写工单号、班组、领料类别并选择材料')
    return
  }
  submitting.value = true
  try {
    await submitWorkOrder({
      workOrderNo: no,
      banzu: header.banzu,
      lingliaotype: header.lingliaotype,
      beizhu: (header.beizhu || '').trim(),
      orderId: currentOrderId.value,
      items: cart.value.map((i) => ({
        Id: i.Id, MaterialName: i.MaterialName, Spec: i.Spec,
        Qty: Number(normQty(i.Qty).toFixed(1)), Unit: i.Unit,
      })),
    })
    ElMessage.success(currentOrderId.value ? '领料已更新' : '领料已提交')
    resetEntry(false)
  } finally {
    submitting.value = false
  }
}

// ==================== 工单列表 ====================
const orderRows = ref([])
const orderTotal = ref(0)
const orderPage = ref(1)
const orderSize = ref(10) // 与库存同为 10 条,列表区不出现纵向滚动条
const orderLoading = ref(false)
const filters = reactive({
  searchText: '', startDate: '', endDate: '', dakoujing: false,
  lingliaotype: '全部类别', unusedOnly: false, bmid: null,
})
const fullscreen = ref(false)

function typeParam() {
  const v = filters.lingliaotype
  if (!v || v === '全部类别') return ''
  if (v === '（未分类）') return dicts.emptySentinel
  return v
}

async function loadOrders() {
  orderLoading.value = true
  try {
    const data = await listWorkOrders({
      page: orderPage.value, size: orderSize.value,
      searchText: filters.searchText.trim(),
      startDate: filters.startDate || '', endDate: filters.endDate || '',
      dakoujing: filters.dakoujing ? 'on' : '',
      lingliaotype: typeParam(),
      unusedOnly: filters.unusedOnly,
      ...(filters.bmid ? { bmid: filters.bmid } : {}),
    })
    orderRows.value = data.rows || []
    orderTotal.value = data.total || 0
  } finally {
    orderLoading.value = false
  }
}

function searchOrders() {
  orderPage.value = 1
  loadOrders()
}
function resetFilters() {
  Object.assign(filters, {
    searchText: '', startDate: '', endDate: '', dakoujing: false,
    lingliaotype: '全部类别', unusedOnly: false, bmid: null,
  })
  searchOrders()
}

async function doExport() {
  await exportWorkOrderStatistics({
    searchText: filters.searchText.trim(),
    startDate: filters.startDate || '', endDate: filters.endDate || '',
    dakoujing: filters.dakoujing ? 'on' : '',
    lingliaotype: typeParam(),
  })
  ElMessage.success('领料统计已导出')
}

function usedRowClass({ row }) {
  return row.IsUsed ? 'row-isused' : ''
}

// 编辑:按工单号回显明细到顶部领料单
async function openEditOrder(row) {
  const res = await getOrderByNo2(row.WorkOrderNo)
  const details = res.details || []
  if (!details.length) {
    ElMessage.warning('该工单没有领料明细，无法编辑')
    return
  }
  fillFromDetails(details, row.WorkOrderNo)
  showAddress('')
  ElMessage.info('已加载到上方领料单，修改后点「提交领料」保存')
}

async function removeOrder(row) {
  if (!dicts.perms.manage) {
    ElMessage.warning('没有删除领料单的权限')
    return
  }
  try {
    await ElMessageBox.confirm('确定要删除该领料工单及其明细吗？库存将自动回滚！', '提示', { type: 'warning' })
  } catch {
    return
  }
  await deleteWorkOrder(row.Id)
  ElMessage.success('已删除')
  if (currentOrderId.value === row.Id) resetEntry(false)
  else {
    loadOrders()
    loadStocks()
  }
}

// ==================== 领料明细弹窗 / 展开明细 ====================
const detailDlg = ref(false)
const detailTitle = ref('工单领料明细')
const detailRows = ref([])
async function showDetailDialog(row) {
  detailTitle.value = `工单 ${row.WorkOrderNo} 领料明细`
  detailRows.value = await getOrderDetails(row.Id)
  detailDlg.value = true
}

const expandRows = reactive({})
async function onExpandChange(row, expandedRows) {
  // Element Plus 的 expand-change 第二参数是「当前展开行数组」,不是布尔值
  const isExpanded = Array.isArray(expandedRows)
    ? expandedRows.some((r) => r.Id === row.Id)
    : !!expandedRows
  if (isExpanded && !expandRows[row.Id]) {
    expandRows[row.Id] = await getOrderDetails(row.Id)
  }
}

// ==================== 外部工单详情抽屉(照搬 jcxt/JcxtManage.vue 的 viewWorkOrder) ====================
// 后端 /workorder/external/info 与 /jcxt/gongdan-info 同一上游服务、同一返回结构;
// 差别只在权限码:这里用 workorder:view,领料用户无需 jcxt:view。
const woDrawer = ref(false)
const woInfo = reactive({
  gongdanhao: '', message: '', loading: false, data: null, images: [],
})
async function openWorkOrderDrawer(row) {
  const no = row.WorkOrderNo
  Object.assign(woInfo, {
    gongdanhao: no || '', message: '', data: null, images: [],
  })
  woDrawer.value = true
  if (!no) {
    woInfo.message = '工单号为空'
    return
  }
  woInfo.loading = true
  try {
    const res = await getExternalWorkOrder(no)
    if (res.success && res.data) {
      woInfo.data = res.data
      try {
        const imgRes = await getExternalImages(res.data.Id || no, no)
        if (imgRes.success) woInfo.images = imgRes.images || []
      } catch { /* 图片失败不影响信息展示 */ }
    } else {
      woInfo.message = res.message || '未获取到工单信息'
    }
  } catch {
    woInfo.message = '接口调用失败'
  } finally {
    woInfo.loading = false
  }
}

// ==================== 附件抽屉 ====================
const attDrawer = ref(false)
const attOrderId = ref(null)
const attOrderNo = ref('')
const attRows = ref([])
const attTotal = ref(0)
const attPage = ref(1)
const attInput = ref(null)
const attFiles = ref([])
const attUploading = ref(false)

async function loadAttachments() {
  if (!attOrderId.value) return
  const data = await listAttachments({
    workorderid: attOrderId.value, page: attPage.value, size: 15,
  })
  attRows.value = data.rows || []
  attTotal.value = data.total || 0
}

function openAttachmentDrawer(row) {
  attOrderId.value = row.Id
  attOrderNo.value = row.WorkOrderNo
  attPage.value = 1
  attFiles.value = []
  attDrawer.value = true
  loadAttachments()
}

function onAttFilesSelected(e) {
  const picked = Array.from(e.target.files || [])
  picked.forEach((f) => attFiles.value.push({ file: f, progress: 0, status: '待上传' }))
  e.target.value = ''
}

async function uploadAllAtt() {
  if (!attFiles.value.length || attUploading.value) return
  attUploading.value = true
  try {
    for (const item of attFiles.value) {
      if (item.status === '完成') continue
      item.status = '上传中'
      try {
        await uploadAttachment(attOrderId.value, item.file, (ev) => {
          item.progress = Math.round((ev.loaded / (ev.total || 1)) * 100)
        })
        item.status = '完成'
        item.progress = 100
      } catch (err) {
        item.status = '失败'
      }
    }
    attFiles.value = attFiles.value.filter((x) => x.status !== '完成')
    await loadAttachments()
    await loadOrders()
    ElMessage.success('附件上传完成')
  } finally {
    attUploading.value = false
  }
}

async function removeAttachment(row) {
  try {
    await ElMessageBox.confirm(`确定删除附件「${row.filename}」？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  await deleteAttachment(row.id)
  ElMessage.success('删除成功')
  await loadAttachments()
  await loadOrders()
}

function downloadAttachment(row) {
  if (row.downloadUrl) window.open(row.downloadUrl, '_blank')
}

function fmtQty(v) {
  const n = parseFloat(v)
  return isNaN(n) ? '0.0' : n.toFixed(1)
}

onMounted(async () => {
  const d = await getWorkOrderDicts()
  Object.assign(dicts, d)
  await Promise.all([loadStocks(), loadOrders()])
  await nextTick()
  fitTables()
  if (typeof ResizeObserver !== 'undefined') {
    tableObserver = new ResizeObserver(fitTables)
    if (stockWrap.value) tableObserver.observe(stockWrap.value)
    if (cartWrap.value) tableObserver.observe(cartWrap.value)
    if (orderWrap.value) tableObserver.observe(orderWrap.value)
  }
  window.addEventListener('resize', onWindowResize)
})

onBeforeUnmount(() => {
  tableObserver?.disconnect()
  window.removeEventListener('resize', onWindowResize)
  clearTimeout(stockTimer)
})
</script>

<template>
  <div class="wo-page">
    <div class="wo-banner">工单领料管理</div>

    <!-- ==================== 领料工单信息 ==================== -->
    <div class="wo-card wo-top-card">
      <div class="wo-card-title">领料工单信息</div>
      <div class="wo-header-row">
        <div class="wo-field">
          <label>工单号</label>
          <el-input ref="noInput" v-model="header.workOrderNo" size="small" clearable
                    placeholder="请输入工单号" style="width: 160px"
                    @blur="onWorkOrderNoBlur" @keyup.enter="$event.target.blur()" />
        </div>
        <div class="wo-field">
          <label>班组</label>
          <el-select v-model="header.banzu" size="small" filterable clearable allow-create
                     default-first-option placeholder="选择班组" style="width: 140px">
            <el-option v-for="b in dicts.banzu" :key="b.id" :label="b.name" :value="b.name" />
          </el-select>
        </div>
        <div class="wo-field">
          <label>领料类别</label>
          <el-select v-model="header.lingliaotype" size="small" filterable clearable
                     placeholder="选择领料类别" style="width: 190px">
            <el-option v-for="t in dicts.lingliaotypes" :key="t" :label="t" :value="t" />
          </el-select>
        </div>
        <div class="wo-field">
          <label>备注</label>
          <el-input v-model="header.beizhu" size="small" clearable style="width: 160px" />
        </div>
        <div class="wo-field">
          <el-input v-model="stockKeyword" size="small" clearable style="width: 200px"
                    placeholder="输材料名称或首字母模糊搜索" @input="onStockKeyword" />
        </div>
        <el-button size="small" :icon="'Refresh'" @click="resetEntry(true)">重置</el-button>
        <el-tag v-if="currentOrderId" type="warning" size="small" effect="plain">
          正在编辑领料单 #{{ currentOrderId }}
        </el-tag>
      </div>
      <div v-if="addressVisible" class="wo-address">
        <span>{{ address }}</span>
        <span class="wo-address-close" @click="addressVisible = false">×</span>
      </div>
    </div>

    <!-- ==================== 左右:材料库存 / 已选材料 ==================== -->
    <div class="wo-split">
      <div class="wo-card">
        <div class="wo-card-title">
          材料库存
          <span class="wo-title-hint">按领用次数排序,数量可输入 1 位小数</span>
        </div>
        <div ref="stockWrap" class="wo-table-wrap">
          <el-table v-loading="stockLoading" :data="stockRows" size="small" border stripe
                    :max-height="stockTableH" row-key="Id">
            <el-table-column prop="MaterialName" label="名称" min-width="90" show-overflow-tooltip />
            <el-table-column v-if="wide" prop="Model" label="型号" min-width="60" align="center" show-overflow-tooltip />
            <el-table-column prop="Spec" label="规格" min-width="70" show-overflow-tooltip />
            <el-table-column label="大口径" width="52" align="center">
              <template #default="{ row }">
                <span v-if="row.dakoujing" class="wo-badge">是</span>
              </template>
            </el-table-column>
            <el-table-column prop="Unit" label="单位" width="44" align="center" />
            <el-table-column label="库存" width="58" align="right">
              <template #default="{ row }">
                <span :class="{ 'wo-low': Number(row.num) < 0 }">{{ fmtQty(row.num) }}</span>
              </template>
            </el-table-column>
            <!-- 列宽需容纳 − / 输入框 / + / 加入 整组(约 127px) + cell 内边距,
                 否则 Element Plus 的 .cell{overflow:hidden} 会把「加入」的「入」裁掉 -->
            <el-table-column label="操作" width="148" align="center">
              <template #default="{ row }">
                <div class="wo-qty-group">
                  <button class="wo-qty-btn" @click="changeStockQty(row, -1)">−</button>
                  <input v-model="stockQty[row.Id]" class="wo-qty-input"
                         @blur="formatStockQty(row)" />
                  <button class="wo-qty-btn" @click="changeStockQty(row, 1)">+</button>
                  <button class="wo-add-btn" @click="addToCart(row)">加入</button>
                </div>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <div class="wo-pager">
          <el-pagination v-model:current-page="stockPage" v-model:page-size="stockSize"
                         :total="stockTotal" :page-sizes="[10, 20, 30]" layout="total, sizes, prev, pager, next"
                         background small @current-change="loadStocks" @size-change="loadStocks" />
        </div>
      </div>

      <div class="wo-card">
        <div class="wo-card-title">
          已选材料（领料单）
          <span class="wo-title-hint">共 {{ cart.length }} 种 / {{ cartTotalQty }} 件</span>
        </div>
        <div ref="cartWrap" class="wo-table-wrap">
          <el-table :data="cart" size="small" border stripe :max-height="cartTableH"
                    empty-text="请从左侧材料库存加入">
            <el-table-column prop="Id" label="材料ID" width="52" align="center" />
            <el-table-column prop="MaterialName" label="名称" min-width="90" show-overflow-tooltip />
            <el-table-column v-if="wide" prop="Model" label="型号" min-width="60" align="center" show-overflow-tooltip />
            <el-table-column prop="Spec" label="规格" min-width="70" show-overflow-tooltip />
            <el-table-column label="数量" width="100" align="center">
              <template #default="{ row }">
                <div class="wo-qty-group">
                  <button class="wo-qty-btn" @click="changeCartQty(row, -1)">−</button>
                  <input v-model="row.Qty" class="wo-qty-input" @blur="formatCartQty(row)" />
                  <button class="wo-qty-btn" @click="changeCartQty(row, 1)">+</button>
                </div>
              </template>
            </el-table-column>
            <el-table-column prop="Unit" label="单位" width="44" align="center" />
            <el-table-column label="操作" width="56" align="center">
              <template #default="{ $index }">
                <el-button link type="danger" size="small" @click="removeCart($index)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
        <div class="wo-cart-actions">
          <el-button size="small" @click="resetEntry(false)">取消</el-button>
          <el-button type="primary" size="small" :loading="submitting" @click="submitEntry">
            提交领料
          </el-button>
        </div>
      </div>
    </div>

    <!-- ==================== 工单列表 ==================== -->
    <div class="wo-card wo-list-card" :class="{ 'wo-fullscreen': fullscreen }">
      <div class="wo-card-title wo-list-title">
        <span>工单列表</span>
        <div class="wo-list-tools">
          <el-select v-model="filters.lingliaotype" size="small" style="width: 180px"
                     @change="searchOrders">
            <el-option v-for="t in dicts.filterTypes" :key="t" :label="t" :value="t" />
          </el-select>
          <el-input v-model="filters.searchText" size="small" clearable style="width: 170px"
                    placeholder="工单号/材料名（回车）" @keyup.enter="searchOrders" />
          <el-date-picker v-model="filters.startDate" type="date" size="small"
                          value-format="YYYY-MM-DD" placeholder="开始日期" style="width: 122px" />
          <el-date-picker v-model="filters.endDate" type="date" size="small"
                          value-format="YYYY-MM-DD" placeholder="结束日期" style="width: 122px" />
          <el-select v-if="dicts.departments.length > 1" v-model="filters.bmid" size="small"
                     clearable placeholder="部门" style="width: 120px" @change="searchOrders">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.bm" :value="d.id" />
          </el-select>
          <el-checkbox v-model="filters.dakoujing" size="small" @change="searchOrders">大口径</el-checkbox>
          <el-button size="small" type="primary" @click="searchOrders">查询</el-button>
          <el-button size="small" @click="resetFilters">重置</el-button>
          <el-checkbox v-model="filters.unusedOnly" size="small" @change="searchOrders">只看未领用</el-checkbox>
          <el-button size="small" @click="doExport">导出Excel</el-button>
          <el-button size="small" text @click="fullscreen = !fullscreen">
            {{ fullscreen ? '还原' : '全屏' }}
          </el-button>
        </div>
      </div>
      <div ref="orderWrap" class="wo-table-wrap">
      <el-table v-loading="orderLoading" :data="orderRows" size="small" border stripe
                :max-height="orderTableH" row-key="Id"
                :row-class-name="usedRowClass" @row-dblclick="showDetailDialog"
                @expand-change="onExpandChange">
        <el-table-column type="expand" width="30">
          <template #default="{ row }">
            <div class="wo-expand">
              <el-table :data="expandRows[row.Id] || []" size="small" border>
                <el-table-column prop="MaterialName" label="材料名称" min-width="150" />
                <el-table-column prop="Model" label="型号" min-width="100" />
                <el-table-column prop="Spec" label="规格" min-width="100" />
                <el-table-column label="大口径" width="80" align="center">
                  <template #default="{ row: d }">
                    <span v-if="d.dakoujing === 'on'" class="wo-badge">是</span>
                  </template>
                </el-table-column>
                <el-table-column label="数量" width="80" align="right">
                  <template #default="{ row: d }">{{ fmtQty(d.Quantity) }}</template>
                </el-table-column>
                <el-table-column prop="Unit" label="单位" width="70" align="center" />
              </el-table>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="Id" label="领料单ID" width="76" align="center" />
        <el-table-column label="工单号" width="95" align="center" show-overflow-tooltip>
          <template #default="{ row }">
            <a class="wo-link" title="点击查看详情" @click="openWorkOrderDrawer(row)">{{ row.WorkOrderNo }}</a>
          </template>
        </el-table-column>
        <el-table-column prop="banzu" label="领料班组" width="90" show-overflow-tooltip />
        <el-table-column prop="lingliaotype" label="领料类别" min-width="140" show-overflow-tooltip />
        <el-table-column prop="beizhu" label="备注" min-width="90" show-overflow-tooltip />
        <el-table-column prop="CreatedTime" label="创建时间" width="140" align="center" />
        <el-table-column v-if="wide" prop="Creator" label="创建人" width="66" align="center" />
        <el-table-column v-if="wide" prop="EditTime" label="修改时间" width="140" align="center" />
        <el-table-column v-if="wide" prop="editor" label="修改人" width="66" align="center" />
        <el-table-column v-if="wide" label="附件" width="52" align="center">
          <template #default="{ row }">
            <a class="wo-link" @click="openAttachmentDrawer(row)">附件{{ row.AttachmentCount ? `(${row.AttachmentCount})` : '' }}</a>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="132" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="openEditOrder(row)">编辑</el-button>
            <el-button link type="danger" size="small" @click="removeOrder(row)">删除</el-button>
            <el-button link size="small" @click="openAttachmentDrawer(row)">附件</el-button>
          </template>
        </el-table-column>
        <el-table-column label="已领用" width="56" align="center" fixed="right">
          <template #default="{ row }">
            <span :class="row.IsUsed ? 'wo-used' : 'wo-unused'">{{ row.IsUsed ? '✔' : '✖' }}</span>
          </template>
        </el-table-column>
      </el-table>
      </div>
      <div class="wo-pager">
        <el-pagination v-model:current-page="orderPage" v-model:page-size="orderSize"
                       :total="orderTotal" :page-sizes="[10, 20, 30, 50]"
                       layout="total, sizes, prev, pager, next" background small
                       @current-change="loadOrders" @size-change="loadOrders" />
      </div>
    </div>

    <!-- ==================== 领料明细弹窗 ==================== -->
    <el-dialog v-model="detailDlg" :title="detailTitle" width="720px" top="8vh">
      <el-table :data="detailRows" size="small" border stripe max-height="440">
        <el-table-column prop="MaterialName" label="材料名称" min-width="180" />
        <el-table-column prop="Spec" label="规格" min-width="140" />
        <el-table-column label="数量" width="100" align="right">
          <template #default="{ row }">{{ fmtQty(row.Quantity) }}</template>
        </el-table-column>
        <el-table-column prop="Unit" label="单位" width="80" align="center" />
        <el-table-column prop="CreatedTime" label="创建时间" width="150" align="center" />
      </el-table>
      <template #footer><el-button size="small" @click="detailDlg = false">关闭</el-button></template>
    </el-dialog>

    <!-- ==================== 外部工单详情抽屉 ==================== -->
    <el-drawer v-model="woDrawer" :title="`工单详情 ${woInfo.gongdanhao}`" size="46%">
      <div v-loading="woInfo.loading" class="wo-body">
        <template v-if="woInfo.data">
          <el-descriptions :column="1" border size="small">
            <el-descriptions-item label="工单号">
              {{ woInfo.data.Id || woInfo.gongdanhao }}
            </el-descriptions-item>
            <el-descriptions-item label="创建时间">
              {{ woInfo.data.createTime || '暂无数据' }}
            </el-descriptions-item>
            <el-descriptions-item label="结束时间">
              {{ woInfo.data.updateTime || '暂无数据' }}
            </el-descriptions-item>
            <el-descriptions-item label="地址">
              {{ woInfo.data.addressStr || '暂无数据' }}
            </el-descriptions-item>
            <el-descriptions-item label="问题描述">
              {{ woInfo.data.problem || '暂无数据' }}
            </el-descriptions-item>
            <el-descriptions-item label="备注">
              {{ woInfo.data.otherDemand || '暂无数据' }}
            </el-descriptions-item>
            <el-descriptions-item label="漏水损坏类型">
              {{ woInfo.data.damageType || '暂无数据' }}
            </el-descriptions-item>
            <el-descriptions-item label="漏水口径">
              {{ woInfo.data.leakageType || '暂无数据' }}
            </el-descriptions-item>
            <el-descriptions-item label="关闭阀门">
              {{ woInfo.data.closeValve || '暂无数据' }}
            </el-descriptions-item>
            <el-descriptions-item label="状态">
              <span :class="woInfo.data.status == 1 ? 'wo-done' : 'wo-doing'">
                {{ woInfo.data.status == 1 ? '已处理' : '处理中' }}
              </span>
            </el-descriptions-item>
          </el-descriptions>
          <div class="wo-image-title">现场图片</div>
          <div v-if="woInfo.images.length" class="wo-image-grid">
            <div v-for="img in woInfo.images" :key="img.kind" class="wo-image-slot">
              <el-image v-if="img.token_url" :src="img.token_url"
                        :preview-src-list="[img.token_url]" fit="cover" class="wo-image" />
              <div v-else class="wo-image wo-image-empty">暂无图片</div>
              <span class="wo-image-label">{{ img.label }}</span>
            </div>
          </div>
          <el-empty v-else :image-size="60" description="暂无现场图片" />
        </template>
        <el-empty v-else :description="woInfo.message || '暂无数据'" />
      </div>
    </el-drawer>

    <!-- ==================== 附件管理抽屉 ==================== -->
    <el-drawer v-model="attDrawer" :title="`工单 ${attOrderNo} 附件`" size="520px">
      <div class="wo-att-bar">
        <input ref="attInput" type="file" multiple style="display: none"
               accept=".pdf,.jpg,.jpeg,.png,.gif,.bmp,.doc,.docx,.xls,.xlsx"
               @change="onAttFilesSelected" />
        <el-button size="small" @click="attInput?.click()">选择文件</el-button>
        <el-button size="small" type="primary" :loading="attUploading"
                   :disabled="!attFiles.length" @click="uploadAllAtt">开始上传</el-button>
        <span class="wo-att-tip">支持 PDF、图片、Word、Excel，单文件 ≤ 50MB</span>
      </div>
      <div v-if="attFiles.length" class="wo-att-queue">
        <div v-for="(f, i) in attFiles" :key="i" class="wo-att-queue-item">
          <span class="wo-att-name">{{ f.file.name }}</span>
          <span>{{ f.status }} {{ f.progress }}%</span>
          <el-button link size="small" @click="attFiles.splice(i, 1)">移除</el-button>
        </div>
      </div>
      <el-table :data="attRows" size="small" border stripe class="wo-att-table">
        <el-table-column prop="filename" label="附件名称" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">
            <a class="wo-link" @click="downloadAttachment(row)">{{ row.filename }}</a>
          </template>
        </el-table-column>
        <el-table-column prop="fileSizeStr" label="大小" width="90" align="center" />
        <el-table-column prop="uploadTime" label="上传时间" width="155" align="center" />
        <el-table-column prop="operator_name" label="上传人" width="90" align="center" />
        <el-table-column label="操作" width="70" align="center">
          <template #default="{ row }">
            <el-button v-if="row.canDelete" link type="danger" size="small"
                       @click="removeAttachment(row)">删除</el-button>
            <span v-else class="wo-muted">—</span>
          </template>
        </el-table-column>
      </el-table>
      <div class="wo-pager">
        <el-pagination v-model:current-page="attPage" :total="attTotal" :page-size="15"
                       layout="total, prev, pager, next" background small
                       @current-change="loadAttachments" />
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
/* 整页按视口高度铺满,由内部 flex 分配三段卡片,页面本身不产生滚动条。
   92px = MainLayout 的 el-header(60px) + el-main 上下 padding(16px*2) */
.wo-page {
  box-sizing: border-box;
  height: calc(100vh - 94px);
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow: hidden;
  background: #fff;
  border-radius: 6px;
  padding: 8px 12px;
}
.wo-banner {
  flex: 0 0 auto;
  background: linear-gradient(90deg, #2c3e6b, #533afd);
  color: #fff;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 1px;
  border-radius: 5px;
  padding: 6px 16px;
}
.wo-page > .wo-top-card {
  flex: 0 0 auto;
}
.wo-card {
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  background: #fff;
  padding: 6px 10px 8px;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
/* 表格外层吃满剩余高度,配合 ResizeObserver 给 el-table 传数值高度 */
.wo-table-wrap {
  flex: 1 1 auto;
  min-height: 0;
  overflow: hidden;
}
.wo-pager {
  flex: 0 0 auto;
}
/* 上方两块高于下方列表;左侧材料库存比右侧领料单稍宽 */
.wo-split {
  flex: 1 1 55%;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(0, 1.15fr) minmax(0, 0.85fr);
  gap: 8px;
}
.wo-list-card {
  flex: 1 1 45%;
  min-height: 0;
}
/* 紧凑行高:10 行 + 表头约 292px,常规视口内两张表都不需要滚动条 */
.wo-page :deep(.el-table--small .el-table__cell) {
  padding: 2px 0;
}
.wo-page :deep(.el-table .cell) {
  line-height: 20px;
  padding: 0 4px;
}
.wo-page :deep(.el-table__header-wrapper th) {
  padding: 3px 0;
}
.wo-split > .wo-card,
.wo-list-card {
  overflow: hidden;
}
@media (max-height: 760px) {
  .wo-banner { padding: 3px 16px; }
  .wo-card-title { margin: 0 0 4px; }
  .wo-page { gap: 5px; }
}
.wo-card-title {
  position: relative;
  font-size: 13px;
  font-weight: 600;
  color: #303133;
  padding-left: 10px;
  margin: 2px 0 8px;
  line-height: 22px;
  display: flex;
  align-items: center;
  gap: 10px;
}
.wo-card-title::before {
  content: '';
  position: absolute;
  left: 0;
  top: 4px;
  bottom: 4px;
  width: 3px;
  border-radius: 2px;
  background: #533afd;
}
.wo-title-hint {
  font-size: 12px;
  font-weight: 400;
  color: #909399;
}
.wo-header-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 12px;
}
.wo-field {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.wo-field label {
  font-size: 12px;
  color: #606266;
  white-space: nowrap;
}
.wo-address {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 6px;
  padding: 4px 10px;
  border-radius: 4px;
  background: #f4f2ff;
  color: #533afd;
  font-size: 12px;
}
.wo-address-close {
  cursor: pointer;
  font-size: 15px;
  line-height: 1;
  padding: 0 4px;
}
.wo-qty-group {
  display: inline-flex;
  align-items: center;
  flex-wrap: nowrap;
  white-space: nowrap;
  gap: 2px;
}
.wo-qty-btn {
  box-sizing: border-box;
  width: 18px;
  height: 22px;
  line-height: 18px;
  border: 1px solid #dcdfe6;
  background: #f5f7fa;
  color: #606266;
  border-radius: 3px;
  cursor: pointer;
  padding: 0;
}
.wo-qty-btn:hover {
  border-color: #533afd;
  color: #533afd;
}
.wo-qty-input {
  box-sizing: border-box;
  width: 42px;
  height: 22px;
  text-align: center;
  border: 1px solid #dcdfe6;
  border-radius: 3px;
  font-size: 12px;
  outline: none;
  padding: 0 2px;
}
.wo-qty-input:focus {
  border-color: #533afd;
}
.wo-add-btn {
  box-sizing: border-box;
  flex: 0 0 auto;
  white-space: nowrap;
  height: 22px;
  margin-left: 3px;
  padding: 0 7px;
  border: 1px solid #533afd;
  border-radius: 3px;
  background: #533afd;
  color: #fff;
  font-size: 12px;
  cursor: pointer;
}
.wo-add-btn:hover {
  background: #6a55ff;
}
.wo-cart-actions {
  flex: 0 0 auto;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 5px;
}
.wo-pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 4px;
}
.wo-badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 12px;
  background: #533afd;
  color: #fff;
  font-size: 11px;
}
.wo-low {
  color: #f56c6c;
  font-weight: 600;
}
.wo-list-title {
  justify-content: space-between;
  flex-wrap: wrap;
}
.wo-list-tools {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
}
.wo-fullscreen {
  position: fixed;
  inset: 8px;
  z-index: 2000;
  margin: 0;
  height: auto;
  background: #fff;
  box-shadow: 0 0 0 2000px rgba(0, 0, 0, 0.35);
  overflow: hidden;
}
.wo-expand {
  padding: 6px 12px;
  background: #fafbff;
}
.wo-link {
  color: #533afd;
  text-decoration: underline;
  cursor: pointer;
}
:deep(.row-isused) {
  background-color: #f6ffed !important;
  color: #333;
}
.wo-used {
  color: #52c41a;
  font-size: 15px;
  font-weight: 700;
}
.wo-unused {
  color: #d9d9d9;
  font-size: 15px;
}
/* 工单详情抽屉:与 jcxt/JcxtManage.vue 的 .wo-* 保持同一套视觉 */
.wo-body {
  min-height: 220px;
}
.wo-image-title {
  margin: 16px 0 8px;
  font-weight: 600;
}
.wo-image-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}
.wo-image-slot {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}
.wo-image {
  width: 100%;
  aspect-ratio: 1;
  border-radius: 6px;
  border: 1px solid var(--el-border-color);
}
.wo-image-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--el-fill-color-lighter);
  color: var(--el-text-color-secondary);
  font-size: 12px;
}
.wo-image-label {
  font-size: 12px;
  color: var(--el-text-color-regular);
}
.wo-done {
  color: var(--el-color-success);
  font-weight: 600;
}
.wo-doing {
  color: var(--el-color-warning);
  font-weight: 600;
}
.wo-muted {
  color: #bbb;
}
.wo-att-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.wo-att-tip {
  color: #909399;
  font-size: 12px;
}
.wo-att-queue {
  border: 1px dashed #dcdfe6;
  border-radius: 4px;
  padding: 4px 8px;
  margin-bottom: 8px;
  max-height: 130px;
  overflow: auto;
}
.wo-att-queue-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  padding: 2px 0;
}
.wo-att-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wo-att-table {
  width: 100%;
}
</style>
