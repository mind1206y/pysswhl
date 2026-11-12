<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createProject,
  deleteProject,
  createDownloadToken,
  fujianUploadUrl,
  addJianguan,
  addJindu,
  deleteFujian,
  deleteJianguan,
  deleteJindu,
  listFujian,
  listJianguan,
  listJindu,
  listProjectCategories,
  listProjects,
  resolveJianguan,
  updateJianguan,
  updateJindu,
  updateProject,
} from '@/api/project'
import { listDepartments } from '@/api/dept'
import { useAuthStore } from '@/stores/auth'

// 状态枚举沿用旧系统:0未开工 1施工中 2已敷设 3已试压 4已通水 5已验收 6已移交 7已归档
const STATUS_OPTIONS = [
  { value: 0, text: '未开工', tag: 'info' },
  { value: 1, text: '施工中', tag: 'primary' },
  { value: 2, text: '已敷设', tag: 'success' },
  { value: 3, text: '已试压', tag: 'success' },
  { value: 4, text: '已通水', tag: 'success' },
  { value: 5, text: '已验收', tag: 'success' },
  { value: 6, text: '已移交', tag: 'warning' },
  { value: 7, text: '已归档', tag: 'danger' },
]
const statusText = (v) => STATUS_OPTIONS.find((o) => o.value === v)?.text ?? v
const statusTag = (v) => STATUS_OPTIONS.find((o) => o.value === v)?.tag ?? 'info'

// ===== 列表 =====
const loading = ref(false)
const keyword = ref('')
const statusFilter = ref(null)
const categoryFilter = ref('')
const deptFilter = ref(null)
const deptOptions = ref([])
const page = ref(1)
const size = ref(10)
const total = ref(0)
const rows = ref([])
const categories = ref([])

async function load() {
  loading.value = true
  try {
    // 空值不传参,避免后端把空串当 int 解析报 422
    const params = { page: page.value, size: size.value, keyword: keyword.value }
    if (statusFilter.value !== null && statusFilter.value !== '') params.status = statusFilter.value
    if (categoryFilter.value) params.xmleibie = categoryFilter.value
    if (deptFilter.value) params.bmid = deptFilter.value
    const data = await listProjects(params)
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

onMounted(async () => {
  load()
  categories.value = await listProjectCategories()
  deptOptions.value = await listDepartments().catch(() => [])
})

// ===== 新增 / 编辑 =====
const editDialog = ref(false)
const editingId = ref(null)
const editFormRef = ref()
const blankForm = () => ({
  xiangmuname: '',
  pianqu: '',
  bmid: null,
  xiangmudizhi: '',
  xiangmuyezhu: '',
  xmleibie: '',
  zijinleixing: '',
  Status: 0,
  StatusRemark: '',
  shenbaoriqi: '',
  daijiandanwei: '',
  shejidanwei: '',
  jianlidanwei: '',
  shigongdanwei: '',
  lianxiren: '',
  dianhua: '',
  isyijiao: false,
  yijiaoriqi: '',
  isguidang: false,
  guidangriqi: '',
  Remark: '',
})
const editForm = reactive(blankForm())
const editRules = {
  xiangmuname: [{ required: true, message: '请输入项目名称', trigger: 'blur' }],
}

// 日期字段空串转 null,有值原样传给后端
function dateOrNull(v) {
  return v ? v : null
}

function buildPayload() {
  return {
    pianqu: editForm.pianqu,
    bmid: editForm.bmid,
    xiangmuname: editForm.xiangmuname.trim(),
    xiangmudizhi: editForm.xiangmudizhi,
    xiangmuyezhu: editForm.xiangmuyezhu,
    xmleibie: editForm.xmleibie,
    zijinleixing: editForm.zijinleixing,
    Status: editForm.Status,
    StatusRemark: editForm.StatusRemark,
    shenbaoriqi: dateOrNull(editForm.shenbaoriqi),
    daijiandanwei: editForm.daijiandanwei,
    shejidanwei: editForm.shejidanwei,
    jianlidanwei: editForm.jianlidanwei,
    shigongdanwei: editForm.shigongdanwei,
    lianxiren: editForm.lianxiren,
    dianhua: editForm.dianhua,
    isyijiao: editForm.isyijiao,
    yijiaoriqi: dateOrNull(editForm.yijiaoriqi),
    isguidang: editForm.isguidang,
    guidangriqi: dateOrNull(editForm.guidangriqi),
    Remark: editForm.Remark,
  }
}

function openCreate() {
  editingId.value = null
  Object.assign(editForm, blankForm())
  // 新增工程归属登录人部门(照旧系统,后端也会强制)
  editForm.bmid = auth.user?.departments?.[0]?.id ?? null
  editDialog.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(editForm, blankForm(), {
    pianqu: row.pianqu,
    bmid: row.bmid ?? null,
    xiangmuname: row.xiangmuname,
    xiangmudizhi: row.xiangmudizhi,
    xiangmuyezhu: row.xiangmuyezhu,
    xmleibie: row.xmleibie,
    zijinleixing: row.zijinleixing,
    Status: row.Status,
    StatusRemark: row.StatusRemark,
    shenbaoriqi: row.shenbaoriqi || '',
    daijiandanwei: row.daijiandanwei,
    shejidanwei: row.shejidanwei,
    jianlidanwei: row.jianlidanwei,
    shigongdanwei: row.shigongdanwei,
    lianxiren: row.lianxiren,
    dianhua: row.dianhua,
    isyijiao: row.isyijiao,
    yijiaoriqi: row.yijiaoriqi || '',
    isguidang: row.isguidang,
    guidangriqi: row.guidangriqi || '',
    Remark: row.Remark || '',
  })
  editDialog.value = true
}

const editSaving = ref(false)
async function submitEdit() {
  if (editSaving.value) return  // 防双击重复提交
  editSaving.value = true
  try {
    await editFormRef.value.validate()
    if (editingId.value == null) {
      await createProject(buildPayload())
    } else {
      await updateProject(editingId.value, buildPayload())
    }
    ElMessage.success('保存成功')
    editDialog.value = false
    load()
  } finally { editSaving.value = false }
}

// ===== 删除 =====
async function remove(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除工程「${row.xiangmuname}」?操作不可恢复。`,
      '删除工程',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  await deleteProject(row.id)
  ElMessage.success('已删除')
  load()
}

// ===== 详情抽屉:进度 / 问题 / 附件 =====
const auth = useAuthStore()
const me = auth.user?.username || ''
// 编辑弹窗可选部门:超管可选全部;普通用户仅限本人部门(多部门时自选,单部门固定)
const formDeptOptions = computed(() => {
  if (auth.user?.is_superuser) return deptOptions.value
  return (auth.user?.departments || []).map((d) => ({ id: d.id, name: d.name }))
})
const deptLocked = computed(
  () => !auth.user?.is_superuser && (auth.user?.departments || []).length <= 1
)
const detailVisible = ref(false)
const detailProject = ref(null)
const activeTab = ref('jindu')
const jinduRows = ref([])
const jianguanRows = ref([])
const fujianRows = ref([])
const detailLoading = ref(false)
const uploadUrl = computed(() => (detailProject.value ? fujianUploadUrl(detailProject.value.id) : ''))
const uploadHeaders = computed(() => ({ Authorization: `Bearer ${localStorage.getItem('token')}` }))

function fmtSize(n) {
  if (n == null) return ''
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function fmtTime(v) {
  return v ? v.slice(0, 16) : ''
}

async function openDetail(row) {
  detailProject.value = row
  activeTab.value = 'jindu'
  detailVisible.value = true
  await loadDetail()
}

async function loadDetail() {
  const id = detailProject.value.id
  detailLoading.value = true
  try {
    const [j, q, f] = await Promise.all([listJindu(id), listJianguan(id), listFujian(id)])
    jinduRows.value = j
    jianguanRows.value = q
    fujianRows.value = f
  } finally {
    detailLoading.value = false
  }
}

// --- 进度 ---
const jinduDialog = ref(false)
const jinduEditingId = ref(null)
const jinduForm = reactive({ jindu: '', jinduzhuangtai: 0 })
// 状态联动:用户没手动输入过描述时,描述跟随所选状态名;手动编辑过则不再覆盖
let jinduTouched = false

function onJinduStatusChange(val) {
  if (jinduEditingId.value != null || jinduTouched) return
  jinduForm.jindu = statusText(val)
}

function onJinduInput() {
  jinduTouched = jinduForm.jindu.trim() !== '' && jinduForm.jindu !== statusText(jinduForm.jinduzhuangtai)
}

function openAddJindu() {
  jinduEditingId.value = null
  jinduTouched = false
  const st = detailProject.value.Status ?? 0
  // 默认描述为当前状态名,用户可直接补充日期等细节
  Object.assign(jinduForm, { jindu: statusText(st), jinduzhuangtai: st })
  jinduDialog.value = true
}

function openEditJindu(row) {
  jinduEditingId.value = row.id
  jinduTouched = true // 编辑模式不动描述
  Object.assign(jinduForm, { jindu: row.jindu, jinduzhuangtai: row.jinduzhuangtai })
  jinduDialog.value = true
}

// 主表状态可能被联动/回滚,刷新列表并同步详情头部
async function syncProjectHead() {
  await load()
  const fresh = rows.value.find((r) => r.id === detailProject.value.id)
  if (fresh) Object.assign(detailProject.value, fresh)
}

const jinduSaving = ref(false)
async function submitJindu() {
  if (jinduSaving.value) return  // 防双击重复提交
  if (!jinduForm.jindu.trim()) {
    ElMessage.warning('请填写进度描述')
    return
  }
  jinduSaving.value = true
  try {
    if (jinduEditingId.value == null) {
      await addJindu(detailProject.value.id, {
        jindu: jinduForm.jindu.trim(),
        jinduzhuangtai: jinduForm.jinduzhuangtai,
      })
      ElMessage.success('已添加进度,工程状态已同步')
    } else {
      await updateJindu(detailProject.value.id, jinduEditingId.value, jinduForm.jindu.trim())
      ElMessage.success('已保存')
    }
    jinduDialog.value = false
    await loadDetail()
    await syncProjectHead()
  } finally { jinduSaving.value = false }
}

async function removeJindu(row) {
  try {
    await ElMessageBox.confirm('删除后工程状态将回滚为最新一条进度记录的状态,确定删除?', '删除进度', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await deleteJindu(detailProject.value.id, row.id)
  ElMessage.success('已删除')
  await loadDetail()
  await syncProjectHead()
}

// --- 问题 ---
const issueDialog = ref(false)
const issueEditingId = ref(null)
const issueForm = reactive({ qingkuangshuoming: '' })

function openAddIssue() {
  issueEditingId.value = null
  issueForm.qingkuangshuoming = ''
  issueDialog.value = true
}

function openEditIssue(row) {
  issueEditingId.value = row.id
  issueForm.qingkuangshuoming = row.qingkuangshuoming
  issueDialog.value = true
}

const issueSaving = ref(false)
async function submitIssue() {
  if (issueSaving.value) return  // 防双击重复提交
  if (!issueForm.qingkuangshuoming.trim()) {
    ElMessage.warning('请填写情况说明')
    return
  }
  issueSaving.value = true
  try {
    if (issueEditingId.value == null) {
      await addJianguan(detailProject.value.id, issueForm.qingkuangshuoming.trim())
      ElMessage.success('已添加问题')
    } else {
      await updateJianguan(detailProject.value.id, issueEditingId.value, issueForm.qingkuangshuoming.trim())
      ElMessage.success('已保存')
    }
    issueDialog.value = false
    loadDetail()
  } finally { issueSaving.value = false }
}

async function toggleResolve(row) {
  await resolveJianguan(detailProject.value.id, row.id, !row.isjiejue)
  ElMessage.success(row.isjiejue ? '已撤销解决' : '已标记解决')
  loadDetail()
}

async function removeIssue(row) {
  try {
    await ElMessageBox.confirm('确定删除该问题记录?', '删除问题', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await deleteJianguan(detailProject.value.id, row.id)
  ElMessage.success('已删除')
  loadDetail()
}

// --- 附件 ---
function beforeUpload(file) {
  if (file.size > 50 * 1024 * 1024) {
    ElMessage.warning(`${file.name} 超过 50MB 限制`)
    return false
  }
  return true
}

async function onUploadError() {
  ElMessage.error('上传失败')
}

async function onUploadSuccess() {
  ElMessage.success('上传成功')
  loadDetail()
}

// --- 附件图片弹窗预览:滚轮/按钮在多张图片间切换 ---
const IMG_EXTS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp']
const isImage = (row) => IMG_EXTS.some((e) => (row.wjname || '').toLowerCase().endsWith(e))
const previewVisible = ref(false)
const previewList = ref([]) // { id, wjname, url }
const previewIndex = ref(0)
const previewLoading = ref(false)

async function openPreview(row) {
  const images = fujianRows.value.filter(isImage)
  if (!images.length) return
  previewLoading.value = true
  previewVisible.value = true
  try {
    // 并行为每张图片取短时效下载令牌,有效期 10 分钟足够浏览
    const withUrl = await Promise.all(
      images.map(async (r) => {
        const data = await createDownloadToken(detailProject.value.id, r.id)
        return { id: r.id, wjname: r.wjname, url: data.url }
      })
    )
    previewList.value = withUrl
    previewIndex.value = Math.max(0, withUrl.findIndex((r) => r.id === row.id))
  } finally {
    previewLoading.value = false
  }
}

function onPreviewWheel(e) {
  if (previewList.value.length < 2) return
  if (e.deltaY > 0) previewIndex.value = Math.min(previewList.value.length - 1, previewIndex.value + 1)
  else previewIndex.value = Math.max(0, previewIndex.value - 1)
}

async function downloadFujian(row) {
  // 先取短时效下载令牌再开直链,登录令牌不进 URL
  const data = await createDownloadToken(detailProject.value.id, row.id)
  window.open(data.url)
}

async function removeFujian(row) {
  try {
    await ElMessageBox.confirm(`确定删除附件「${row.wjname}」?`, '删除附件', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消',
    })
  } catch {
    return
  }
  await deleteFujian(detailProject.value.id, row.id)
  ElMessage.success('已删除')
  loadDetail()
}
</script>

<template>
  <el-card>
    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="项目名称 / 地址 / 业主 / 联系人"
        clearable
        style="width: 260px"
        @keyup.enter="search"
        @clear="search"
      />
      <el-select
        v-model="statusFilter"
        placeholder="状态"
        clearable
        style="width: 130px"
        @change="search"
      >
        <el-option v-for="o in STATUS_OPTIONS" :key="o.value" :value="o.value" :label="o.text" />
      </el-select>
      <el-select
        v-model="categoryFilter"
        placeholder="项目类别"
        clearable
        filterable
        style="width: 150px"
        @change="search"
      >
        <el-option v-for="c in categories" :key="c" :value="c" :label="c" />
      </el-select>
      <el-select
        v-model="deptFilter"
        placeholder="营业所"
        clearable
        filterable
        style="width: 140px"
        @change="search"
      >
        <el-option v-for="d in deptOptions" :key="d.id" :value="d.id" :label="d.name" />
      </el-select>
      <el-button type="primary" @click="search">查询</el-button>
      <div class="spacer" />
      <el-button type="primary" @click="openCreate">新增工程</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="xiangmuname" label="项目名称" min-width="200" show-overflow-tooltip />
      <el-table-column prop="pianqu" label="片区" width="100" show-overflow-tooltip />
      <el-table-column prop="bumen" label="营业所" width="100" show-overflow-tooltip />
      <el-table-column prop="xiangmuyezhu" label="业主" min-width="120" show-overflow-tooltip />
      <el-table-column prop="shigongdanwei" label="施工单位" min-width="150" show-overflow-tooltip />
      <el-table-column prop="xmleibie" label="项目类别" width="110" show-overflow-tooltip />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag :type="statusTag(row.Status)" size="small">{{ statusText(row.Status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="shenbaoriqi" label="申报日期" width="110" />
      <el-table-column prop="lianxiren" label="联系人" width="90" />
      <el-table-column prop="dianhua" label="电话" width="130" />
      <el-table-column prop="CreateTime" label="创建时间" width="170" />
      <el-table-column label="操作" width="170" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openDetail(row)">详情</el-button>
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button v-if="auth.hasPerm('project:manage')" link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="page"
      v-model:page-size="size"
      :total="total"
      :page-sizes="[10, 20, 50]"
      layout="total, sizes, prev, pager, next"
      style="margin-top: 14px; justify-content: flex-end"
      @current-change="load"
      @size-change="search"
    />
  </el-card>

  <!-- 新增 / 编辑 -->
  <el-dialog
    v-model="editDialog"
    :title="editingId == null ? '新增工程' : '编辑工程'"
    width="720px"
    top="6vh"
    class="std-dialog"
  >
    <el-form ref="editFormRef" :model="editForm" :rules="editRules" label-width="90px">
      <div class="section-title">基本信息</div>
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="项目名称" prop="xiangmuname">
            <el-input v-model="editForm.xiangmuname" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="片区">
            <el-input v-model="editForm.pianqu" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="营业所">
            <!-- 照旧 Gongchengguanli 编辑页:bmid 为部门下拉;普通用户仅限本人部门 -->
            <el-select
              v-model="editForm.bmid"
              clearable
              filterable
              placeholder="选择部门"
              style="width: 100%"
              :disabled="deptLocked"
            >
              <el-option v-for="d in formDeptOptions" :key="d.id" :value="d.id" :label="d.name" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="项目地址">
            <el-input v-model="editForm.xiangmudizhi" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="项目业主">
            <el-input v-model="editForm.xiangmuyezhu" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="项目类别">
            <el-input v-model="editForm.xmleibie" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="资金类型">
            <el-input v-model="editForm.zijinleixing" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="申报日期">
            <el-date-picker
              v-model="editForm.shenbaoriqi"
              type="date"
              value-format="YYYY-MM-DD"
              style="width: 100%"
            />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="状态">
            <el-select v-model="editForm.Status" style="width: 100%">
              <el-option v-for="o in STATUS_OPTIONS" :key="o.value" :value="o.value" :label="o.text" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="状态备注">
            <el-input v-model="editForm.StatusRemark" />
          </el-form-item>
        </el-col>
      </el-row>

      <div class="section-title">相关单位与联系</div>
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="代建单位">
            <el-input v-model="editForm.daijiandanwei" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="设计单位">
            <el-input v-model="editForm.shejidanwei" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="监理单位">
            <el-input v-model="editForm.jianlidanwei" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="施工单位">
            <el-input v-model="editForm.shigongdanwei" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="联系人">
            <el-input v-model="editForm.lianxiren" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="电话">
            <el-input v-model="editForm.dianhua" />
          </el-form-item>
        </el-col>
      </el-row>

      <div class="section-title">移交 / 归档</div>
      <el-row :gutter="12">
        <el-col :span="12">
          <el-form-item label="已移交">
            <el-switch v-model="editForm.isyijiao" />
            <el-date-picker
              v-if="editForm.isyijiao"
              v-model="editForm.yijiaoriqi"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="移交日期"
              style="width: auto; margin-left: 10px"
            />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="已归档">
            <el-switch v-model="editForm.isguidang" />
            <el-date-picker
              v-if="editForm.isguidang"
              v-model="editForm.guidangriqi"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="归档日期"
              style="width: auto; margin-left: 10px"
            />
          </el-form-item>
        </el-col>
        <el-col :span="24">
          <el-form-item label="备注">
            <el-input v-model="editForm.Remark" type="textarea" :rows="2" />
          </el-form-item>
        </el-col>
      </el-row>
    </el-form>
    <template #footer>
      <el-button @click="editDialog = false">取消</el-button>
      <el-button type="primary" @click="submitEdit">保存</el-button>
    </template>
  </el-dialog>

  <!-- 详情抽屉:进度 / 问题 / 附件 -->
  <el-drawer
    v-model="detailVisible"
    :title="detailProject?.xiangmuname || '工程详情'"
    size="62%"
    :destroy-on-close="false"
  >
    <div v-if="detailProject" v-loading="detailLoading">
      <div class="detail-head">
        <el-tag :type="statusTag(detailProject.Status)" size="large">
          {{ statusText(detailProject.Status) }}
        </el-tag>
        <span class="head-meta">申报日期 {{ detailProject.shenbaoriqi || '—' }}</span>
        <span class="head-meta">业主 {{ detailProject.xiangmuyezhu || '—' }}</span>
        <span class="head-meta">施工单位 {{ detailProject.shigongdanwei || '—' }}</span>
      </div>

      <el-tabs v-model="activeTab">
        <!-- 进度 -->
        <el-tab-pane label="进度" name="jindu">
          <div class="tab-toolbar">
            <span class="tab-hint">添加进度会同步工程的当前状态</span>
            <div class="spacer" />
            <el-button type="primary" size="small" @click="openAddJindu">添加进度</el-button>
          </div>
          <el-table :data="jinduRows" stripe size="small">
            <el-table-column prop="riqi" label="日期" width="160">
              <template #default="{ row }">{{ fmtTime(row.riqi) }}</template>
            </el-table-column>
            <el-table-column prop="jindu" label="进度描述" min-width="220" show-overflow-tooltip />
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="statusTag(row.jinduzhuangtai)" size="small">
                  {{ statusText(row.jinduzhuangtai) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="CreateUser" label="创建人" width="90" />
            <el-table-column label="操作" width="110">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="openEditJindu(row)">编辑</el-button>
                <el-button
                  v-if="row.CreateUser === me"
                  link
                  type="danger"
                  size="small"
                  @click="removeJindu(row)"
                >删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 问题 -->
        <el-tab-pane label="问题" name="jianguan">
          <div class="tab-toolbar">
            <span class="tab-hint">{{ jianguanRows.filter((r) => !r.isjiejue).length }} 个未解决</span>
            <div class="spacer" />
            <el-button type="primary" size="small" @click="openAddIssue">添加问题</el-button>
          </div>
          <el-table :data="jianguanRows" stripe size="small">
            <el-table-column prop="riqi" label="日期" width="160">
              <template #default="{ row }">{{ fmtTime(row.riqi) }}</template>
            </el-table-column>
            <el-table-column prop="qingkuangshuoming" label="情况说明" min-width="260" show-overflow-tooltip />
            <el-table-column label="是否解决" width="100">
              <template #default="{ row }">
                <el-tag :type="row.isjiejue ? 'success' : 'warning'" size="small">
                  {{ row.isjiejue ? '✓ 已解决' : '● 未解决' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="CreateUser" label="创建人" width="90" />
            <el-table-column label="操作" width="200">
              <template #default="{ row }">
                <el-button link :type="row.isjiejue ? 'warning' : 'success'" size="small" @click="toggleResolve(row)">
                  {{ row.isjiejue ? '撤销解决' : '标记解决' }}
                </el-button>
                <el-button link type="primary" size="small" @click="openEditIssue(row)">编辑</el-button>
                <el-button
                  v-if="row.CreateUser === me"
                  link
                  type="danger"
                  size="small"
                  @click="removeIssue(row)"
                >删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <!-- 附件 -->
        <el-tab-pane :label="`附件(${fujianRows.length})`" name="fujian">
          <div class="tab-toolbar">
            <span class="tab-hint">单个文件不超过 50MB</span>
            <div class="spacer" />
            <el-upload
              :action="uploadUrl"
              :headers="uploadHeaders"
              multiple
              show-file-list
              :before-upload="beforeUpload"
              :on-success="onUploadSuccess"
              :on-error="onUploadError"
            >
              <el-button type="primary" size="small">上传附件</el-button>
            </el-upload>
          </div>
          <el-table :data="fujianRows" stripe size="small">
            <el-table-column prop="wjname" label="文件名" min-width="240" show-overflow-tooltip />
            <el-table-column label="大小" width="90">
              <template #default="{ row }">{{ fmtSize(row.size) }}</template>
            </el-table-column>
            <el-table-column prop="CreateUser" label="上传人" width="90" />
            <el-table-column label="上传时间" width="160">
              <template #default="{ row }">{{ fmtTime(row.CreateTime) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="160">
              <template #default="{ row }">
                <el-button v-if="isImage(row)" link type="primary" size="small" @click="openPreview(row)">
                  查看
                </el-button>
                <el-button link type="primary" size="small" @click="downloadFujian(row)">下载</el-button>
                <el-button
                  v-if="row.CreateUser === me"
                  link
                  type="danger"
                  size="small"
                  @click="removeFujian(row)"
                >删除</el-button>
              </template>
            </el-table-column>
          </el-table>
          <el-alert
            v-if="fujianRows.length"
            type="info"
            :closable="false"
            show-icon
            title="历史迁移的附件若原文件尚未复制到新系统,下载会提示文件丢失"
            class="fujian-tip"
          />
        </el-tab-pane>
      </el-tabs>
    </div>

    <!-- 添加/编辑进度 -->
    <el-dialog
      v-model="jinduDialog"
      :title="jinduEditingId == null ? '添加进度' : '编辑进度'"
      width="480px"
      append-to-body
      class="std-dialog"
    >
      <el-form label-width="80px">
        <el-form-item v-if="jinduEditingId == null" label="状态">
          <el-select
            v-model="jinduForm.jinduzhuangtai"
            style="width: 100%"
            @change="onJinduStatusChange"
          >
            <el-option v-for="o in STATUS_OPTIONS" :key="o.value" :value="o.value" :label="o.text" />
          </el-select>
        </el-form-item>
        <el-form-item label="进度描述">
          <el-input
            v-model="jinduForm.jindu"
            type="textarea"
            :rows="3"
            placeholder="已预填状态名,可补充日期等细节"
            @input="onJinduInput"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="jinduDialog = false">取消</el-button>
        <el-button type="primary" @click="submitJindu">保存</el-button>
      </template>
    </el-dialog>

    <!-- 添加/编辑问题 -->
    <el-dialog
      v-model="issueDialog"
      :title="issueEditingId == null ? '添加问题' : '编辑问题'"
      width="480px"
      append-to-body
      class="std-dialog"
    >
      <el-form label-width="80px">
        <el-form-item label="情况说明">
          <el-input v-model="issueForm.qingkuangshuoming" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="issueDialog = false">取消</el-button>
        <el-button type="primary" @click="submitIssue">保存</el-button>
      </template>
    </el-dialog>

    <!-- 附件图片预览:滚轮/按钮切换 -->
    <el-dialog
      v-model="previewVisible"
      :title="previewList[previewIndex]?.wjname || '附件预览'"
      width="860px"
      top="4vh"
      append-to-body
      class="std-dialog preview-dialog"
    >
      <div
        v-loading="previewLoading"
        class="preview-body"
        @wheel.prevent="onPreviewWheel"
      >
        <img
          v-if="previewList[previewIndex]"
          :src="previewList[previewIndex].url"
          :key="previewList[previewIndex].id"
          class="preview-img"
        />
        <div v-if="previewList.length > 1" class="preview-nav">
          <el-button size="small" :disabled="previewIndex === 0" @click="previewIndex--">
            上一张
          </el-button>
          <span class="preview-pos">{{ previewIndex + 1 }} / {{ previewList.length }}</span>
          <el-button
            size="small"
            :disabled="previewIndex === previewList.length - 1"
            @click="previewIndex++"
          >
            下一张
          </el-button>
        </div>
        <div class="preview-hint">滚轮上下滚动可切换图片</div>
      </div>
    </el-dialog>
  </el-drawer>
</template>

<style scoped>
.toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 14px;
}
.spacer {
  flex: 1;
}
/* 分节标题:浅紫底 + 左侧紫条,与统一弹窗的紫题头呼应 */
.section-title {
  font-weight: 600;
  font-size: 13px;
  line-height: 20px;
  margin: 2px 0 12px;
  padding: 5px 10px 5px 12px;
  color: #533afd;
  background: #f4f2ff;
  border-left: 3px solid #533afd;
  border-radius: 4px;
}
.detail-head {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 12px;
}
.head-meta {
  color: #606266;
  font-size: 13px;
}
.tab-toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 10px;
}
.tab-hint {
  color: #909399;
  font-size: 12px;
}
.fujian-tip {
  margin-top: 10px;
}
.preview-body {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  min-height: 300px;
}
.preview-img {
  max-width: 100%;
  max-height: 66vh;
  object-fit: contain;
  border-radius: 8px;
  box-shadow: 0 2px 10px rgba(16, 24, 40, .12);
}
.preview-nav {
  display: flex;
  align-items: center;
  gap: 14px;
}
.preview-pos {
  color: #5a5752;
  font-size: 13px;
  font-weight: 600;
}
.preview-hint {
  color: #8a867f;
  font-size: 12px;
}
</style>
