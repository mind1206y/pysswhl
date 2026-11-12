<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  claimIp, createIpNetwork, deleteIpNetwork, exportIps, getIpDicts,
  listIps, recycleIp,
} from '@/api/ipadress'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const isSuper = computed(() => !!auth.user?.is_superuser)
const username = computed(() => auth.user?.username || '')

const dicts = reactive({
  netnames: [], departments: [], default_bmid: null,
  locations: [], uses: [], perms: { view: true, manage: false },
})

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(25)
const filters = reactive({ keyword: '', netnames: [], ipzt: '' })

function buildParams(withPage = true) {
  const p = {}
  if (withPage) { p.page = page.value; p.size = size.value }
  if (filters.keyword) p.keyword = filters.keyword
  if (filters.netnames.length) p.netname = filters.netnames.join(',')
  if (filters.ipzt) p.ipzt = filters.ipzt
  return p
}

async function load() {
  loading.value = true
  try {
    const data = await listIps(buildParams())
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
  Object.assign(filters, { keyword: '', netnames: [], ipzt: '' })
  search()
}

function canRecycle(row) {
  return row.zt === '已使用' && (isSuper.value || row.sqren === username.value)
}

async function loadDicts() {
  const d = await getIpDicts()
  Object.assign(dicts, d)
  if (dicts.default_bmid == null && dicts.departments.length) {
    dicts.default_bmid = dicts.departments[0].id
  }
}

onMounted(async () => {
  await loadDicts()
  load()
})

// ===== 添加网络 =====
const netDialog = ref(false)
const netFormRef = ref()
const netSaving = ref(false)
const netForm = reactive({ netname: '', net: '', bmid: null })
const netRules = {
  netname: [{ required: true, message: '请输入网络名称', trigger: 'blur' }],
  net: [
    { required: true, message: '请输入网段', trigger: 'blur' },
    {
      validator: (rule, value, callback) =>
        /^\d{1,3}\.\d{1,3}\.\d{1,3}$/.test(value || '')
          ? callback()
          : callback(new Error('网段格式无效，如：192.168.1')),
      trigger: 'blur',
    },
  ],
}

function openNetDialog() {
  Object.assign(netForm, { netname: '', net: '', bmid: dicts.default_bmid })
  netDialog.value = true
}

async function submitNet() {
  if (netSaving.value) return  // 防双击重复提交
  netSaving.value = true
  try {
    await netFormRef.value.validate()
    await createIpNetwork({
      netname: netForm.netname,
      net: netForm.net,
      bmid: netForm.bmid,
    })
    ElMessage.success('初始化成功！共创建 253 个 IP')
    netDialog.value = false
    await loadDicts()
    search()
  } finally { netSaving.value = false }
}

// ===== 领用 / 修改分配 =====
const claimDialog = ref(false)
const claimFormRef = ref()
const claimForm = reactive({
  id: null, ip: '', netname: '', syren: '', didian: '综合办', yongtu: '办公',
})
const claimRules = {
  syren: [{ required: true, message: '请输入使用人', trigger: 'blur' }],
  didian: [{ required: true, message: '请选择或输入位置', trigger: 'change' }],
  yongtu: [{ required: true, message: '请选择或输入用途', trigger: 'change' }],
}

function openClaim(row) {
  Object.assign(claimForm, {
    id: row.id,
    ip: row.ip,
    netname: row.netname,
    syren: row.syren || '',
    didian: row.didian || '综合办',
    yongtu: row.yongtu || '办公',
  })
  claimDialog.value = true
}

async function submitClaim() {
  await claimFormRef.value.validate()
  await claimIp(claimForm.id, {
    syren: claimForm.syren,
    didian: claimForm.didian,
    yongtu: claimForm.yongtu,
  })
  ElMessage.success('分配成功！')
  claimDialog.value = false
  load()
}

// ===== 收回 =====
async function doRecycle(row) {
  try {
    await ElMessageBox.confirm(`确定要收回 IP ${row.ip} 吗？`, '确认', { type: 'warning' })
  } catch {
    return
  }
  await recycleIp(row.id)
  ElMessage.success('IP 已回收')
  load()
}

// ===== 删除网络 =====
const delDialog = ref(false)
const delNet = ref('')

function openDelDialog() {
  delNet.value = ''
  delDialog.value = true
}

async function submitDelNet() {
  if (!delNet.value) {
    ElMessage.warning('请选择要删除的网络')
    return
  }
  try {
    await ElMessageBox.confirm(
      `删除网络「${delNet.value}」会同时删除该网段全部 253 个 IP，确定继续吗？`,
      '确认删除',
      { type: 'warning' },
    )
  } catch {
    return
  }
  await deleteIpNetwork(delNet.value)
  ElMessage.success('删除成功')
  delDialog.value = false
  await loadDicts()
  search()
}

async function doExport() {
  await exportIps(buildParams(false))
  ElMessage.success('已导出 Excel')
}
</script>

<template>
  <div class="ip-page">
    <el-card shadow="never" class="filter-card">
      <div class="filter-title">IP 地址管理</div>
      <el-form inline class="filter-form">
        <el-form-item label="关键字">
          <el-input v-model="filters.keyword" clearable style="width: 240px"
            placeholder="网络名称 / 地点 / 用途 / 使用人" @keyup.enter="search" />
        </el-form-item>
        <el-form-item label="网段">
          <el-select v-model="filters.netnames" multiple collapse-tags collapse-tags-tooltip
            filterable clearable placeholder="选择网段（可多选）" style="width: 240px"
            @change="search">
            <el-option v-for="n in dicts.netnames" :key="n.value" :label="n.text" :value="n.value">
              <span>{{ n.text }}</span>
              <span class="opt-creator" :title="n.creator ? `创建人：${n.creator}` : '未记录创建人'">
                {{ n.creator || '—' }}
              </span>
            </el-option>
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-radio-group v-model="filters.ipzt" @change="search">
            <el-radio-button label="">全部</el-radio-button>
            <el-radio-button label="可领用">可领用</el-radio-button>
            <el-radio-button label="已占用">已占用</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="search">查询</el-button>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <div class="toolbar">
      <el-button type="primary" size="small" @click="openNetDialog">添加网络</el-button>
      <el-button size="small" @click="doExport">导出</el-button>
      <el-button v-if="dicts.perms.manage" type="danger" plain size="small"
        @click="openDelDialog">删除网络</el-button>
      <span class="toolbar-hint">共 {{ total }} 条 · 双击行可领用 / 修改分配信息</span>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe size="small"
      height="calc(100vh - 300px)" row-key="id" @row-dblclick="openClaim">
      <el-table-column prop="netname" label="网络名称" width="170" show-overflow-tooltip />
      <el-table-column prop="bm" label="登记部门" width="130" show-overflow-tooltip />
      <el-table-column prop="netdate" label="登记日期" width="145" />
      <el-table-column prop="net" label="网段" width="130" />
      <el-table-column label="IP" width="100" align="center">
        <template #default="{ row }">
          <span class="ip-badge">{{ row.numb }}</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100" align="center">
        <template #default="{ row }">
          <el-button v-if="row.zt === '未使用'" link type="success" size="small"
            @click.stop="openClaim(row)">可领用</el-button>
          <el-tooltip v-else :content="row.zt || '已占用'" placement="top">
            <span class="status-dot" />
          </el-tooltip>
        </template>
      </el-table-column>
      <el-table-column prop="syren" label="使用人" width="110" show-overflow-tooltip />
      <el-table-column prop="didian" label="位置" min-width="150" show-overflow-tooltip />
      <el-table-column prop="yongtu" label="用途" width="120" show-overflow-tooltip />
      <el-table-column prop="sqdate" label="操作日期" width="145" />
      <el-table-column prop="sqren" label="申请人" width="110" />
      <el-table-column label="收回操作" width="100" align="center">
        <template #default="{ row }">
          <el-button v-if="canRecycle(row)" link type="danger" size="small" title="收回 IP"
            @click.stop="doRecycle(row)">
            <el-icon><Delete /></el-icon>
          </el-button>
          <span v-else>-</span>
        </template>
      </el-table-column>
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[25, 50, 100]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>

    <!-- 添加网络 -->
    <el-dialog v-model="netDialog" title="初始化 IP 网络段" width="440px"
      :close-on-click-modal="false">
      <el-alert type="info" show-icon :closable="false" class="tip-alert"
        title="将按网段自动创建 2~254 共 253 个 IP，初始状态为「未使用」" />
      <el-form ref="netFormRef" :model="netForm" :rules="netRules" label-width="90px">
        <el-form-item label="网络名称" prop="netname">
          <el-input v-model="netForm.netname" placeholder="如：售水91段内网" />
        </el-form-item>
        <el-form-item label="网段" prop="net">
          <el-input v-model="netForm.net" placeholder="如：192.168.1" />
        </el-form-item>
        <el-form-item v-if="isSuper || dicts.departments.length > 1" label="登记部门">
          <el-select v-model="netForm.bmid" clearable filterable style="width: 100%"
            placeholder="（不选则取本人部门）">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="netDialog = false">取消</el-button>
        <el-button type="primary" @click="submitNet">提交</el-button>
      </template>
    </el-dialog>

    <!-- 领用 IP -->
    <el-dialog v-model="claimDialog" title="领用 IP 地址" width="480px"
      :close-on-click-modal="false">
      <div class="assign-tip">
        您正在为 <span class="assign-ip">{{ claimForm.ip }}</span> 的 IP 分配使用
        <span v-if="claimForm.netname" class="assign-net">（{{ claimForm.netname }}）</span>
      </div>
      <el-form ref="claimFormRef" :model="claimForm" :rules="claimRules" label-width="80px">
        <el-form-item label="使用人" prop="syren">
          <el-input v-model="claimForm.syren" placeholder="请输入使用人" />
        </el-form-item>
        <el-form-item label="位置" prop="didian">
          <el-select v-model="claimForm.didian" filterable allow-create default-first-option
            style="width: 100%" placeholder="请选择或输入位置">
            <el-option v-for="v in dicts.locations" :key="v" :label="v" :value="v" />
          </el-select>
        </el-form-item>
        <el-form-item label="用途" prop="yongtu">
          <el-select v-model="claimForm.yongtu" filterable allow-create default-first-option
            style="width: 100%" placeholder="请选择或输入用途">
            <el-option v-for="v in dicts.uses" :key="v" :label="v" :value="v" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="claimDialog = false">取消</el-button>
        <el-button type="primary" @click="submitClaim">提交</el-button>
      </template>
    </el-dialog>

    <!-- 删除网络 -->
    <el-dialog v-model="delDialog" title="删除网络" width="420px"
      :close-on-click-modal="false">
      <el-form label-width="90px">
        <el-form-item label="网络名称">
          <el-select v-model="delNet" filterable style="width: 100%" placeholder="请选择网络">
            <el-option v-for="n in dicts.netnames" :key="n.value" :label="n.text" :value="n.value">
              <span>{{ n.text }}</span>
              <span class="opt-creator">{{ n.creator || '—' }}</span>
            </el-option>
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="delDialog = false">取消</el-button>
        <el-button type="danger" @click="submitDelNet">删除</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.ip-page {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.filter-card :deep(.el-card__body) {
  padding: 10px 14px;
}
.filter-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 8px;
}
.filter-form :deep(.el-form-item) {
  margin-bottom: 4px;
  margin-right: 12px;
}
.toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.toolbar-hint {
  margin-left: auto;
  color: #909399;
  font-size: 12px;
}
.pager {
  display: flex;
  justify-content: flex-end;
}
.opt-creator {
  float: right;
  margin-left: 16px;
  color: #9aa8b8;
  font-size: 12px;
}
.ip-badge {
  display: inline-block;
  padding: 1px 12px;
  border: 1.5px solid #d90000;
  border-radius: 50%;
  color: #d90000;
  font-weight: 700;
  line-height: 18px;
}
.status-dot {
  display: inline-block;
  width: 12px;
  height: 12px;
  border-radius: 50%;
  background: #ff9800;
  box-shadow: 0 0 5px rgba(255, 152, 0, 0.5);
}
.tip-alert {
  margin-bottom: 14px;
}
.assign-tip {
  background: #f2effe;
  border-left: 3px solid #533afd;
  border-radius: 6px;
  padding: 8px 12px;
  margin-bottom: 14px;
  font-weight: 600;
  color: #1c1e54;
  font-size: 13px;
}
.assign-ip {
  color: #d9534f;
}
.assign-net {
  color: #7c8ba0;
  font-weight: 400;
}
</style>
