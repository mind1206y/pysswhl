<script setup>
/**
 * 测漏笔记(照旧系统 Views/Leak/Index.cshtml 复刻)
 * - 月份/队伍/维修日期/关键字筛选
 * - 新增/编辑:四种计量方法自动计算漏量、配合排查 8 折封顶 30
 * - 附件:图片自动压缩、视频封面截帧、文档预览/下载
 * - 详情抽屉 + PDF 导出
 */
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import {
  cleanupLeakUploads, createLeak, deleteLeak, downloadLeakPdf, getLeakDetail,
  getLeakDetectComs, getLeakFormComs, getLeakMonths, listLeaks, updateLeak,
  uploadLeakFile,
} from '@/api/leak'

const auth = useAuthStore()
const canManage = computed(() => auth.hasPerm('leak:manage'))
const isSuper = computed(() => !!auth.user?.is_superuser)

// 115 远程存储开关(照旧系统:仅管理员可见,默认 115;普通用户固定走 115)
const STORAGE_KEY = 'leak_upload_storage'
const remoteStorage = ref(localStorage.getItem(STORAGE_KEY) !== 'local')
const currentStorage = computed(() => (
  isSuper.value && !remoteStorage.value ? 'local' : 'remote'
))

function onStorageChange(value) {
  localStorage.setItem(STORAGE_KEY, value ? 'remote' : 'local')
  ElMessage.success(`文件存储已切换至：${value ? '115服务器' : '本地服务器'}`)
}

const METHOD_LABELS = {
  coefficient: '面积乘系数法',
  bucket: '桶量时间法',
  meter: '水表读数法',
  experience: '经验对比法',
}

// 压力 - 快速系数表(旧系统内置表,线性插值)
const COEFF_TABLE = {
  0.01: 0.956, 0.02: 1.352, 0.03: 1.656, 0.04: 1.912, 0.05: 2.138, 0.06: 2.342, 0.07: 2.529, 0.08: 2.704, 0.09: 2.868, 0.10: 3.023,
  0.11: 3.171, 0.12: 3.312, 0.13: 3.447, 0.14: 3.577, 0.15: 3.703, 0.16: 3.824, 0.17: 3.942, 0.18: 4.056, 0.19: 4.167, 0.20: 4.275,
  0.21: 4.381, 0.22: 4.484, 0.23: 4.585, 0.24: 4.683, 0.25: 4.780, 0.26: 4.875, 0.27: 4.968, 0.28: 5.059, 0.29: 5.148, 0.30: 5.236,
  0.31: 5.323, 0.32: 5.408, 0.33: 5.492, 0.34: 5.574, 0.35: 5.656, 0.36: 5.736, 0.37: 5.815, 0.38: 5.893, 0.39: 5.970, 0.40: 6.046,
  0.41: 6.121, 0.42: 6.196, 0.43: 6.269, 0.44: 6.341, 0.45: 6.413, 0.46: 6.484, 0.47: 6.554, 0.48: 6.623, 0.49: 6.692, 0.50: 6.760,
  0.51: 6.827, 0.52: 6.894, 0.53: 6.960, 0.54: 7.025, 0.55: 7.090, 0.56: 7.154, 0.57: 7.218, 0.58: 7.281, 0.59: 7.343, 0.60: 7.405,
}

const ACCEPT = '.jpg,.jpeg,.png,.gif,.bmp,.mp4,.mov,.avi,.wmv,.flv,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.xml'
const ALLOWED_EXTS = ACCEPT.split(',')

// ===== 列表筛选 =====
function yearRange() {
  const y = new Date().getFullYear()
  return [`${y}-01-01`, `${y}-12-31`]
}
const filters = reactive({
  page: 1, rows: 30, month: 'all', detectCom: 'all', keyword: '',
  dateRange: yearRange(),
})
const months = ref([{ value: 'all', text: '全部月份' }])
const detectComs = ref([{ value: 'all', text: '全部队伍' }])
const formComs = ref([])
const rows = ref([])
const total = ref(0)
const loading = ref(false)
const searchKeys = ref([])

const COLUMNS = [
  { prop: 'Title', label: '标题', width: 240, tip: true, slot: 'highlight' },
  { prop: 'Location', label: '地点', width: 180, tip: true, slot: 'highlight' },
  { prop: 'DetectUser', label: '测漏人', width: 100 },
  { prop: 'DetectCom', label: '测漏队伍', width: 170 },
  { prop: 'LeakMethod', label: '计量方法', width: 110, fmt: 'method' },
  { prop: 'FlowRate', label: '漏量(m³/h)', width: 110, align: 'right', fmt: 'num2' },
  { prop: 'PaichaType', label: '排查类型', width: 95, slot: 'highlight' },
  { prop: 'DetectTime', label: '维修日期', width: 150, slot: 'date' },
  { prop: 'QuantifyTime', label: '定量时间', width: 100, slot: 'quantify' },
  { prop: 'Remark', label: '备注', width: 320, tip: true, slot: 'highlight' },
  { prop: 'Pressure', label: '压力(MPa)', width: 100, align: 'right', fmt: 'num2' },
  { prop: 'Area', label: '面积(cm²)', width: 105, align: 'right', fmt: 'num2' },
  { prop: 'Time1', label: '时间1(s)', width: 90, align: 'right', fmt: 'num2' },
  { prop: 'Time2', label: '时间2(s)', width: 90, align: 'right', fmt: 'num2' },
  { prop: 'Time3', label: '时间3(s)', width: 90, align: 'right', fmt: 'num2' },
  { prop: 'AvgTime', label: '平均时间(s)', width: 100, align: 'right', fmt: 'num2' },
  { prop: 'BucketLiters', label: '定量桶(L)', width: 100, align: 'right', fmt: 'num2' },
  { prop: 'MeterTime', label: '计读时间(s)', width: 110, align: 'right', fmt: 'num2' },
  { prop: 'MeterVolume', label: '计读流量(m³)', width: 110, align: 'right', fmt: 'num3' },
  { prop: 'ExperienceDesc', label: '破口描述', width: 200, tip: true, slot: 'plain' },
  { prop: 'ExperienceFlow', label: '估量漏量(m³/h)', width: 120, align: 'right', fmt: 'num2' },
  { prop: 'Creator', label: '记录人', width: 100, slot: 'highlight' },
  { prop: 'CreateTime', label: '记录时间', width: 160 },
]

function isWeekend(row) {
  const dt = row?.DetectTime ? String(row.DetectTime) : ''
  if (dt.length < 10) return false
  const p = dt.slice(0, 10).split('-')
  if (p.length !== 3) return false
  const day = new Date(+p[0], +p[1] - 1, +p[2]).getDay()
  return day === 0 || day === 6
}

function isQuantifyIllegal(row) {
  const qt = row?.QuantifyTime ? String(row.QuantifyTime) : ''
  const p = qt.split(':')
  if (p.length !== 2) return false
  const mins = parseInt(p[0], 10) * 60 + parseInt(p[1], 10)
  if (Number.isNaN(mins)) return false
  let summer = false
  if (row?.DetectTime) {
    const mm = parseInt(String(row.DetectTime).slice(5, 7), 10)
    summer = mm >= 6 && mm <= 9
  }
  const pmStart = summer ? 870 : 840
  const pmEnd = summer ? 1080 : 1050
  return !((mins >= 510 && mins < 720) || (mins >= pmStart && mins <= pmEnd))
}

function dateCell(row) {
  const v = row?.DetectTime
  if (!v) return { text: '-', red: false }
  const d = String(v).slice(0, 10)
  const p = d.split('-')
  if (p.length !== 3) return { text: d, red: false }
  const day = new Date(+p[0], +p[1] - 1, +p[2]).getDay()
  const week = ['日', '一', '二', '三', '四', '五', '六'][day]
  return {
    text: `${d}（周${week}）`,
    red: day === 0 || day === 6 || isQuantifyIllegal(row),
  }
}

function quantifyRed(row) {
  return isQuantifyIllegal(row) || isWeekend(row)
}

function methodName(v) {
  return METHOD_LABELS[v] || v || '-'
}

function numCell(v, digits = 2) {
  if (v === null || v === undefined || v === '') return '-'
  const n = Number(v)
  if (Number.isNaN(n)) return String(v)
  return n ? n.toFixed(digits) : '-'
}

function fmtNum(v, digits = 2) {
  if (v === null || v === undefined || v === '') return '-'
  const n = Number(v)
  return Number.isNaN(n) ? String(v) : n.toFixed(digits)
}

function fmtDate(v) {
  return v ? String(v).slice(0, 10) : '-'
}

function fmtDateTime(v) {
  return v ? String(v).replace('T', ' ').slice(0, 19) : '-'
}

function esc(text) {
  return String(text ?? '').replace(/[&<>"']/g, (m) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[m]))
}

function parseKeys(text) {
  return Array.from(new Set(
    String(text || '').trim().split(/[\s,，]+/).map((k) => k.trim()).filter(Boolean)
  ))
}

function highlight(value) {
  const text = value === null || value === undefined || value === '' ? '-' : String(value)
  let out = esc(text)
  if (!searchKeys.value.length) return out
  for (const key of searchKeys.value) {
    const escaped = esc(key).replace(/[.*+?^=!:${}()|[\]\\]/g, '\\$&')
    if (!escaped) continue
    out = out.replace(new RegExp(escaped, 'gi'), (m) => `<span class="highlight">${m}</span>`)
  }
  return out
}

async function loadMonths() {
  try {
    const data = await getLeakMonths()
    if (Array.isArray(data) && data.length) months.value = data
  } catch { /* 忽略字典失败 */ }
}

async function loadDetectComs() {
  try {
    const data = await getLeakDetectComs()
    if (Array.isArray(data) && data.length) detectComs.value = data
  } catch { /* 忽略字典失败 */ }
}

async function loadFormComs() {
  if (!canManage.value) return
  try {
    const data = await getLeakFormComs()
    formComs.value = Array.isArray(data) ? data : []
  } catch { formComs.value = [] }
}

async function loadList() {
  searchKeys.value = parseKeys(filters.keyword)
  loading.value = true
  try {
    const params = {
      page: filters.page,
      rows: filters.rows,
      month: filters.month,
      detectCom: filters.detectCom,
      keyword: filters.keyword.trim(),
    }
    if (filters.month === 'all' && Array.isArray(filters.dateRange) && filters.dateRange.length === 2) {
      params.startDate = filters.dateRange[0]
      params.endDate = filters.dateRange[1]
    }
    const res = await listLeaks(params)
    rows.value = res.rows || []
    total.value = res.total || 0
  } finally {
    loading.value = false
  }
}

function search() {
  filters.page = 1
  searchKeys.value = parseKeys(filters.keyword)
  loadList()
}

function onFilterChange() {
  filters.page = 1
  searchKeys.value = parseKeys(filters.keyword)
  loadList()
}

// ===== 表单 =====
function todayStr() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

function emptyForm() {
  return {
    Id: 0, Title: '', Location: '', DetectCom: '', DetectUser: '',
    PaichaType: '普查', DetectTime: todayStr(), QuantifyTime: '',
    LeakMethod: 'coefficient', Pressure: null, Area: null, FlowRate: null,
    AreaExpression: '', Remark: '', Time1: null, Time2: null, Time3: null,
    AvgTime: null, BucketLiters: 50, MeterTime: null, MeterVolume: null,
    ExperienceDesc: '', ExperienceFlow: 0, FlowMeta: '',
  }
}

const formDlg = ref(false)
const formRef = ref()
const form = reactive(emptyForm())
const rules = {
  Title: [{ required: true, message: '请填写标题', trigger: 'blur' }],
  Location: [{ required: true, message: '请填写地点', trigger: 'blur' }],
  DetectUser: [{ required: true, message: '请填写测漏人', trigger: 'blur' }],
  DetectTime: [{ required: true, message: '请选择维修日期', trigger: 'change' }],
}
const newFiles = ref([])
const existingFiles = ref([])
const deletedFileIds = ref([])
const rawExpFlowValue = ref(0)
const lastRawFlow = ref(0)
const kValue = ref(0)
const discountHint = ref('')
const saveSucceeded = ref(false)
const coeffDlg = ref(false)
const uploadingCount = computed(() => newFiles.value.filter((f) => f.uploading).length)
const avgTime = computed(() => {
  const t = (Number(form.Time1) || 0) + (Number(form.Time2) || 0) + (Number(form.Time3) || 0)
  return t / 3
})
const coeffRows = computed(() =>
  Object.keys(COEFF_TABLE).map(Number).sort((a, b) => a - b).map((p) => ({
    pressure: p.toFixed(2), k: COEFF_TABLE[p].toFixed(3),
  }))
)

function round2(v) {
  const n = Number(v) || 0
  return Math.round((n + Number.EPSILON) * 100) / 100
}

function getCoefficientK(pressure) {
  if (pressure <= 0.01) return COEFF_TABLE[0.01]
  if (pressure >= 0.60) return COEFF_TABLE[0.60]
  const keys = Object.keys(COEFF_TABLE).map(Number).sort((a, b) => a - b)
  for (let i = 0; i < keys.length - 1; i += 1) {
    const low = keys[i]
    const high = keys[i + 1]
    if (Math.abs(pressure - low) < 1e-10) return COEFF_TABLE[low]
    if (Math.abs(pressure - high) < 1e-10) return COEFF_TABLE[high]
    if (pressure > low && pressure < high) {
      const t = (pressure - low) / (high - low)
      return COEFF_TABLE[low] + (COEFF_TABLE[high] - COEFF_TABLE[low]) * t
    }
  }
  return 0.956
}

function refreshCalculation() {
  const method = form.LeakMethod
  let raw = 0
  let formula = ''

  if (method === 'coefficient') {
    const pressure = Number(form.Pressure) || 0
    const area = Number(form.Area) || 0
    const k = getCoefficientK(pressure)
    kValue.value = k
    if (area > 0) {
      raw = k * area
      formula = `面积乘系数法: 压力=${pressure.toFixed(3)} MPa → K=${k.toFixed(4)}, 面积=${area.toFixed(2)} cm² → 原始漏量=K×面积=${k.toFixed(4)}×${area.toFixed(2)}=${raw.toFixed(4)} m³/h`
    } else {
      formula = '系数法: 请填写面积(>0)'
    }
  } else if (method === 'bucket') {
    const t1 = Number(form.Time1) || 0
    const t2 = Number(form.Time2) || 0
    const t3 = Number(form.Time3) || 0
    const liters = Number(form.BucketLiters) || 0
    const avg = (t1 + t2 + t3) / 3
    form.AvgTime = round2(avg)
    if (avg > 0 && liters > 0) {
      raw = (liters * 3.6) / avg
      formula = `桶量时间法: 定量桶=${liters.toFixed(2)}L, 平均时间=${avg.toFixed(2)}s → 原始漏量=${raw.toFixed(4)} m³/h`
    } else {
      formula = '桶量法: 请填写完整的时间(>0)和定量桶升数'
    }
  } else if (method === 'meter') {
    const time = Number(form.MeterTime) || 0
    const volume = Number(form.MeterVolume) || 0
    if (time > 0 && volume > 0) {
      raw = (volume / time) * 3600
      formula = `水表读数法: T=${time.toFixed(2)}s, V=${volume.toFixed(3)}m³ → 原始漏量=${raw.toFixed(4)} m³/h`
    } else {
      formula = '水表读数法: 请填写计读时间(>0)和计读流量(>0)'
    }
  } else if (method === 'experience') {
    raw = Number(rawExpFlowValue.value) || 0
    formula = `经验对比法（估量）: ${form.ExperienceDesc || '未填写破口描述'}`
    formula += raw > 0
      ? `，估量原始漏量=${raw.toFixed(2)} m³/h`
      : '，请手动输入估量漏量'
    form.ExperienceFlow = raw
  }

  lastRawFlow.value = raw
  let final = raw
  if (form.PaichaType === '配合排查' && raw > 0) {
    const adjusted = raw * 0.8
    final = adjusted > 30 ? 30 : adjusted
    const adjustedText = final.toFixed(2)
    discountHint.value = adjusted > 30
      ? `配合排查打8折：原始 ${raw.toFixed(2)} → 打折后 ${adjusted.toFixed(2)} → 封顶 30.00 m³/h`
      : `配合排查打8折：原始 ${raw.toFixed(2)} → 最终 ${adjustedText} m³/h`
    form.FlowMeta = JSON.stringify({
      originalFlow: round2(raw), adjustedFlow: round2(final), reason: '配合排查',
    })
  } else {
    discountHint.value = ''
    form.FlowMeta = ''
  }

  form.AreaExpression = formula
  form.FlowRate = round2(final)
}

function onMethodChange(method) {
  if (method === 'bucket' && !Number(form.BucketLiters)) form.BucketLiters = 50
  rawExpFlowValue.value = method === 'experience'
    ? (Number(form.FlowRate) || 0)
    : 0
  refreshCalculation()
}

function onParamChange() {
  refreshCalculation()
}

function onFlowRateChange(val) {
  if (form.LeakMethod === 'experience') {
    rawExpFlowValue.value = Number(val) || 0
    refreshCalculation()
  }
}

function onPaichaChange() {
  refreshCalculation()
}

function onExperienceDesc() {
  if (form.LeakMethod === 'experience') refreshCalculation()
}

function formatQuantify(value, pad = false) {
  const digits = String(value || '').replace(/\D/g, '').slice(0, 4)
  let out = digits
  if (digits.length === 4 || (pad && digits.length === 3)) {
    let hh
    let mm
    if (digits.length === 3) {
      if (parseInt(digits.slice(0, 2), 10) > 23) {
        hh = parseInt(digits.slice(0, 1), 10)
        mm = parseInt(digits.slice(1), 10)
      } else {
        hh = parseInt(digits.slice(0, 2), 10)
        mm = parseInt(digits.slice(2), 10)
      }
    } else {
      hh = parseInt(digits.slice(0, 2), 10)
      mm = parseInt(digits.slice(2), 10)
    }
    if (hh > 23) hh = 23
    if (mm > 59) mm = 59
    out = `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`
  }
  form.QuantifyTime = out
}

function onQuantifyInput(value) {
  formatQuantify(value, false)
}

function onQuantifyBlur() {
  if (form.QuantifyTime === '') return
  formatQuantify(form.QuantifyTime, true)
}

// ===== 附件 =====
function getType(name) {
  const ext = `.${String(name || '').split('.').pop().toLowerCase()}`
  if (['.jpg', '.jpeg', '.png', '.gif', '.bmp'].includes(ext)) return 'image'
  if (['.mp4', '.mov', '.avi', '.wmv', '.flv'].includes(ext)) return 'video'
  if (ext === '.pdf') return 'pdf'
  if (['.doc', '.docx'].includes(ext)) return 'word'
  if (['.xls', '.xlsx'].includes(ext)) return 'excel'
  return 'other'
}

function fileIcon(name) {
  const type = getType(name)
  if (type === 'pdf') return '📑'
  if (type === 'word') return '📝'
  if (type === 'excel') return '📊'
  const ext = String(name || '').split('.').pop().toLowerCase()
  if (['ppt', 'pptx'].includes(ext)) return '📽️'
  if (ext === 'txt') return '📃'
  if (ext === 'xml') return '🧾'
  return '📄'
}

function captureVideoCover(file, seekTime = 1) {
  return new Promise((resolve, reject) => {
    const video = document.createElement('video')
    video.preload = 'metadata'
    video.muted = true
    video.playsInline = true
    const objectUrl = URL.createObjectURL(file)
    const timer = setTimeout(() => {
      URL.revokeObjectURL(objectUrl)
      reject(new Error('视频截帧超时'))
    }, 10000)

    video.onloadeddata = () => {
      video.currentTime = Math.min(seekTime, (video.duration || 2) * 0.5)
    }
    video.onseeked = () => {
      clearTimeout(timer)
      try {
        if (!video.videoWidth || !video.videoHeight) {
          URL.revokeObjectURL(objectUrl)
          reject(new Error('浏览器无法解码该视频格式'))
          return
        }
        const canvas = document.createElement('canvas')
        canvas.width = video.videoWidth
        canvas.height = video.videoHeight
        canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height)
        canvas.toBlob((blob) => {
          URL.revokeObjectURL(objectUrl)
          if (!blob) {
            reject(new Error('生成封面失败'))
            return
          }
          resolve(new File(
            [blob],
            `${file.name.replace(/\.[^/.]+$/, '')}_cover.jpg`,
            { type: 'image/jpeg' },
          ))
        }, 'image/jpeg', 0.9)
      } catch (err) {
        URL.revokeObjectURL(objectUrl)
        reject(err)
      }
    }
    video.onerror = () => {
      clearTimeout(timer)
      URL.revokeObjectURL(objectUrl)
      reject(new Error('视频加载失败'))
    }
    video.src = objectUrl
  })
}

async function handleUpload(options) {
  const file = options.file
  const ext = `.${String(file.name).split('.').pop().toLowerCase()}`
  if (!ALLOWED_EXTS.includes(ext)) {
    ElMessage.error(`不支持的文件类型：${file.name}`)
    throw new Error('unsupported type')
  }

  const entry = reactive({
    uid: file.uid || `${Date.now()}_${file.name}`,
    fileName: file.name,
    fileType: getType(file.name),
    previewUrl: URL.createObjectURL(file),
    thumbPreview: '',
    url: '',
    thumbUrl: '',
    uploading: true,
    progress: 0,
  })
  newFiles.value.push(entry)

  try {
    const res = await uploadLeakFile(file, (p) => { entry.progress = p }, currentStorage.value)
    entry.url = res.url
    entry.fileName = res.fileName || file.name
    entry.fileType = res.fileType || getType(file.name)
    if (res.warning) ElMessage.warning(res.warning)

    if (entry.fileType === 'video') {
      try {
        const cover = await captureVideoCover(file)
        const coverRes = await uploadLeakFile(cover, null, currentStorage.value)
        entry.thumbUrl = coverRes.url
        entry.thumbPreview = URL.createObjectURL(cover)
      } catch (err) {
        console.warn('视频封面生成降级:', err)
      }
    }

    entry.uploading = false
    entry.progress = 100
    return res
  } catch (err) {
    newFiles.value = newFiles.value.filter((f) => f !== entry)
    URL.revokeObjectURL(entry.previewUrl)
    if (entry.thumbPreview) URL.revokeObjectURL(entry.thumbPreview)
    ElMessage.error(`附件上传失败：${err?.response?.data?.detail || err.message || '未知错误'}`)
    throw err
  }
}

function releaseEntryUrls(entry) {
  if (entry.previewUrl) URL.revokeObjectURL(entry.previewUrl)
  if (entry.thumbPreview) URL.revokeObjectURL(entry.thumbPreview)
}

function removeNewFile(index) {
  const [entry] = newFiles.value.splice(index, 1)
  if (!entry) return
  releaseEntryUrls(entry)
  const urls = [entry.url, entry.thumbUrl].filter(Boolean)
  if (urls.length) cleanupLeakUploads(urls).catch(() => {})
}

function removeExisting(index) {
  const [entry] = existingFiles.value.splice(index, 1)
  if (entry) deletedFileIds.value.push(entry.Id)
}

function openFile(url) {
  if (url) window.open(url, '_blank', 'noopener')
}

function cleanupAllNewFiles() {
  const urls = []
  for (const entry of newFiles.value) {
    releaseEntryUrls(entry)
    if (entry.url) urls.push(entry.url)
    if (entry.thumbUrl) urls.push(entry.thumbUrl)
  }
  newFiles.value = []
  if (urls.length) cleanupLeakUploads(urls).catch(() => {})
}

// ===== 新增 / 编辑 / 删除 =====
function resetFormState() {
  Object.assign(form, emptyForm())
  newFiles.value = []
  existingFiles.value = []
  deletedFileIds.value = []
  rawExpFlowValue.value = 0
  lastRawFlow.value = 0
  kValue.value = 0
  discountHint.value = ''
}

async function openCreate() {
  cleanupAllNewFiles()
  resetFormState()
  await loadFormComs()
  formDlg.value = true
  nextTick(() => formRef.value?.clearValidate())
}

async function openEdit(row) {
  try {
    const res = await getLeakDetail(row.Id)
    const d = res.data
    cleanupAllNewFiles()
    resetFormState()
    Object.assign(form, {
      ...d,
      DetectTime: d.DetectTime ? String(d.DetectTime).slice(0, 10) : todayStr(),
      FlowRate: d.FlowRate ?? 0,
    })
    form.Id = d.Id
    existingFiles.value = res.files || []
    deletedFileIds.value = []
    rawExpFlowValue.value = d.LeakMethod === 'experience'
      ? (Number(d.ExperienceFlow) || Number(d.FlowRate) || 0)
      : 0
    await loadFormComs()
    if (d.DetectCom && !formComs.value.includes(d.DetectCom)) formComs.value.push(d.DetectCom)
    formDlg.value = true
    nextTick(() => {
      formRef.value?.clearValidate()
      refreshCalculation()
    })
  } catch {
    ElMessage.error('获取记录详情失败')
  }
}

function onDialogClosed() {
  if (!saveSucceeded.value) cleanupAllNewFiles()
  saveSucceeded.value = false
  for (const entry of newFiles.value) releaseEntryUrls(entry)
  newFiles.value = []
  existingFiles.value = []
  deletedFileIds.value = []
}

function validateMethod() {
  if (form.LeakMethod === 'coefficient' && (Number(form.Area) || 0) <= 0) {
    ElMessage.warning('系数法请填写面积')
    return false
  }
  if (form.LeakMethod === 'bucket') {
    const values = [form.Time1, form.Time2, form.Time3, form.BucketLiters].map((v) => Number(v) || 0)
    if (values.some((v) => v <= 0)) {
      ElMessage.warning('桶量法请完整填写三个时间(>0)和定量桶升数')
      return false
    }
  }
  if (form.LeakMethod === 'meter') {
    if ((Number(form.MeterTime) || 0) <= 0 || (Number(form.MeterVolume) || 0) <= 0) {
      ElMessage.warning('水表读数法请填写计读时间(>0)和计读流量(>0)')
      return false
    }
  }
  if (form.LeakMethod === 'experience' && (Number(form.FlowRate) || 0) <= 0) {
    ElMessage.warning('经验对比法请手动输入估量漏量(>0)')
    return false
  }
  return true
}

function buildFlowRemark() {
  if (form.PaichaType !== '配合排查' || lastRawFlow.value <= 0) return ''
  const raw = lastRawFlow.value
  const adjusted = raw * 0.8
  if (adjusted > 30) {
    return `原漏量值：${raw.toFixed(2)} m³/h，因配合排查，最终值为：30.00 m³/h（已超过上限30，按30计算）`
  }
  return `原漏量值：${raw.toFixed(2)} m³/h，因配合排查，最终值为：${adjusted.toFixed(2)} m³/h`
}

async function saveRecord() {
  if (!formRef.value) return
  const ok = await formRef.value.validate().catch(() => false)
  if (!ok) return
  if (uploadingCount.value > 0) {
    ElMessage.warning('附件仍在上传，请稍候')
    return
  }
  if (!validateMethod()) return

  refreshCalculation()
  const flowRemark = buildFlowRemark()
  if (flowRemark) {
    const current = form.Remark || ''
    const cleaned = current
      .replace(/；?原漏量值：[\d.]+ m³\/h，因配合排查，最终值为：[\d.]+ m³\/h(?:（已超过上限30，按30计算）)?/g, '')
      .trim()
    form.Remark = cleaned ? `${cleaned}；${flowRemark}` : flowRemark
  }

  const fd = new FormData()
  const append = (key, value) => fd.append(key, value === null || value === undefined ? '' : value)
  append('Title', form.Title)
  append('Location', form.Location)
  append('DetectUser', form.DetectUser)
  append('DetectCom', form.DetectCom)
  append('PaichaType', form.PaichaType)
  append('DetectTime', form.DetectTime)
  append('QuantifyTime', form.QuantifyTime)
  append('LeakMethod', form.LeakMethod)
  append('Pressure', form.Pressure)
  append('Area', form.Area)
  append('FlowRate', form.FlowRate)
  append('AreaExpression', form.AreaExpression)
  append('Remark', form.Remark)
  append('Time1', form.Time1)
  append('Time2', form.Time2)
  append('Time3', form.Time3)
  append('AvgTime', form.AvgTime)
  append('BucketLiters', form.BucketLiters)
  append('MeterTime', form.MeterTime)
  append('MeterVolume', form.MeterVolume)
  append('ExperienceDesc', form.ExperienceDesc)
  append('ExperienceFlow', form.ExperienceFlow)
  append('FlowMeta', form.FlowMeta)
  const infos = newFiles.value
    .filter((f) => f.url)
    .map((f) => ({ url: f.url, fileName: f.fileName, ThumbUrl: f.thumbUrl || '' }))
  append('FileInfos', JSON.stringify(infos))
  if (form.Id) {
    append('DeletedFileIds', deletedFileIds.value.join(','))
  }

  try {
    if (form.Id) {
      await updateLeak(form.Id, fd)
    } else {
      await createLeak(fd)
    }
    ElMessage.success('保存成功')
    saveSucceeded.value = true
    formDlg.value = false
    loadList()
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '保存失败')
  }
}

async function doDelete(row) {
  try {
    await ElMessageBox.confirm('确定删除该记录及其所有附件吗？', '提示', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消',
    })
    await deleteLeak(row.Id)
    ElMessage.success('删除成功')
    loadList()
  } catch (err) {
    if (err !== 'cancel' && err !== 'close') {
      ElMessage.error(err?.response?.data?.detail || '删除失败')
    }
  }
}

// ===== 详情 =====
const drawer = ref(false)
const detail = ref({})
const detailFiles = ref([])
const detailRemark = computed(() => {
  let text = detail.value.Remark || ''
  if (detail.value.FlowMeta) {
    try {
      const meta = JSON.parse(detail.value.FlowMeta)
      if (meta.originalFlow !== undefined && meta.originalFlow !== null) {
        const msg = `原漏量值：${Number(meta.originalFlow).toFixed(2)} m³/h，因${meta.reason || ''}，最终值为：${Number(meta.adjustedFlow || 0).toFixed(2)} m³/h`
        if (!text.includes(msg)) text = text ? `${text}；${msg}` : msg
      }
    } catch { /* 忽略旧数据里的非法 JSON */ }
  }
  return text || '-'
})
const imageUrls = computed(() =>
  detailFiles.value.filter((f) => f.FileType === 'image').map((f) => f.FileUrl)
)

async function openDetail(row) {
  try {
    const res = await getLeakDetail(row.Id)
    detail.value = res.data || {}
    detailFiles.value = res.files || []
    drawer.value = true
  } catch {
    ElMessage.error('获取记录详情失败')
  }
}

function buildPdfName(d) {
  const clean = (s) => String(s ?? '').replace(/[\\/:*?"<>|]/g, '-')
  const date = d.DetectTime ? String(d.DetectTime).slice(0, 10) : todayStr()
  return `${clean(date)}_${clean(d.DetectCom || '未知队伍')}_${clean(d.DetectUser || '未知测漏者')}_${clean(d.Location || '未知地点')}_${clean(`${(Number(d.FlowRate) || 0).toFixed(2)} m³/h`)}.pdf`
}

async function exportPdf(d) {
  if (!d || !d.Id) return
  try {
    await downloadLeakPdf(d.Id, buildPdfName(d))
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '导出失败')
  }
}

onMounted(() => {
  loadMonths()
  loadDetectComs()
  loadList()
})
</script>

<template>
  <div class="leak-page">
    <el-card class="filter-card" shadow="never">
      <div class="page-head">
        <div>
          <div class="page-title">💧 测漏笔记</div>
          <div class="page-sub">记录测漏点滴，沉淀现场经验</div>
        </div>
        <div v-if="isSuper" class="storage-switch">
          <span class="fl-label">📁 存储</span>
          <el-switch
            v-model="remoteStorage"
            inline-prompt
            active-text="115"
            inactive-text="本地"
            @change="onStorageChange"
          />
          <span class="filter-tip">{{ remoteStorage ? '115服务器' : '本地服务器' }}</span>
        </div>
      </div>

      <div class="filter-row">
        <el-button v-if="canManage" type="success" @click="openCreate">新增测漏记录</el-button>
        <span class="fl-label">月份</span>
        <el-select v-model="filters.month" style="width: 140px" @change="onFilterChange">
          <el-option v-for="m in months" :key="m.value" :label="m.text" :value="m.value" />
        </el-select>
        <span class="fl-label">队伍</span>
        <el-select v-model="filters.detectCom" style="width: 170px" filterable @change="onFilterChange">
          <el-option v-for="c in detectComs" :key="c.value" :label="c.text" :value="c.value" />
        </el-select>
        <span class="fl-label">维修日期</span>
        <el-date-picker
          v-model="filters.dateRange"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          :disabled="filters.month !== 'all'"
        />
        <el-input
          v-model="filters.keyword"
          placeholder="地点/标题/排查类型/备注"
          clearable
          style="width: 240px"
          @keyup.enter="search"
          @clear="search"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-button type="primary" @click="onFilterChange">查询</el-button>
      </div>

      <div class="filter-row">
        <span class="filter-tip">月份优先；选择具体月份后日期范围自动置灰</span>
      </div>
    </el-card>

    <div class="table-wrap">
    <el-table
      v-loading="loading"
      :data="rows"
      border
      stripe
      size="small"
      class="leak-table"
      height="100%"
      :header-cell-style="{ background: '#f5f7fa', color: '#303133' }"
    >
      <el-table-column label="操作" width="185" fixed="left" align="center">
        <template #default="{ row }">
          <div class="opt-group">
            <el-button link type="primary" @click="openDetail(row)">查看</el-button>
            <el-button v-if="canManage" link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button link type="success" @click="exportPdf(row)">导出</el-button>
            <el-button v-if="canManage" link type="danger" @click="doDelete(row)">删除</el-button>
          </div>
        </template>
      </el-table-column>
      <el-table-column
        v-for="c in COLUMNS"
        :key="c.prop"
        :prop="c.prop"
        :label="c.label"
        :width="c.width"
        :align="c.align || 'left'"
        :show-overflow-tooltip="c.tip && c.slot !== 'highlight'"
      >
        <template #default="{ row }">
          <template v-if="c.slot === 'highlight'">
            <span v-html="highlight(row[c.prop])" />
          </template>
          <template v-else-if="c.slot === 'plain'">
            {{ row[c.prop] || '-' }}
          </template>
          <template v-else-if="c.slot === 'date'">
            <span :class="{ 'weekend-date': dateCell(row).red }">{{ dateCell(row).text }}</span>
          </template>
          <template v-else-if="c.slot === 'quantify'">
            <span v-if="!row.QuantifyTime">-</span>
            <span v-else :class="{ 'weekend-date': quantifyRed(row) }">{{ row.QuantifyTime }}</span>
          </template>
          <template v-else-if="c.fmt === 'method'">
            {{ methodName(row[c.prop]) }}
          </template>
          <template v-else-if="c.fmt === 'num2'">
            {{ numCell(row[c.prop], 2) }}
          </template>
          <template v-else-if="c.fmt === 'num3'">
            {{ numCell(row[c.prop], 3) }}
          </template>
          <template v-else>
            {{ row[c.prop] || '-' }}
          </template>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination
        v-model:current-page="filters.page"
        v-model:page-size="filters.rows"
        :page-sizes="[30, 60, 120]"
        :total="total"
        layout="total, sizes, prev, pager, next, jumper"
        @current-change="loadList"
        @size-change="search"
      />
    </div>
    </div>

    <!-- 新增/编辑 -->
    <el-dialog
      v-model="formDlg"
      :title="form.Id ? '编辑测漏记录' : '新增测漏记录'"
      width="820px"
      top="3vh"
      destroy-on-close
      @closed="onDialogClosed"
    >
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="105px"
        size="small"
        class="leak-form"
      >
        <el-divider content-position="left">基础信息</el-divider>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="标题" prop="Title">
              <el-input v-model="form.Title" maxlength="200" show-word-limit placeholder="测漏点名称" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="地点" prop="Location">
              <el-input v-model="form.Location" placeholder="详细位置" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="测漏队">
              <el-select
                v-model="form.DetectCom"
                filterable
                allow-create
                default-first-option
                clearable
                placeholder="可选择已有队伍或输入新队伍"
                style="width: 100%"
              >
                <el-option v-for="c in formComs" :key="c" :label="c" :value="c" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="测漏人" prop="DetectUser">
              <el-input v-model="form.DetectUser" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="排查类型">
              <el-radio-group v-model="form.PaichaType" @change="onPaichaChange">
                <el-radio value="普查">普查</el-radio>
                <el-radio value="配合排查">配合排查</el-radio>
              </el-radio-group>
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="维修日期" prop="DetectTime">
              <el-date-picker
                v-model="form.DetectTime"
                type="date"
                value-format="YYYY-MM-DD"
                placeholder="选择日期"
                style="width: 100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="定量时间">
              <el-input
                v-model="form.QuantifyTime"
                maxlength="5"
                placeholder="输入1215自动变为12:15"
                @input="onQuantifyInput"
                @blur="onQuantifyBlur"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">测漏参数 & 智能计算</el-divider>
        <el-form-item label="计量方法">
          <el-radio-group v-model="form.LeakMethod" @change="onMethodChange">
            <el-radio value="coefficient">面积乘系数法</el-radio>
            <el-radio value="bucket">桶量时间法</el-radio>
            <el-radio value="meter">水表读数法</el-radio>
            <el-radio value="experience">经验对比法</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="压力(MPa)">
              <el-input-number
                v-model="form.Pressure"
                :precision="3"
                :min="0"
                :controls="false"
                style="width: 100%"
                @change="onParamChange"
              />
            </el-form-item>
          </el-col>
          <el-col v-if="form.LeakMethod === 'coefficient'" :span="12">
            <el-form-item label="面积(cm²)">
              <el-input-number
                v-model="form.Area"
                :precision="2"
                :min="0"
                :controls="false"
                style="width: 100%"
                @change="onParamChange"
              />
            </el-form-item>
          </el-col>
        </el-row>

        <div v-if="form.LeakMethod === 'coefficient'" class="k-tip" @click="coeffDlg = true">
          🔍 当前快速系数 K = <b>{{ kValue.toFixed(4) }}</b>（基于压力查表插值，点击查看对照表）
        </div>

        <template v-if="form.LeakMethod === 'bucket'">
          <el-form-item label="时间1/2/3(秒)">
            <div class="triple-input">
              <el-input-number v-model="form.Time1" :precision="2" :min="0" :controls="false" @change="onParamChange" />
              <el-input-number v-model="form.Time2" :precision="2" :min="0" :controls="false" @change="onParamChange" />
              <el-input-number v-model="form.Time3" :precision="2" :min="0" :controls="false" @change="onParamChange" />
            </div>
          </el-form-item>
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="定量桶(L)">
                <el-input-number v-model="form.BucketLiters" :precision="2" :min="0" :controls="false" style="width: 100%" @change="onParamChange" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="平均时间">
                <span class="calc-value">{{ avgTime.toFixed(2) }} 秒</span>
              </el-form-item>
            </el-col>
          </el-row>
        </template>

        <template v-if="form.LeakMethod === 'meter'">
          <el-row :gutter="12">
            <el-col :span="12">
              <el-form-item label="计读时间 T(秒)">
                <el-input-number v-model="form.MeterTime" :precision="2" :min="0" :controls="false" style="width: 100%" @change="onParamChange" />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="计读流量 V(m³)">
                <el-input-number v-model="form.MeterVolume" :precision="3" :min="0" :controls="false" style="width: 100%" @change="onParamChange" />
              </el-form-item>
            </el-col>
          </el-row>
          <div class="formula-tip">📐 计算公式：Q = V / T × 3600 (m³/h)</div>
        </template>

        <template v-if="form.LeakMethod === 'experience'">
          <el-form-item label="破口描述">
            <el-input
              v-model="form.ExperienceDesc"
              type="textarea"
              :rows="3"
              placeholder="例：DN100铸铁管，埋深1m，管身开裂长10cm宽5mm，漏量较大"
              @input="onExperienceDesc"
            />
          </el-form-item>
          <div class="formula-tip">✏️ 请在下方的“漏量”字段中手动输入估量漏量值 (m³/h)</div>
        </template>

        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="漏量(m³/h)">
              <el-input-number
                v-model="form.FlowRate"
                :precision="2"
                :controls="false"
                :readonly="form.LeakMethod !== 'experience'"
                style="width: 100%"
                @change="onFlowRateChange"
              />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="计算公式">
              <el-input v-model="form.AreaExpression" type="textarea" :rows="2" readonly />
            </el-form-item>
          </el-col>
        </el-row>
        <el-alert
          v-if="discountHint"
          :title="discountHint"
          type="warning"
          :closable="false"
          show-icon
          class="discount-hint"
        />

        <el-divider content-position="left">备注信息</el-divider>
        <el-form-item label="备注">
          <el-input v-model="form.Remark" type="textarea" :rows="4" />
        </el-form-item>

        <el-divider content-position="left">附件上传</el-divider>
        <el-form-item label="附件">
          <div class="upload-block">
            <el-upload
              :show-file-list="false"
              :http-request="handleUpload"
              :accept="ACCEPT"
              multiple
              :disabled="uploadingCount > 0"
            >
              <el-button :loading="uploadingCount > 0">选择并上传附件</el-button>
              <template #tip>
                <div class="el-upload__tip">支持图片/视频/PDF/Word/Excel/PPT/TXT/XML，单文件 ≤ 200MB</div>
              </template>
            </el-upload>

            <div v-if="newFiles.length || existingFiles.length" class="attach-list">
              <div v-for="(f, idx) in newFiles" :key="f.uid" class="attach-item">
                <div class="attach-preview">
                  <img v-if="f.fileType === 'image'" :src="f.previewUrl" alt="" />
                  <video v-else-if="f.fileType === 'video'" :src="f.previewUrl" :poster="f.thumbPreview" muted />
                  <span v-else class="file-icon">{{ fileIcon(f.fileName) }}</span>
                </div>
                <div class="attach-name" :title="f.fileName">{{ f.fileName }}</div>
                <el-progress v-if="f.uploading" :percentage="f.progress" :stroke-width="4" />
                <el-button link type="danger" :disabled="f.uploading" @click="removeNewFile(idx)">移除</el-button>
              </div>

              <div v-for="(f, idx) in existingFiles" :key="`old_${f.Id}`" class="attach-item">
                <div class="attach-preview">
                  <img v-if="f.FileType === 'image'" :src="f.FileUrl" alt="" />
                  <video v-else-if="f.FileType === 'video'" :src="f.FileUrl" :poster="f.ThumbUrl" muted />
                  <span v-else class="file-icon">{{ fileIcon(f.FileName) }}</span>
                </div>
                <div class="attach-name" :title="f.FileName">{{ f.FileName }}</div>
                <el-button link type="primary" @click="openFile(f.FileUrl)">打开</el-button>
                <el-button link type="danger" @click="removeExisting(idx)">删除</el-button>
              </div>
            </div>
          </div>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="formDlg = false">取消</el-button>
        <el-button type="primary" :loading="false" @click="saveRecord">提交保存</el-button>
      </template>
    </el-dialog>

    <!-- 系数对照表 -->
    <el-dialog v-model="coeffDlg" title="压力 - 快速系数对照表" width="420px">
      <el-table :data="coeffRows" size="small" border max-height="460">
        <el-table-column prop="pressure" label="压力 (MPa)" align="center" />
        <el-table-column prop="k" label="系数 K" align="center" />
      </el-table>
    </el-dialog>

    <!-- 详情抽屉 -->
    <el-drawer v-model="drawer" title="测漏记录详情" size="820px">
      <div class="detail-body">
        <h2 class="detail-title">📋 {{ detail.Title || '-' }}</h2>
        <div class="detail-location">
          <span class="detail-location-label">📍 地点：</span>
          <span>{{ detail.Location || '-' }}</span>
        </div>

        <div class="section-title">📋 详情描述</div>
        <div class="detail-grid">
          <div class="detail-item"><span class="detail-label">记录ID：</span><span>{{ detail.Id || '-' }}</span></div>
          <div class="detail-item"><span class="detail-label">记录时间：</span><span>{{ fmtDateTime(detail.CreateTime) }}</span></div>
          <div class="detail-item"><span class="detail-label">测漏人：</span><span>{{ detail.DetectUser || '-' }}</span></div>
          <div class="detail-item"><span class="detail-label">测漏队伍：</span><span>{{ detail.DetectCom || '-' }}</span></div>
          <div class="detail-item"><span class="detail-label">压力(MPa)：</span><span>{{ fmtNum(detail.Pressure) }}</span></div>
          <div class="detail-item"><span class="detail-label">面积(cm²)：</span><span>{{ fmtNum(detail.Area) }}</span></div>
          <div class="detail-item"><span class="detail-label">漏量(m³/h)：</span><span>{{ fmtNum(detail.FlowRate) }}</span></div>
          <div class="detail-item"><span class="detail-label">排查类型：</span><span>{{ detail.PaichaType || '-' }}</span></div>
          <div class="detail-item"><span class="detail-label">维修日期：</span><span>{{ fmtDate(detail.DetectTime) }}</span></div>
          <div class="detail-item"><span class="detail-label">计量方法：</span><span>{{ methodName(detail.LeakMethod) }}</span></div>
          <div class="detail-item"><span class="detail-label">时间1/2/3：</span><span>{{ fmtNum(detail.Time1) }} / {{ fmtNum(detail.Time2) }} / {{ fmtNum(detail.Time3) }}</span></div>
          <div class="detail-item"><span class="detail-label">平均时间(s)：</span><span>{{ fmtNum(detail.AvgTime) }}</span></div>
          <div class="detail-item"><span class="detail-label">定量桶(L)：</span><span>{{ fmtNum(detail.BucketLiters) }}</span></div>
          <div class="detail-item"><span class="detail-label">计读时间(s)：</span><span>{{ fmtNum(detail.MeterTime) }}</span></div>
          <div class="detail-item"><span class="detail-label">计读流量(m³)：</span><span>{{ fmtNum(detail.MeterVolume, 3) }}</span></div>
          <div class="detail-item"><span class="detail-label">破口描述：</span><span>{{ detail.ExperienceDesc || '-' }}</span></div>
          <div class="detail-item"><span class="detail-label">估量漏量(m³/h)：</span><span>{{ fmtNum(detail.ExperienceFlow) }}</span></div>
        </div>

        <div class="section-title">📐 计算公式</div>
        <div class="detail-block">{{ detail.AreaExpression || '-' }}</div>

        <div class="section-title">📝 备注信息</div>
        <div class="detail-block">{{ detailRemark }}</div>

        <div class="section-title">🖼️ 相关影像</div>
        <div v-if="detailFiles.length" class="media-grid">
          <div v-for="f in detailFiles" :key="f.Id" class="media-card">
            <div class="media-container">
              <video v-if="f.FileType === 'video'" :src="f.FileUrl" :poster="f.ThumbUrl" controls />
              <el-image
                v-else-if="f.FileType === 'image'"
                :src="f.FileUrl"
                :preview-src-list="imageUrls"
                fit="contain"
                preview-teleported
              />
              <a v-else :href="f.FileUrl" target="_blank" rel="noopener" class="file-link">
                <span class="file-icon">{{ fileIcon(f.FileName) }}</span>
                <span>{{ f.FileName }}</span>
              </a>
            </div>
            <div class="media-name">{{ f.FileName }}</div>
          </div>
        </div>
        <div v-else class="media-empty">暂无附件</div>
      </div>

      <template #footer>
        <el-button type="primary" @click="exportPdf(detail)">导出PDF</el-button>
        <el-button @click="drawer = false">关闭</el-button>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.leak-page {
  height: 100%;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 4px;
  box-sizing: border-box;
  background: transparent;
}
.filter-card {
  margin-bottom: 12px;
  border: 1px solid #ebeef5;
  background: #fff;
}
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.page-title {
  font-size: 22px;
  font-weight: 700;
  color: #303133;
  letter-spacing: 1px;
}
.page-sub,
.page-hint,
.filter-tip {
  font-size: 12px;
  color: #909399;
}
.filter-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.filter-row:last-child {
  margin-bottom: 0;
}
/* 筛选栏日期范围：固定宽度，禁止在 flex 行里被拉伸撑满整行
   (不能用 class 直接定宽——Element Plus 的 el-date-picker 根节点 class 在
   scoped 样式下不一定落到位，故用 :deep 钻进 .el-date-editor 根节点) */
.filter-row :deep(.el-date-editor.el-input__wrapper) {
  flex: 0 0 240px;
  width: 240px !important;
  max-width: 240px;
}
.fl-label {
  font-size: 13px;
  color: #606266;
}
.storage-switch {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 14px;
  border-radius: 20px;
  background: #f0f2f5;
  border: 1px solid #e4e7ed;
}
.leak-table {
  background: #fff;
  flex: 1;
  min-height: 0;
}
.table-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.opt-group {
  display: flex;
  justify-content: center;
  gap: 2px;
  white-space: nowrap;
}
.weekend-date {
  color: #b22222;
  font-weight: bold;
}
:deep(.highlight) {
  background-color: #e6f0ff;
  color: #1d4ed8;
  font-weight: bold;
}
.pager {
  display: flex;
  justify-content: flex-end;
  padding: 10px 4px 0;
}
.k-tip {
  margin: 4px 0 12px 105px;
  padding: 6px 12px;
  font-size: 12px;
  color: #606266;
  background: #f0f2f5;
  border: 1px solid #ebeef5;
  border-radius: 20px;
  cursor: pointer;
  width: fit-content;
}
.k-tip b {
  color: #c0392b;
}
.triple-input {
  display: flex;
  gap: 8px;
  width: 100%;
}
.triple-input > * {
  flex: 1;
}
.calc-value {
  color: #c0392b;
  font-weight: 600;
}
.formula-tip {
  margin: 0 0 12px 105px;
  font-size: 12px;
  color: #606266;
}
.discount-hint {
  margin: 0 0 12px;
}
.upload-block {
  width: 100%;
}
.attach-list {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
}
.attach-item {
  width: 140px;
  padding: 8px;
  border: 1px solid #ebeef5;
  border-radius: 10px;
  background: #fff;
  position: relative;
}
.attach-preview {
  width: 100%;
  height: 84px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: #f5f7fa;
  border-radius: 8px;
}
.attach-preview img,
.attach-preview video {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.attach-name {
  margin-top: 6px;
  font-size: 12px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.file-icon {
  font-size: 34px;
  line-height: 1;
}
.detail-body {
  padding: 0 4px 12px;
}
.detail-title {
  margin: 0 0 14px;
  padding-left: 14px;
  border-left: 5px solid #409eff;
  color: #303133;
  font-size: 24px;
}
.detail-location {
  margin-bottom: 16px;
  padding: 10px 14px;
  border-radius: 12px;
  background: #f0f2f5;
  border: 1px solid #ebeef5;
  color: #303133;
}
.detail-location-label {
  color: #409eff;
  font-weight: 600;
}
.section-title {
  margin: 18px 0 10px;
  font-size: 15px;
  font-weight: 700;
  color: #303133;
}
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 20px;
}
.detail-item {
  font-size: 13px;
  color: #606266;
}
.detail-label {
  color: #909399;
}
.detail-block {
  padding: 12px;
  border-radius: 12px;
  background: #f5f7fa;
  border: 1px solid #ebeef5;
  color: #303133;
  white-space: pre-wrap;
  word-break: break-all;
}
.media-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 12px;
}
.media-card {
  border: 1px solid #ebeef5;
  border-radius: 10px;
  background: #fff;
  padding: 6px;
}
.media-container {
  height: 110px;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: #f5f7fa;
  border-radius: 8px;
}
.media-container img,
.media-container video,
.media-container :deep(.el-image) {
  width: 100%;
  height: 100%;
  object-fit: contain;
}
.media-name {
  margin-top: 6px;
  font-size: 12px;
  color: #606266;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.media-empty {
  color: #909399;
  text-align: center;
  padding: 18px;
}
.file-link {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 6px;
  color: #606266;
  text-decoration: none;
  font-size: 12px;
  text-align: center;
  word-break: break-all;
}
</style>
