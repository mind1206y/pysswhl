<template>
  <div class="ot-page" v-loading="loading">
    <div class="ot-banner">加班申请管理</div>

    <el-tabs v-model="activeTab" class="ot-tabs" @tab-change="onTabChange">
      <el-tab-pane label="我的加班" name="my"><MyRecords v-if="mounted.my" /></el-tab-pane>
      <el-tab-pane label="申请单管理" name="apply" v-if="perms.can_apply"><ApplyManage v-if="mounted.apply" /></el-tab-pane>
      <el-tab-pane label="核销管理" name="verify" v-if="perms.can_verify"><VerifyManage v-if="mounted.verify" /></el-tab-pane>
      <el-tab-pane label="我的审批" name="approvals" v-if="perms.is_approver"><MyApprovals v-if="mounted.approvals" /></el-tab-pane>
      <el-tab-pane label="加班汇总" name="summary" v-if="perms.can_summary"><Summary v-if="mounted.summary" /></el-tab-pane>
      <el-tab-pane label="配置管理" name="config" v-if="perms.can_config"><Config v-if="mounted.config" /></el-tab-pane>
    </el-tabs>

    <!-- 跨 Tab 共用的弹窗 -->
    <EntryDialog v-model="entryVisible" :options="entryOptions" @saved="onEntrySaved" />
    <BatchDialog v-model="batchVisible" @saved="bump" />

    <!-- 申请单明细抽屉(90%) -->
    <el-drawer v-model="drawerVisible" size="90%" class="ot-drawer" :with-header="true" destroy-on-close>
      <template #header>
        <span>{{ drawerTitle }}</span>
      </template>
      <div class="ad-info" v-if="drawerData">
        <span>月份：{{ drawerData.apply?.apply_month }}</span>
        <span>总时长：{{ Number(drawerData.apply?.total_hours || 0).toFixed(2) }}h</span>
        <span>制单人：{{ drawerData.apply?.applyUserName }}</span>
        <span>部门：{{ drawerData.apply?.deptName }}</span>
        <span>申请日期：{{ drawerData.apply?.apply_date }}</span>
        <span>操作时间：{{ drawerData.apply?.create_time }}</span>
        <el-tag size="small" round effect="light" :class="'status-' + drawerData.apply?.status">
          {{ statusText[drawerData.apply?.status] || drawerData.apply?.status }}
        </el-tag>
      </div>
      <div class="ad-body">
        <template v-if="drawerData?.apply?.status === 'draft'">
          <div class="filter-row" style="margin-bottom: 8px">
            <div class="filter-group">
              <label>备注：</label>
              <el-input v-model="drawerRemark" style="width: 320px" size="small" @change="saveDrawerRemark" />
            </div>
            <div class="filter-group">
              <label>部门：</label>
              <el-tree-select v-model="drawerDept" :data="deptTreeData" node-key="id"
                              :props="{ label: 'text', children: 'children' }" check-strictly
                              style="width: 300px" size="small" @change="saveDrawerDept" />
            </div>
          </div>
        </template>
        <el-table :data="drawerEntries" border size="small" max-height="440">
          <el-table-column prop="personnelName" label="加班人" width="90" />
          <el-table-column label="日期" width="130">
            <template #default="{ row }">{{ row.work_date }} {{ weekLabel(row.work_date) }}</template>
          </el-table-column>
          <el-table-column label="时段" width="150">
            <template #default="{ row }">
              {{ (row.start_time || '').slice(11, 16) }}-{{ (row.end_time || '').slice(11, 16) }}
              <span v-if="row.shift_type === '晚班'">（次日）</span>
            </template>
          </el-table-column>
          <el-table-column prop="raw_hours" label="原始时长" width="90" />
          <el-table-column prop="total_hours" label="折算时长" width="90" />
          <el-table-column prop="multiplier" label="倍数" width="70" />
          <el-table-column prop="reason" label="工作内容" min-width="200" show-overflow-tooltip />
        </el-table>
      </div>
      <template #footer>
        <div class="ad-footer" v-if="drawerData?.apply?.status === 'draft'">
          <el-button type="primary" size="small" @click="openAddRecords">添加人员记录</el-button>
          <el-button size="small" @click="openEntryFromDrawer">录入加班时段</el-button>
        </div>
      </template>
    </el-drawer>

    <el-dialog v-model="addRecordsVisible" title="添加人员记录到申请单" width="860px" class="ot-dialog" append-to-body>
      <div class="hint" style="margin-bottom: 8px">
        {{ addRecordsInfo }} —— 以下为同月份同类型且未被其他申请单使用的已提交记录
      </div>
      <el-table :data="addRecordsRows" border size="small" height="340"
                @selection-change="(v) => (addRecordsSelected = v)">
        <el-table-column type="selection" width="42" />
        <el-table-column prop="apply_no" label="编号" width="120" />
        <el-table-column prop="personnelName" label="加班人" width="90" />
        <el-table-column prop="applyUserName" label="录入人" width="90" />
        <el-table-column prop="work_type" label="类型" width="110" />
        <el-table-column prop="settle_type" label="结算" width="70" />
        <el-table-column prop="apply_month" label="月份" width="80" />
        <el-table-column prop="total_hours" label="总时长" width="90" />
      </el-table>
      <template #footer>
        <el-button @click="addRecordsVisible = false">取消</el-button>
        <el-button type="primary" @click="doAddRecords">添加到申请单</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, inject, onMounted, provide, reactive, ref, watch, nextTick } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import './overtime.css'
import * as api from '@/api/overtime'
import MyRecords from './tabs/MyRecords.vue'
import ApplyManage from './tabs/ApplyManage.vue'
import VerifyManage from './tabs/VerifyManage.vue'
import MyApprovals from './tabs/MyApprovals.vue'
import Summary from './tabs/Summary.vue'
import Config from './tabs/Config.vue'
import EntryDialog from './dialogs/EntryDialog.vue'
import BatchDialog from './dialogs/BatchDialog.vue'

const loading = ref(false)
const dicts = ref({
  months: [], current_month: '', work_types: [], exclusive_work_types: [],
  comp_leave_work_types: [], multi_date_work_types: [], status_text: {},
  approval_status_text: {}, approval_enabled: false,
  perms: {}, user: {}, my_personnel: null, dept_tree: [], dept_paths: {},
  personnel: [], users: [],
})
const perms = computed(() => dicts.value.perms || {})
const statusText = computed(() => dicts.value.status_text || {})
const months = computed(() => dicts.value.months || [])
const currentMonth = computed(() => dicts.value.current_month || '')
const workTypes = computed(() => dicts.value.work_types || [])
const personnel = computed(() => dicts.value.personnel || [])
const deptTree = computed(() => dicts.value.dept_tree || [])

const TABS = ['my', 'apply', 'verify', 'approvals', 'summary', 'config']
const activeTab = ref(localStorage.getItem('overtime_last_tab') || 'my')
const mounted = reactive({ my: true })
function syncMounted() {
  TABS.forEach((t) => {
    if (t === activeTab.value) mounted[t] = true
  })
}
function onTabChange(name) {
  localStorage.setItem('overtime_last_tab', name)
  syncMounted()
}
watch(activeTab, syncMounted, { immediate: true })

const tick = ref(0)
function bump() { tick.value++ }

// ---- 跨组件弹窗调度
const entryVisible = ref(false)
const entryOptions = ref({})
function openEntry(opts = {}) { entryOptions.value = { ...opts }; entryVisible.value = true }
function onEntrySaved() { bump() }

const batchVisible = ref(false)
function openBatch() { batchVisible.value = true }

const drawerVisible = ref(false)
const drawerData = ref(null)
const drawerEntries = ref([])
const drawerRemark = ref('')
const drawerDept = ref(null)
const drawerTitle = ref('申请单明细')
const addRecordsVisible = ref(false)
const addRecordsRows = ref([])
const addRecordsSelected = ref([])
const addRecordsInfo = ref('')

async function openApplyDrawer(row) {
  const data = await api.getApplyInfo(row.id)
  if (!data.success) return ElMessage.error(data.msg || '记录不存在')
  drawerData.value = data
  drawerRemark.value = data.apply?.remark || ''
  drawerDept.value = data.apply?.apply_dept_id || null
  drawerTitle.value = `${data.apply?.apply_no} - ${data.apply?.work_type}`
  drawerEntries.value = (await api.listEntries(row.id, 'apply')).rows || []
  drawerVisible.value = true
}
async function refreshDrawer() {
  if (!drawerData.value) return
  const id = drawerData.value.apply.id
  const data = await api.getApplyInfo(id)
  if (data.success) drawerData.value = data
  drawerEntries.value = (await api.listEntries(id, 'apply')).rows || []
  bump()
}
async function saveDrawerRemark(v) {
  if (!drawerData.value) return
  await api.updateApplyRemark(drawerData.value.apply.id, v)
  ElMessage.success('备注已保存')
  bump()
}
async function saveDrawerDept(v) {
  if (!drawerData.value || !v) return
  await api.updateApplyDept(drawerData.value.apply.id, v)
  ElMessage.success('部门已更新')
  await refreshDrawer()
}
function openEntryFromDrawer() {
  if (!drawerData.value) return
  openEntry({ mode: 'apply', applyId: drawerData.value.apply.id,
              workType: drawerData.value.apply.work_type,
              settleType: drawerData.value.apply.settle_type,
              applyMonth: drawerData.value.apply.apply_month,
              onSaved: refreshDrawer })
}
async function openAddRecords() {
  if (!drawerData.value) return
  const a = drawerData.value.apply
  addRecordsInfo.value = `${a.apply_no} | ${a.apply_month} | ${a.work_type}`
  const res = await api.listSubmittedRecords({ month: a.apply_month, work_type: a.work_type, rows: 200 })
  addRecordsRows.value = res.rows || []
  addRecordsVisible.value = true
}
async function doAddRecords() {
  const ids = addRecordsSelected.value.map((r) => r.id)
  if (!ids.length) return ElMessage.warning('请选择要添加的记录')
  await api.addRecordsToApply(drawerData.value.apply.id, ids)
  ElMessage.success('已添加')
  addRecordsVisible.value = false
  await refreshDrawer()
}

// ---- 通用工具
function weekLabel(d) {
  if (!d) return ''
  const dt = new Date(String(d).replace(/-/g, '/'))
  return '(周' + '日一二三四五六'[dt.getDay()] + ')'
}
function monthLabel(m) { return m && m.length === 6 ? `${m.slice(0, 4)}-${m.slice(4)}` : (m || '') }
function tagClass(s) { return 'status-tag status-' + (s || '') }
function tagText(s) { return statusText.value[s] || s || '' }
function deptSelectData() {
  const conv = (nodes) => (nodes || []).map((n) => ({
    value: n.id, label: n.displayText || n.text,
    children: conv(n.children),
  }))
  return conv(deptTree.value)
}
const deptTreeData = computed(deptSelectData)
async function confirm(text) {
  await ElMessageBox.confirm(text, '提示', { type: 'warning', confirmButtonText: '确定', cancelButtonText: '取消' })
}
function openPrint(id) {
  window.open(`/overtime/print?id=${id}`, '_blank', 'width=1000,height=700,scrollbars=yes')
}

const ctx = {
  dicts, perms, statusText, months, currentMonth, workTypes, personnel, deptTree, deptTreeData,
  tick, bump, openEntry, openBatch, openApplyDrawer, refreshDrawer, openPrint,
  weekLabel, monthLabel, tagClass, tagText, confirm,
  async reloadDicts() { await loadDicts() },
}
provide('ot', ctx)

async function loadDicts() {
  try {
    dicts.value = await api.getOvertimeDicts()
  } catch (e) {
    ElMessage.error('加班模块字典加载失败')
  }
}

onMounted(async () => {
  loading.value = true
  await loadDicts()
  // 权限变化时回退到可见的第一个 Tab
  await nextTick()
  const available = TABS.filter((t) => {
    if (t === 'my') return true
    if (t === 'apply') return perms.value.can_apply
    if (t === 'verify') return perms.value.can_verify
    if (t === 'approvals') return perms.value.is_approver
    if (t === 'summary') return perms.value.can_summary
    if (t === 'config') return perms.value.can_config
    return false
  })
  if (!available.includes(activeTab.value)) activeTab.value = available[0] || 'my'
  syncMounted()
  loading.value = false
})
</script>
