<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  batchDelete,
  batchDeleteBiandong,
  batchInLishi,
  batchUpdate,
  copyToNextYear,
  createWaterFee,
  downloadExport,
  extractToHistory,
  getCopyCount,
  importExcel,
  importHeaders,
  importUpdateExcel,
  listBiandong,
  listDaoruOptions,
  listLogs,
  listRowHistory,
  listWaterFee,
  listYears,
  updateBiandong,
  updateWaterFee,
} from '@/api/waterfee'
import { listDepartments } from '@/api/dept'
import { useAuthStore } from '@/stores/auth'

// 管理员能力(=旧 otherqx 含「特殊群体管理」或「admin」):导入/上传/批量导入历史/删除/复制年度按钮显隐
const auth = useAuthStore()
const canManage = computed(() => auth.hasPerm('waterfee:manage'))

// ===== 列定义(照旧系统 Index.cshtml originalColumns 的顺序与名称) =====
// 优惠起止/保障起止/取消日期按年月展示(旧系统 yyyyMM 口径,后端存当月1号)
const fmtMonth = (row, _col, v) => (v ? String(v).slice(0, 7) : '')
const COLUMNS = [
  { prop: 'bumen', label: '营业所', width: 90 },
  { prop: 'yonghuhao', label: '用户号', width: 90 },
  { prop: 'qitayongshui', label: '其他用水情况', width: 120 },
  { prop: 'shixiang', label: '办理事项', width: 100 },
  { prop: 'xingming', label: '申请人姓名', width: 90 },
  { prop: 'sfz', label: '证件号码', width: 170 },
  { prop: 'juzhudizhi', label: '居住地址', width: 240 },
  { prop: 'dianhua', label: '联系电话', width: 120 },
  { prop: 'ksbriqi', label: '起始保障年月', width: 110, formatter: fmtMonth },
  { prop: 'jsbriqi', label: '截止保障年月', width: 110, formatter: fmtMonth },
  { prop: 'shouliriqi', label: '受理时间', width: 100 },
  { prop: 'youhuiksriqi', label: '优惠开始时间', width: 110, formatter: fmtMonth },
  { prop: 'youhuijsriqi', label: '优惠结束时间', width: 110, formatter: fmtMonth },
  { prop: 'wushuifeihetui', label: '污水费核退时间', width: 120 },
  { prop: 'daoruqingkuang', label: '系统导入情况', width: 120 },
  { prop: 'beizhu', label: '备注', width: 220 },
  { prop: 'fanhuiminzhengju', label: '返民政局', width: 90 },
  { prop: 'guitaishouli', label: '柜台受理情况', width: 120 },
  { prop: 'kaihuming', label: '开户名称', width: 110 },
  { prop: 'yinhangzhanghao', label: '银行账号', width: 170 },
  { prop: 'kaihuhang', label: '开户行', width: 120 },
  { prop: 'kaihushenfenzheng', label: '开户人身份证号码', width: 170 },
  { prop: 'yinhangbeizhu', label: '银行账号备注', width: 120 },
  { prop: 'tekunlei', label: '特困类别', width: 100 },
  { prop: 'gongyangfangshi', label: '供养方式', width: 100 },
  { prop: 'gongyangjigou', label: '供养机构', width: 130 },
  { prop: 'shi', label: '市', width: 60 },
  { prop: 'quxian', label: '区县', width: 80 },
  { prop: 'xiangzhen', label: '乡镇（街道）', width: 100 },
  { prop: 'cun', label: '村(居)', width: 90 },
  { prop: 'caozuo', label: '操作人', width: 90 },
  { prop: 'caozuoriqi', label: '最后操作时间', width: 150 },
  { prop: 'yueshu', label: '优惠月数', width: 80 },
  { prop: 'nd', label: '年度', width: 70 },
  { prop: 'wenjianxuhao', label: '文件序号', width: 80 },
  { prop: 'biaoming', label: '文件表名', width: 110 },
  { prop: 'bm', label: '文件营业所', width: 100 },
  { prop: 'id', label: 'ID', width: 60 },
  { prop: 'quxiaoriqi', label: '取消日期', width: 100, formatter: fmtMonth },
]
// 照旧系统:未保存过列设置时默认显示全部列
const DEFAULT_COLS = COLUMNS.map((c) => c.prop)
const _savedCols = JSON.parse(localStorage.getItem('waterfee_cols') || 'null')
// 兼容旧存档:原"营业所"列 prop 为 bm,已拆为 bumen(部门)+bm(文件营业所)
if (Array.isArray(_savedCols) && _savedCols.includes('bm') && !_savedCols.includes('bumen')) {
  _savedCols.splice(_savedCols.indexOf('bm'), 0, 'bumen')
  localStorage.setItem('waterfee_cols', JSON.stringify(_savedCols))
}
const shownCols = ref(_savedCols || [...DEFAULT_COLS])
const colDialog = ref(false)
const colDraft = ref([])
const colSearch = ref('')

function openColDialog() {
  colSearch.value = ''
  colDraft.value = [...shownCols.value]
  colDialog.value = true
}

const colUnselected = computed(() =>
  COLUMNS.filter((c) => !colDraft.value.includes(c.prop) && colLabel(c.prop).toLowerCase().includes(colSearch.value.toLowerCase()))
)
const colDraftFiltered = computed(() =>
  colDraft.value.filter((p) => colLabel(p).toLowerCase().includes(colSearch.value.toLowerCase()))
)
const colLabel = (prop) => COLUMNS.find((c) => c.prop === prop)?.label ?? prop

function toggleCol(prop, checked) {
  if (checked) colDraft.value.push(prop)
  else colDraft.value = colDraft.value.filter((x) => x !== prop)
}
function moveCol(i, dir) {
  const arr = [...colDraft.value]
  const [item] = arr.splice(i, 1)
  arr.splice(i + dir, 0, item)
  colDraft.value = arr
}
function selectAllCols() {
  COLUMNS.forEach((c) => {
    if (!colDraft.value.includes(c.prop)) colDraft.value.push(c.prop)
  })
}
function unselectAllCols() {
  colDraft.value = []
}
function resetCols() {
  colDraft.value = [...DEFAULT_COLS]
}
function saveCols() {
  if (!colDraft.value.length) {
    ElMessage.warning('请至少选择一列显示')
    return
  }
  shownCols.value = colDraft.value.filter((prop) => COLUMNS.some((c) => c.prop === prop))
  localStorage.setItem('waterfee_cols', JSON.stringify(shownCols.value))
  colDialog.value = false
}
const visibleColumns = computed(() => COLUMNS.filter((c) => shownCols.value.includes(c.prop)))

// ===== 筛选(照旧系统工具栏:搜索/年度/导入情况/其他用水/有无用户号/部门/取消/重复身份证/返民政) =====
const ndSel = ref([])
const yearOptions = ref([])
const mohu = ref('')
const qitaSel = ref([])
const daoruSel = ref([])
const yhhSel = ref('')
const deptSel = ref(null)
const deptOptions = ref([])
const fanmin = ref(false)
const showQuxiao = ref(false)
const dupSfz = ref(false)
const daoruOptions = ref([])
// 其他用水情况预设(照旧系统编辑弹窗/批量修改下拉 13 项)
const QITA_PRESETS = [
  '总表', '自备水源', '养老院/老人院', '医院', '人饮工程', '安兜供水', '舫山供水',
  '其他非我司供水区域', '外地', '已过世', '集中供养', '住校', '自愿放弃',
]
const page = ref(1)
const size = ref(20)
const total = ref(0)
const rows = ref([])
const loading = ref(false)
const selection = ref([])
const tableRef = ref()

const queryParams = computed(() => {
  // 空值不传参,避免后端空串解析 422
  const p = {
    nd: ndSel.value.join(','),
    mohu: mohu.value,
    yhh: yhhSel.value,
    fanmin: fanmin.value,
    show_quxiao: showQuxiao.value,
    dup_sfz: dupSfz.value,
  }
  if (deptSel.value) p.bmid = deptSel.value
  if (qitaSel.value.length) p.qitayongshui = qitaSel.value.join(',')
  if (daoruSel.value.length) p.daoruqingkuang = daoruSel.value.join(',')
  return p
})

async function load() {
  if (!ndSel.value.length) {
    ElMessage.warning('请先选择年度')
    return
  }
  loading.value = true
  try {
    const data = await listWaterFee({ page: page.value, size: size.value, ...queryParams.value })
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

function clearSelect() {
  tableRef.value?.clearSelection()
}

onMounted(async () => {
  yearOptions.value = await listYears()
  daoruOptions.value = await listDaoruOptions()
  deptOptions.value = await listDepartments().catch(() => [])
})

// ===== 行展开:变动历史 =====
const historyCache = reactive({})
async function expandHistory(row, expanded) {
  if (!expanded.length) return
  historyCache[row.id] = { loading: true, rows: [] }
  historyCache[row.id].rows = await listRowHistory(row.id)
  historyCache[row.id].loading = false
}

// ===== 查看记录(修改日志;主表与变动表共用,source 区分) =====
const logDialog = ref(false)
const logRows = ref([])
const logTitle = ref('查看记录')
async function openLogs(id, source = 'shuifeixitong') {
  logRows.value = await listLogs(id, source)
  logTitle.value = `查看记录 - ${source === 'shuifeixitong' ? '记录' : '变动记录'} #${id}`
  logDialog.value = true
}

// ===== 新增 / 编辑(照旧系统五页签编辑弹窗) =====
const editDialog = ref(false)
const editingId = ref(null)
const editFormRef = ref()
const editTab = ref('input')
const blankForm = () => ({
  nd: null, shi: '', quxian: '', xiangzhen: '', cun: '', shixiang: '', xingming: '', sfz: '',
  juzhudizhi: '', dianhua: '', kaihuming: '', yinhangzhanghao: '', kaihuhang: '',
  kaihushenfenzheng: '', yinhangbeizhu: '', ksbriqi: '', jsbriqi: '', tekunlei: '',
  gongyangfangshi: '', gongyangjigou: '', bm: '', bmid: null, yonghuhao: '', qitayongshui: '',
  beizhu: '', shouliriqi: '', youhuiksriqi: '', youhuijsriqi: '', wushuifeihetui: '',
  daoruqingkuang: '', fanhuiminzhengju: '否', guitaishouli: '', yueshu: null, quxiaoriqi: '',
})
const editForm = reactive(blankForm())
const editRules = { yonghuhao: [{ required: true, message: '请输入用户号', trigger: 'blur' }] }
const editFormFields = [
  'nd', 'yonghuhao', 'shixiang', 'xingming', 'sfz', 'dianhua', 'juzhudizhi',
  'shi', 'quxian', 'xiangzhen', 'cun', 'qitayongshui', 'beizhu',
  'youhuiksriqi', 'youhuijsriqi', 'yueshu', 'shouliriqi', 'wushuifeihetui',
  'guitaishouli', 'daoruqingkuang', 'fanhuiminzhengju', 'ksbriqi', 'jsbriqi',
  'tekunlei', 'gongyangfangshi', 'gongyangjigou', 'bm', 'bmid', 'kaihuming',
  'yinhangzhanghao', 'kaihuhang', 'kaihushenfenzheng', 'yinhangbeizhu', 'quxiaoriqi',
]
const FIELD_LABELS = {
  nd: '年度', yonghuhao: '用户号', shixiang: '办理事项', xingming: '申请人姓名', sfz: '证件号码',
  dianhua: '联系电话', juzhudizhi: '居住地址', shi: '省/市', quxian: '区县', xiangzhen: '乡镇（街道）',
  cun: '村(居)', qitayongshui: '其他用水情况', beizhu: '备注', youhuiksriqi: '优惠开始时间',
  youhuijsriqi: '优惠结束时间', yueshu: '优惠月数', shouliriqi: '受理时间',
  wushuifeihetui: '污水费核退时间', guitaishouli: '柜台受理情况', daoruqingkuang: '系统导入情况',
  fanhuiminzhengju: '返民政局', ksbriqi: '起始保障年月', jsbriqi: '截止保障年月', tekunlei: '特困类别',
  gongyangfangshi: '供养方式', gongyangjigou: '供养机构', bm: '营业所', bmid: '营业所', kaihuming: '开户名称',
  yinhangzhanghao: '银行账号', kaihuhang: '开户行', kaihushenfenzheng: '开户人身份证号码',
  yinhangbeizhu: '银行账号备注', quxiaoriqi: '取消日期',
}
const DATE_FORM_FIELDS = ['ksbriqi', 'jsbriqi', 'youhuiksriqi', 'youhuijsriqi', 'wushuifeihetui', 'shouliriqi', 'quxiaoriqi']

// 优惠月数实时计算(照旧 calcMonths:起止相差月数 +1)
watch(
  () => [editForm.youhuiksriqi, editForm.youhuijsriqi],
  ([s, e]) => {
    if (!s || !e) {
      editForm.yueshu = null
      return
    }
    const sy = +String(s).slice(0, 4), sm = +String(s).slice(5, 7)
    const ey = +String(e).slice(0, 4), em = +String(e).slice(5, 7)
    editForm.yueshu = Math.max(0, (ey - sy) * 12 + (em - sm) + 1)
  }
)

// 自动填优惠时间(照旧 GetYouhuiTime:开始=下个月,结束=明年1月)
function autoFillYouhuiTime() {
  const now = new Date()
  const start = new Date(now.getFullYear(), now.getMonth() + 1, 1)
  const end = new Date(now.getFullYear() + 1, 0, 1)
  const fmt = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-01`
  editForm.youhuiksriqi = fmt(start)
  editForm.youhuijsriqi = fmt(end)
  ElMessage.success('优惠开始结束已设置成功')
}

function buildPayload() {
  const p = {}
  for (const f of editFormFields) {
    const v = editForm[f]
    p[f] = v === '' ? null : v
  }
  return p
}

function openCreate() {
  editingId.value = null
  editTab.value = 'input'
  Object.assign(editForm, blankForm())
  editForm.nd = ndSel.value[0] || yearOptions.value[0] || null
  editForm.shouliriqi = new Date().toISOString().slice(0, 10)
  editDialog.value = true
}

function openEdit(row) {
  editingId.value = row.id
  editTab.value = 'input'
  Object.assign(editForm, blankForm())
  for (const f of editFormFields) editForm[f] = row[f] ?? ''
  if (!editForm.fanhuiminzhengju) editForm.fanhuiminzhengju = '否'
  editDialog.value = true
}

async function submitEdit() {
  await editFormRef.value.validate()
  if (editingId.value == null) {
    await createWaterFee(buildPayload())
    ElMessage.success('已新增')
  } else {
    const r = await updateWaterFee(editingId.value, buildPayload())
    ElMessage.success(`已保存,变更 ${r.log_added} 处`)
  }
  editDialog.value = false
  load()
}

// 提取当前信息到历史记录(照旧:快照的是编辑弹窗表单当前值,不是库里的旧值)
async function extractCurrent() {
  if (editingId.value == null) return
  const r = await extractToHistory([editingId.value], {
    yonghuhao: editForm.yonghuhao,
    qitayongshui: editForm.qitayongshui,
    beizhu: editForm.beizhu,
    shouliriqi: editForm.shouliriqi || null,
    juzhudizhi: editForm.juzhudizhi,
    daoruqingkuang: editForm.daoruqingkuang,
    fanhuiminzhengju: editForm.fanhuiminzhengju,
    guitaishouli: editForm.guitaishouli,
    yueshu: editForm.yueshu,
    youhuiksriqi: editForm.youhuiksriqi || null,
    youhuijsriqi: editForm.youhuijsriqi || null,
    wushuifeihetui: editForm.wushuifeihetui || null,
  })
  ElMessage.success(r.message)
}

// ===== 批量操作 =====
function requireSelection() {
  if (!selection.value.length) {
    ElMessage.warning('请先勾选记录')
    return false
  }
  return true
}

async function removeBatch() {
  if (!requireSelection()) return
  try {
    await ElMessageBox.confirm(`确定要删除这 ${selection.value.length} 条记录吗？其变动历史与日志一并删除,删除后不可恢复！`, '确认删除', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const r = await batchDelete(selection.value.map((r) => r.id))
  ElMessage.success(r.message)
  load()
}

async function doExtract() {
  if (!requireSelection()) return
  const r = await extractToHistory(selection.value.map((r) => r.id))
  ElMessage.success(r.message)
}

async function doBatchInLishi() {
  if (!requireSelection()) return
  const r = await batchInLishi(selection.value.map((r) => r.id))
  ElMessage.success(r.message)
}

// ===== 批量修改(照旧 dlgBatch:5 个预设字段,其他用水用下拉,返民政是/否,备注追加不覆盖) =====
const batchDialog = ref(false)
const batchField = ref('')
const batchValue = ref('')
const BATCH_FIELDS = [
  { value: 'beizhu', label: '备注(追加,不覆盖)' },
  { value: 'qitayongshui', label: '其他用水情况' },
  { value: 'fanhuiminzhengju', label: '返民政局(是/否)' },
  { value: 'guitaishouli', label: '柜台受理情况' },
  { value: 'daoruqingkuang', label: '系统导入情况' },
]
function openBatch() {
  if (!requireSelection()) return
  batchField.value = ''
  batchValue.value = ''
  batchDialog.value = true
}

async function submitBatch() {
  if (!batchField.value) {
    ElMessage.warning('请选择要修改的列')
    return
  }
  if (!batchValue.value) {
    ElMessage.warning('请输入或选择要更新的内容')
    return
  }
  try {
    await ElMessageBox.confirm(`确定要批量修改这 ${selection.value.length} 条数据吗？`, '确认', {
      type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const r = await batchUpdate(
    selection.value.map((row) => row.id),
    { [batchField.value]: batchValue.value }
  )
  ElMessage.success(r.message)
  batchDialog.value = false
  load()
}

// ===== 导入新增 / 上传更新(选文件后解析表头,自定义导入哪些列) =====
const importDialog = ref(false)
// 照旧 UploadE:勾选取消导入 → 存取消名单表并回写主表取消日期(一个开关即可)
const importForm = reactive({ nd: null, isQuxiao: false, quxiaoriqi: '', file: null })
const updateDialog = ref(false)
const updateForm = reactive({ nd: null, file: null })
// 列选择:parsedCols=[{header,field}],checkedCols=勾选的中文表头
const parsedCols = ref([])
const checkedCols = ref([])
const parseLoading = ref(false)
const sheetNames = ref([])

async function onFileChange(file, form) {
  form.file = file
  if (!file) return
  // 自动解析表头,勾选所有系统认识的列(身份证必选,照旧系统)
  parseLoading.value = true
  parsedCols.value = []
  checkedCols.value = []
  sheetNames.value = []
  try {
    const data = await importHeaders(file)
    sheetNames.value = data.sheets.map((s) => s.name)
    parsedCols.value = data.columns
    checkedCols.value = data.columns
      .filter((c) => c.field && c.field !== 'quxiaoriqi')
      .map((c) => c.header)
  } finally {
    parseLoading.value = false
  }
}

function isSfzCol(c) {
  return c.field === 'sfz'
}

function checkAllParsedCols(flag) {
  const names = parsedCols.value.filter((c) => c.field && !isSfzCol(c)).map((c) => c.header)
  checkedCols.value = flag
    ? Array.from(new Set([...checkedCols.value, ...names]))
    : checkedCols.value.filter((h) => isSfzCol(parsedCols.value.find((c) => c.header === h)))
}

function onImportFile(e) {
  const f = e.target.files[0] || null
  e.target.value = '' // 立即清空,允许重复选择同一个文件
  onFileChange(f, importForm)
}

function onUpdateFile(e) {
  const f = e.target.files[0] || null
  e.target.value = ''
  onFileChange(f, updateForm)
}

function openImport() {
  Object.assign(importForm, { nd: ndSel.value[0] || null, isQuxiao: false, quxiaoriqi: '', file: null })
  parsedCols.value = []
  checkedCols.value = []
  sheetNames.value = []
  importDialog.value = true
}

function openUpdateDialog() {
  Object.assign(updateForm, { nd: ndSel.value[0] || null, file: null })
  parsedCols.value = []
  checkedCols.value = []
  sheetNames.value = []
  updateDialog.value = true
}

async function submitImport() {
  if (!importForm.nd) return ElMessage.warning('请选择年度')
  if (!importForm.file) return ElMessage.warning('请选择 Excel 文件')
  if (importForm.isQuxiao && !importForm.quxiaoriqi) {
    return ElMessage.warning('勾选导入取消数据时必须选择取消年月')
  }
  loading.value = true
  try {
    const r = await importExcel(importForm.file, importForm.nd, {
      isQuxiao: importForm.isQuxiao,
      quxiaoriqi: importForm.quxiaoriqi || null,
      selectedCols: checkedCols.value.map((h) => parsedCols.value.find((c) => c.header === h)?.field).filter(Boolean),
    })
    ElMessage.success(
      importForm.isQuxiao
        ? `取消导入完成:取消名单新增 ${r.cancel_inserted},查重跳过 ${r.skipped_dup},回写主表 ${r.cancel_marked} 条`
        : `导入完成:新增 ${r.added},查重跳过 ${r.skipped_dup}`
    )
    importDialog.value = false
    load()
  } finally {
    loading.value = false
  }
}

async function submitUpdate() {
  if (!updateForm.nd) return ElMessage.warning('请选择年度')
  if (!updateForm.file) return ElMessage.warning('请选择 Excel 文件')
  loading.value = true
  try {
    const r = await importUpdateExcel(updateForm.file, updateForm.nd, checkedCols.value.map((h) => parsedCols.value.find((c) => c.header === h)?.field).filter(Boolean))
    ElMessage.success(`更新完成:成功 ${r.updated},未匹配 ${r.not_found}`)
    updateDialog.value = false
    load()
  } finally {
    loading.value = false
  }
}

// ===== 复制到下一年度 =====
async function doCopyYear() {
  const nd = ndSel.value[0]
  if (!nd) return ElMessage.warning('请先选择单个年度')
  const info = await getCopyCount(nd)
  if (!info.count) return ElMessage.info(`【${nd}年】没有可复制的数据`)
  try {
    await ElMessageBox.confirm(
      `将从【${nd}年】复制 ${info.count} 条【未取消】记录到【${info.target_nd}年】,是否继续？`,
      '确认操作',
      { type: 'warning', confirmButtonText: '复制', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  const r = await copyToNextYear(nd)
  ElMessage.success(r.message)
}

// ===== 导出 =====
async function doExport(kind) {
  const names = { full: '水费全量导出', simplified: '水费简化导出', report: '匹配率报表', ls: '变动历史导出' }
  await downloadExport(kind, queryParams.value, `${names[kind]}_${Date.now()}.xlsx`)
  ElMessage.success('已导出')
}

// ===== 历史 Tab(照旧"历史表":独立年度筛选 + 查看记录 + 双击编辑) =====
const activeTab = ref('main')
const bdRows = ref([])
const bdTotal = ref(0)
const bdPage = ref(1)
const bdLoading = ref(false)
const bdSelection = ref([])
const bdNdSel = ref([])
const bdMohu = ref('')
const bdDeptSel = ref(null)
const bdEditDialog = ref(false)
const bdEditingId = ref(null)
const blankBdForm = () => ({
  yonghuhao: '', qitayongshui: '', beizhu: '', yueshu: null, juzhudizhi: '',
  daoruqingkuang: '', guitaishouli: '', fanhuiminzhengju: '否',
  youhuiksriqi: '', youhuijsriqi: '', wushuifeihetui: '', shoulishijian: '',
})
const bdForm = reactive(blankBdForm())

watch(
  () => [bdForm.youhuiksriqi, bdForm.youhuijsriqi],
  ([s, e]) => {
    if (!s || !e) {
      bdForm.yueshu = null
      return
    }
    const sy = +String(s).slice(0, 4), sm = +String(s).slice(5, 7)
    const ey = +String(e).slice(0, 4), em = +String(e).slice(5, 7)
    bdForm.yueshu = Math.max(0, (ey - sy) * 12 + (em - sm) + 1)
  }
)

async function loadBiandong() {
  bdLoading.value = true
  try {
    const params = {
      page: bdPage.value,
      size: 20,
      nd: bdNdSel.value.join(','),
      mohu: bdMohu.value,
    }
    if (bdDeptSel.value) params.bmid = bdDeptSel.value
    const data = await listBiandong(params)
    bdRows.value = data.items
    bdTotal.value = data.total
  } finally {
    bdLoading.value = false
  }
}

function bdSearch() {
  bdPage.value = 1
  loadBiandong()
}

function openBdEdit(row) {
  bdEditingId.value = row.id
  Object.assign(bdForm, blankBdForm())
  for (const k of Object.keys(bdForm)) bdForm[k] = row[k] ?? bdForm[k]
  if (!bdForm.fanhuiminzhengju) bdForm.fanhuiminzhengju = '否'
  bdEditDialog.value = true
}

async function submitBdEdit() {
  const payload = {}
  for (const k of Object.keys(bdForm)) {
    const v = bdForm[k]
    payload[k] = v === '' ? null : v
  }
  const r = await updateBiandong(bdEditingId.value, payload)
  ElMessage.success(`已保存,变更 ${r.log_added} 处`)
  bdEditDialog.value = false
  loadBiandong()
}

async function removeBdBatch() {
  if (!bdSelection.value.length) return ElMessage.warning('请先勾选变动记录')
  try {
    await ElMessageBox.confirm(`确定要删除这 ${bdSelection.value.length} 条变动记录吗？`, '确认删除', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
  } catch {
    return
  }
  const r = await batchDeleteBiandong(bdSelection.value.map((r) => r.id))
  ElMessage.success(r.message)
  loadBiandong()
}
</script>

<template>
  <el-card>
    <el-tabs v-model="activeTab" @tab-change="(t) => t === 'history' && loadBiandong()">
      <!-- 主表 Tab -->
      <el-tab-pane label="特殊群体信息主表" name="main">
        <div class="toolbar">
          <el-input
            v-model="mohu"
            placeholder="输入关键字搜索"
            clearable
            style="width: 200px"
            @keyup.enter="search"
            @clear="search"
          />
          <el-select v-model="ndSel" multiple collapse-tags collapse-tags-tooltip placeholder="年度(必选)" style="width: 160px" @change="search">
            <el-option v-for="y in yearOptions" :key="y" :value="y" :label="y + '年'" />
          </el-select>
          <el-select v-model="daoruSel" multiple collapse-tags collapse-tags-tooltip filterable placeholder="系统导入情况" style="width: 160px" @change="search">
            <el-option-group v-for="g in daoruOptions" :key="g.nd" :label="g.nd + '年'">
              <el-option v-for="v in g.values" :key="v" :value="v" :label="v" />
            </el-option-group>
          </el-select>
          <el-select v-model="qitaSel" multiple collapse-tags collapse-tags-tooltip filterable placeholder="其他用水情况" style="width: 160px" @change="search">
            <el-option label="(空)" value="__empty__" />
            <el-option v-for="v in QITA_PRESETS" :key="v" :value="v" :label="v" />
          </el-select>
          <el-select v-model="yhhSel" placeholder="用户号" clearable style="width: 110px" @change="search">
            <el-option label="有用户号" value="有" />
            <el-option label="无用户号" value="无" />
          </el-select>
          <el-select v-model="deptSel" placeholder="选择部门" clearable filterable style="width: 130px" @change="search">
            <el-option v-for="d in deptOptions" :key="d.id" :value="d.id" :label="d.name" />
          </el-select>
          <el-checkbox v-model="showQuxiao" @change="search">显示取消数据</el-checkbox>
          <el-checkbox v-model="dupSfz" @change="search">重复身份证</el-checkbox>
          <el-divider direction="vertical" />
          <span class="switch-label">返民政</span>
          <el-switch v-model="fanmin" active-text="是" @change="search" />
          <el-button type="primary" @click="search">查询</el-button>
        </div>
        <div class="toolbar">
          <el-button size="small" @click="openColDialog">显示列</el-button>
          <el-button size="small" @click="clearSelect">取消选中</el-button>
          <el-button size="small" :disabled="!selection.length" @click="openBatch">批量修改</el-button>
          <el-button size="small" plain @click="doExport('full')">导出</el-button>
          <el-button size="small" plain @click="doExport('report')">导出报表</el-button>
          <el-button v-if="canManage" size="small" plain @click="doCopyYear">复制到下年度</el-button>
          <el-button v-if="canManage" size="small" type="danger" plain :disabled="!selection.length" @click="removeBatch">批量删除</el-button>
          <el-button v-if="canManage" size="small" type="success" plain @click="openImport">导入新增</el-button>
          <el-button v-if="canManage" size="small" :disabled="!selection.length" @click="doBatchInLishi">批量导入历史</el-button>
          <el-button v-if="canManage" size="small" type="success" plain @click="openUpdateDialog">上传更新</el-button>
          <el-divider v-if="canManage" direction="vertical" />
          <el-button size="small" type="primary" plain @click="openCreate">新增</el-button>
          <el-button size="small" :disabled="!selection.length" @click="openEdit(selection[0])">编辑</el-button>
          <el-button size="small" :disabled="!selection.length" @click="doExtract">提取到历史</el-button>
          <el-button size="small" plain @click="doExport('simplified')">简化导出</el-button>
        </div>

        <el-table
          ref="tableRef"
          v-loading="loading"
          :data="rows"
          stripe
          :row-class-name="({ row }) => (row.quxiaoriqi ? 'row-cancelled' : '')"
          @selection-change="(s) => (selection = s)"
          @expand-change="expandHistory"
          @row-dblclick="(row) => openEdit(row)"
        >
          <el-table-column type="selection" width="42" />
          <el-table-column type="expand" width="40">
            <template #default="{ row }">
              <div v-loading="historyCache[row.id]?.loading" style="padding: 8px 24px">
                <el-table v-if="historyCache[row.id]" :data="historyCache[row.id].rows" size="small" border>
                  <el-table-column prop="biandongriqi" label="变动日期" width="160" />
                  <el-table-column prop="yonghuhao" label="用户号" width="100" />
                  <el-table-column prop="qitayongshui" label="其他用水情况" min-width="110" />
                  <el-table-column prop="youhuiksriqi" label="优惠开始时间" width="100" :formatter="fmtMonth" />
                  <el-table-column prop="youhuijsriqi" label="优惠结束时间" width="100" :formatter="fmtMonth" />
                  <el-table-column prop="yueshu" label="优惠月数" width="80" />
                  <el-table-column prop="beizhu" label="备注" min-width="140" />
                  <el-table-column prop="daoruqingkuang" label="系统导入情况" min-width="120" />
                  <el-table-column prop="caozuo" label="操作人" width="90" />
                </el-table>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="查看记录" width="100" fixed="left">
            <template #default="{ row }">
              <el-button link size="small" :type="row.log_count ? 'danger' : 'info'" @click="openLogs(row.id)">
                {{ row.log_count ? `查看记录(${row.log_count})` : '查看记录' }}
              </el-button>
            </template>
          </el-table-column>
          <el-table-column v-for="c in visibleColumns" :key="c.prop" :prop="c.prop" :label="c.label" :width="c.width" :formatter="c.formatter" show-overflow-tooltip />
          <el-table-column label="操作" width="80" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click.stop="openEdit(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-pagination
          v-model:current-page="page"
          v-model:page-size="size"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          style="margin-top: 14px; justify-content: flex-end"
          @current-change="load"
          @size-change="search"
        />
      </el-tab-pane>

      <!-- 历史 Tab -->
      <el-tab-pane label="历史表" name="history">
        <div class="toolbar">
          <el-input v-model="bdMohu" placeholder="请输入关键字搜索" clearable style="width: 200px" @keyup.enter="bdSearch" @clear="bdSearch" />
          <el-select v-model="bdNdSel" multiple collapse-tags collapse-tags-tooltip placeholder="主表年度" clearable style="width: 150px" @change="bdSearch">
            <el-option v-for="y in yearOptions" :key="y" :value="y" :label="y + '年'" />
          </el-select>
          <el-select v-model="bdDeptSel" placeholder="选择部门" clearable filterable style="width: 130px" @change="bdSearch">
            <el-option v-for="d in deptOptions" :key="d.id" :value="d.id" :label="d.name" />
          </el-select>
          <el-button type="primary" @click="bdSearch">查询</el-button>
          <div class="spacer" />
          <el-button size="small" type="danger" plain :disabled="!bdSelection.length" @click="removeBdBatch">批量删除</el-button>
          <el-button size="small" plain @click="doExport('ls')">导出EXCEL</el-button>
        </div>
        <el-table
          v-loading="bdLoading"
          :data="bdRows"
          stripe
          size="small"
          @selection-change="(s) => (bdSelection = s)"
          @row-dblclick="(row) => openBdEdit(row)"
        >
          <el-table-column type="selection" width="42" />
          <el-table-column label="查看记录" width="100">
            <template #default="{ row }">
              <el-button link size="small" :type="row.has_log ? 'danger' : 'info'" @click="openLogs(row.id, 'shuifeixitongbiandong')">查看记录</el-button>
            </template>
          </el-table-column>
          <el-table-column label="部门(主表信息)" width="110">
            <template #default="{ row }">{{ row.main?.bm ?? '' }}</template>
          </el-table-column>
          <el-table-column label="主表年度" width="80">
            <template #default="{ row }">{{ row.main?.nd ?? '' }}</template>
          </el-table-column>
          <el-table-column prop="yonghuhao" label="用户号" width="100" />
          <el-table-column label="申请人姓名(主表信息)" width="120">
            <template #default="{ row }">{{ row.main?.xingming ?? '' }}</template>
          </el-table-column>
          <el-table-column prop="juzhudizhi" label="居住地址" min-width="160" show-overflow-tooltip />
          <el-table-column prop="qitayongshui" label="其他用水情况" width="110" show-overflow-tooltip />
          <el-table-column prop="beizhu" label="备注" min-width="140" show-overflow-tooltip />
          <el-table-column prop="shoulishijian" label="受理时间" width="100" />
          <el-table-column label="证件号码(主表信息)" width="170">
            <template #default="{ row }">{{ row.main?.sfz ?? '' }}</template>
          </el-table-column>
          <el-table-column prop="youhuiksriqi" label="优惠开始时间" width="100" :formatter="fmtMonth" />
          <el-table-column prop="youhuijsriqi" label="优惠结束时间" width="100" :formatter="fmtMonth" />
          <el-table-column prop="yueshu" label="优惠月数" width="80" />
          <el-table-column prop="wushuifeihetui" label="污水费核退时间" width="110" />
          <el-table-column prop="daoruqingkuang" label="系统导入情况" width="120" show-overflow-tooltip />
          <el-table-column prop="fanhuiminzhengju" label="返民政局" width="90" />
          <el-table-column prop="guitaishouli" label="柜台受理情况" width="110" show-overflow-tooltip />
          <el-table-column prop="caozuo" label="操作员" width="90" />
          <el-table-column prop="biandongriqi" label="操作日期" width="160" />
          <el-table-column prop="id" label="记录ID" width="80" />
          <el-table-column label="操作" width="80" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="openBdEdit(row)">编辑</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-pagination
          v-model:current-page="bdPage"
          :total="bdTotal"
          :page-size="20"
          layout="total, prev, pager, next"
          style="margin-top: 14px; justify-content: flex-end"
          @current-change="loadBiandong"
        />
      </el-tab-pane>
    </el-tabs>
  </el-card>

  <!-- 新增 / 编辑:照旧系统五页签 -->
  <el-dialog v-model="editDialog" :title="editingId == null ? '新增记录' : '编辑信息'" width="640px" top="3vh">
    <el-form ref="editFormRef" :model="editForm" :rules="editRules" label-width="130px" size="small">
      <el-tabs v-model="editTab">
        <!-- 录入信息 -->
        <el-tab-pane label="录入信息" name="input">
          <el-form-item label="用户号" prop="yonghuhao">
            <el-input v-model="editForm.yonghuhao" style="width: 60%" />
            <el-button type="success" size="small" style="margin-left: 10px" @click="autoFillYouhuiTime">自动填优惠时间</el-button>
          </el-form-item>
          <el-form-item label="其他用水情况">
            <el-select v-model="editForm.qitayongshui" clearable style="width: 100%">
              <el-option v-for="v in QITA_PRESETS" :key="v" :value="v" :label="v" />
            </el-select>
          </el-form-item>
          <el-form-item label="备注">
            <el-input v-model="editForm.beizhu" type="textarea" :rows="2" />
          </el-form-item>
          <el-form-item label="受理时间">
            <el-input v-model="editForm.shouliriqi" readonly placeholder="后台自动默认当前日期" />
          </el-form-item>
          <el-form-item label="优惠开始时间">
            <el-date-picker v-model="editForm.youhuiksriqi" type="month" value-format="YYYY-MM-DD" style="width: 100%" />
          </el-form-item>
          <el-form-item label="优惠结束时间">
            <el-date-picker v-model="editForm.youhuijsriqi" type="month" value-format="YYYY-MM-DD" style="width: 100%" />
          </el-form-item>
          <el-form-item label="优惠月数">
            <el-input-number v-model="editForm.yueshu" :min="0" readonly style="width: 100%" />
          </el-form-item>
          <el-form-item label="污水费核退时间">
            <el-date-picker v-model="editForm.wushuifeihetui" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
          </el-form-item>
          <el-form-item label="系统导入情况">
            <el-input v-model="editForm.daoruqingkuang" />
          </el-form-item>
          <el-form-item label="返民政局">
            <el-switch v-model="editForm.fanhuiminzhengju" active-text="是" inactive-text="否" active-value="是" inactive-value="否" />
          </el-form-item>
          <el-form-item label="柜台受理情况">
            <el-input v-model="editForm.guitaishouli" />
          </el-form-item>
          <el-form-item v-if="editingId != null" label="">
            <el-button type="success" @click="extractCurrent">提取当前信息到历史记录</el-button>
          </el-form-item>
        </el-tab-pane>

        <!-- 民政局可变信息 -->
        <el-tab-pane label="民政局可变信息" name="mzvar">
          <el-form-item label="居住地址"><el-input v-model="editForm.juzhudizhi" /></el-form-item>
          <el-form-item label="联系电话"><el-input v-model="editForm.dianhua" /></el-form-item>
          <el-form-item label="开户名称"><el-input v-model="editForm.kaihuming" /></el-form-item>
          <el-form-item label="银行账号"><el-input v-model="editForm.yinhangzhanghao" /></el-form-item>
          <el-form-item label="开户行"><el-input v-model="editForm.kaihuhang" /></el-form-item>
          <el-form-item label="开户人身份证号码"><el-input v-model="editForm.kaihushenfenzheng" /></el-form-item>
          <el-form-item label="银行账号备注"><el-input v-model="editForm.yinhangbeizhu" /></el-form-item>
        </el-tab-pane>

        <!-- 民政局信息(只读) -->
        <el-tab-pane label="民政局信息" name="mz">
          <el-form-item label="省/市"><el-input v-model="editForm.shi" readonly /></el-form-item>
          <el-form-item label="区县"><el-input v-model="editForm.quxian" readonly /></el-form-item>
          <el-form-item label="乡镇（街道）"><el-input v-model="editForm.xiangzhen" readonly /></el-form-item>
          <el-form-item label="村(居)"><el-input v-model="editForm.cun" readonly /></el-form-item>
          <el-form-item label="办理事项"><el-input v-model="editForm.shixiang" readonly /></el-form-item>
          <el-form-item label="申请人姓名"><el-input v-model="editForm.xingming" readonly /></el-form-item>
          <el-form-item label="申请人证件号码"><el-input v-model="editForm.sfz" readonly /></el-form-item>
        </el-tab-pane>

        <!-- 民政局信息2(只读) -->
        <el-tab-pane label="民政局信息2" name="mz2">
          <el-form-item label="起始保障年月"><el-input :model-value="editForm.ksbriqi ? editForm.ksbriqi.slice(0, 7) : ''" readonly /></el-form-item>
          <el-form-item label="截止保障年月"><el-input :model-value="editForm.jsbriqi ? editForm.jsbriqi.slice(0, 7) : ''" readonly /></el-form-item>
          <el-form-item label="特困类别"><el-input v-model="editForm.tekunlei" readonly /></el-form-item>
          <el-form-item label="供养方式"><el-input v-model="editForm.gongyangfangshi" readonly /></el-form-item>
          <el-form-item label="供养机构"><el-input v-model="editForm.gongyangjigou" readonly /></el-form-item>
        </el-tab-pane>

        <!-- 操作信息 -->
        <el-tab-pane label="操作信息" name="op">
          <el-form-item label="ID"><el-input :model-value="editingId ?? ''" readonly /></el-form-item>
          <el-form-item label="年度">
            <el-select v-if="editingId == null" v-model="editForm.nd" style="width: 100%">
              <el-option v-for="y in yearOptions" :key="y" :value="y" :label="y + '年'" />
            </el-select>
            <el-input v-else :model-value="editForm.nd" readonly />
          </el-form-item>
          <el-form-item label="营业所">
            <!-- 照旧 Edit.cshtml:bmid 为部门下拉(GetDeptList) -->
            <el-select v-model="editForm.bmid" clearable filterable placeholder="选择部门" style="width: 100%">
              <el-option v-for="d in deptOptions" :key="d.id" :value="d.id" :label="d.name" />
            </el-select>
          </el-form-item>
          <el-form-item label="文件营业所"><el-input v-model="editForm.bm" /></el-form-item>
          <el-form-item v-if="editingId != null" label="操作者"><el-input :model-value="editForm.caozuo || ''" readonly /></el-form-item>
          <el-form-item label="取消日期">
            <el-date-picker v-model="editForm.quxiaoriqi" type="month" value-format="YYYY-MM-DD" style="width: 100%" />
          </el-form-item>
        </el-tab-pane>
      </el-tabs>
    </el-form>
    <template #footer>
      <el-button @click="editDialog = false">取消</el-button>
      <el-button type="primary" @click="submitEdit">保存</el-button>
    </template>
  </el-dialog>

  <!-- 批量修改(照旧 dlgBatch) -->
  <el-dialog v-model="batchDialog" title="批量修改" width="440px">
    <el-form label-width="110px" size="small">
      <el-form-item label="目标字段">
        <el-select v-model="batchField" placeholder="请选择要批量更新的字段" style="width: 100%">
          <el-option v-for="f in BATCH_FIELDS" :key="f.value" :value="f.value" :label="f.label" />
        </el-select>
      </el-form-item>
      <el-form-item label="新值">
        <el-select v-if="batchField === 'qitayongshui'" v-model="batchValue" placeholder="请选择其他用水情况" style="width: 100%">
          <el-option v-for="v in QITA_PRESETS" :key="v" :value="v" :label="v" />
        </el-select>
        <el-select v-else-if="batchField === 'fanhuiminzhengju'" v-model="batchValue" style="width: 100%">
          <el-option value="是" label="是" />
          <el-option value="否" label="否" />
        </el-select>
        <el-input v-else-if="batchField === 'beizhu'" v-model="batchValue" type="textarea" :rows="3" placeholder="请输入要批量更新的内容,备注字段不会覆盖(追加)" />
        <el-input v-else v-model="batchValue" placeholder="请输入要批量更新的内容" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="batchDialog = false">取消</el-button>
      <el-button type="primary" @click="submitBatch">提交</el-button>
    </template>
  </el-dialog>

  <!-- 查看记录(修改日志) -->
  <el-dialog v-model="logDialog" :title="logTitle" width="720px">
    <el-table :data="logRows" size="small" max-height="480">
      <el-table-column prop="field_name" label="字段" width="130" />
      <el-table-column prop="old_value" label="旧值" min-width="150" show-overflow-tooltip />
      <el-table-column prop="new_value" label="新值" min-width="150" show-overflow-tooltip />
      <el-table-column prop="update_user" label="操作人" width="110" />
      <el-table-column prop="update_time" label="时间" width="160" />
    </el-table>
  </el-dialog>

  <!-- 导入新增 -->
  <el-dialog v-model="importDialog" title="导入数据" width="560px">
    <el-form label-width="120px" size="small">
      <el-form-item label="Excel 文件" required>
        <input type="file" accept=".xlsx,.xls" @change="onImportFile" />
        <span v-if="importForm.file" class="sheet-hint">已选:{{ importForm.file.name }}</span>
        <span v-if="sheetNames.length" class="sheet-hint">工作表:{{ sheetNames.join('、') }}</span>
      </el-form-item>
      <el-form-item label="选择年度" required>
        <el-select v-model="importForm.nd" style="width: 220px">
          <el-option v-for="y in yearOptions" :key="y" :value="y" :label="y + ' 年度'" />
        </el-select>
      </el-form-item>
      <el-form-item label=" ">
        <el-checkbox v-model="importForm.isQuxiao">导入【取消】数据(存入取消名单并回写主表取消日期)</el-checkbox>
      </el-form-item>
      <el-form-item v-if="importForm.isQuxiao" label="取消年月" required>
        <el-date-picker v-model="importForm.quxiaoriqi" type="month" value-format="YYYY-MM-DD" style="width: 220px" />
      </el-form-item>
      <el-form-item v-if="parsedCols.length" label="导入列">
        <div class="import-cols">
          <div class="import-cols-ops">
            <el-button size="small" link type="primary" @click="checkAllParsedCols(true)">全选</el-button>
            <el-button size="small" link type="warning" @click="checkAllParsedCols(false)">全不选</el-button>
            <span class="sheet-hint">勾选要导入的列(身份证为必选)</span>
          </div>
          <el-checkbox-group v-model="checkedCols">
            <el-checkbox
              v-for="c in parsedCols"
              :key="c.header"
              :value="c.header"
              :disabled="isSfzCol(c)"
              :label="c.header + (c.field ? '' : '(不识别)')"
            />
          </el-checkbox-group>
        </div>
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="importDialog = false">关闭</el-button>
      <el-button type="primary" :loading="loading" @click="submitImport">上传文件</el-button>
    </template>
  </el-dialog>

  <!-- 上传更新 -->
  <el-dialog v-model="updateDialog" title="Excel 数据更新" width="560px">
    <el-form label-width="120px" size="small">
      <el-form-item label="Excel 文件" required>
        <input type="file" accept=".xlsx,.xls" @change="onUpdateFile" />
        <span v-if="updateForm.file" class="sheet-hint">已选:{{ updateForm.file.name }}</span>
        <span v-if="sheetNames.length" class="sheet-hint">工作表:{{ sheetNames.join('、') }}</span>
      </el-form-item>
      <el-form-item label="选择年度" required>
        <el-select v-model="updateForm.nd" style="width: 220px">
          <el-option v-for="y in yearOptions" :key="y" :value="y" :label="y + ' 年度'" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="parsedCols.length" label="更新列">
        <div class="import-cols">
          <div class="import-cols-ops">
            <el-button size="small" link type="primary" @click="checkAllParsedCols(true)">全选</el-button>
            <el-button size="small" link type="warning" @click="checkAllParsedCols(false)">全不选</el-button>
          </div>
          <el-checkbox-group v-model="checkedCols">
            <el-checkbox
              v-for="c in parsedCols"
              :key="c.header"
              :value="c.header"
              :label="c.header + (c.field ? '' : '(不识别)')"
            />
          </el-checkbox-group>
        </div>
      </el-form-item>
      <el-alert type="info" :closable="false" title="按 年度+身份证+事项 匹配已有记录,只更新勾选的列,匹配不到的忽略" />
    </el-form>
    <template #footer>
      <el-button @click="updateDialog = false">取消</el-button>
      <el-button type="primary" :loading="loading" @click="submitUpdate">开始更新</el-button>
    </template>
  </el-dialog>

  <!-- 变动历史编辑 -->
  <el-dialog v-model="bdEditDialog" title="编辑记录" width="520px" top="4vh">
    <el-form label-width="130px" size="small">
      <el-form-item label="用户号"><el-input v-model="bdForm.yonghuhao" /></el-form-item>
      <el-form-item label="其他用水情况">
        <el-select v-model="bdForm.qitayongshui" clearable style="width: 100%">
          <el-option v-for="v in QITA_PRESETS" :key="v" :value="v" :label="v" />
        </el-select>
      </el-form-item>
      <el-form-item label="居住地址"><el-input v-model="bdForm.juzhudizhi" /></el-form-item>
      <el-form-item label="柜台受理情况"><el-input v-model="bdForm.guitaishouli" /></el-form-item>
      <el-form-item label="系统导入情况"><el-input v-model="bdForm.daoruqingkuang" /></el-form-item>
      <el-form-item label="返民政局">
        <el-switch v-model="bdForm.fanhuiminzhengju" active-text="是" inactive-text="否" active-value="是" inactive-value="否" />
      </el-form-item>
      <el-form-item label="受理时间">
        <el-date-picker v-model="bdForm.shoulishijian" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
      </el-form-item>
      <el-form-item label="优惠开始时间">
        <el-date-picker v-model="bdForm.youhuiksriqi" type="month" value-format="YYYY-MM-DD" style="width: 100%" />
      </el-form-item>
      <el-form-item label="优惠结束时间">
        <el-date-picker v-model="bdForm.youhuijsriqi" type="month" value-format="YYYY-MM-DD" style="width: 100%" />
      </el-form-item>
      <el-form-item label="优惠月数"><el-input-number v-model="bdForm.yueshu" :min="0" readonly style="width: 100%" /></el-form-item>
      <el-form-item label="污水费核退时间">
        <el-date-picker v-model="bdForm.wushuifeihetui" type="date" value-format="YYYY-MM-DD" style="width: 100%" />
      </el-form-item>
      <el-form-item label="备注"><el-input v-model="bdForm.beizhu" type="textarea" :rows="2" /></el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="bdEditDialog = false">取消</el-button>
      <el-button type="primary" @click="submitBdEdit">保存</el-button>
    </template>
  </el-dialog>

  <!-- 显示列设置(照旧 dlgColumns:搜索/全选/全不选/重置/统计) -->
  <el-dialog v-model="colDialog" :title="`显示列设置 (已选择 ${colDraft.length} / ${COLUMNS.length} 列)`" width="440px">
    <el-input v-model="colSearch" placeholder="输入列名搜索..." clearable size="small" style="margin-bottom: 10px" />
    <div class="col-ops-bar">
      <el-button size="small" type="success" plain @click="selectAllCols">全选</el-button>
      <el-button size="small" type="danger" plain @click="unselectAllCols">全不选</el-button>
      <el-button size="small" type="warning" plain @click="resetCols">重置</el-button>
    </div>
    <div class="col-list">
      <div v-for="(prop, i) in colDraftFiltered" :key="prop" class="col-item">
        <el-checkbox :model-value="true" @change="(v) => !v && toggleCol(prop, false)">
          {{ colLabel(prop) }}
        </el-checkbox>
        <div class="col-move">
          <el-button size="small" link :disabled="i === 0" @click="moveCol(colDraft.indexOf(prop), -1)">上移</el-button>
          <el-button size="small" link :disabled="i === colDraftFiltered.length - 1" @click="moveCol(colDraft.indexOf(prop), 1)">下移</el-button>
        </div>
      </div>
      <div v-if="colUnselected.length" class="col-add">
        <div class="sheet-hint" style="margin-bottom: 4px">未显示的列:</div>
        <el-checkbox
          v-for="c in colUnselected"
          :key="c.prop"
          :model-value="false"
          :label="c.label"
          @change="(v) => toggleCol(c.prop, v)"
        />
      </div>
    </div>
    <template #footer>
      <el-button @click="colDialog = false">取消</el-button>
      <el-button type="primary" @click="saveCols">保存设置</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
  align-items: center;
}
.spacer {
  flex: 1;
}
.switch-label {
  font-size: 13px;
  color: #606266;
}
.col-ops-bar {
  display: flex;
  gap: 8px;
  margin-bottom: 8px;
}
.col-list {
  max-height: 360px;
  overflow: auto;
}
.col-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px dashed #ebeef5;
}
.col-move {
  display: flex;
  gap: 4px;
}
.col-add {
  margin-top: 10px;
}
.import-cols {
  max-height: 240px;
  overflow: auto;
  border: 1px solid #ebeef5;
  border-radius: 4px;
  padding: 8px;
  width: 100%;
}
.import-cols-ops {
  margin-bottom: 4px;
}
.sheet-hint {
  color: #909399;
  font-size: 12px;
  margin-left: 10px;
}
:deep(.row-cancelled) {
  background: #f3ecd8;
}
</style>
