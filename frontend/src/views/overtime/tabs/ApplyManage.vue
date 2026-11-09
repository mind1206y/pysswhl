<template>
  <div>
    <div class="sub-tabs">
      <div class="sub-tab" :class="{ on: panel === 'src' }" @click="switchPanel('src')">待汇总记录</div>
      <div class="sub-tab" :class="{ on: panel === 'apply' }" @click="switchPanel('apply')">申请单列表</div>
    </div>

    <!-- 待汇总记录 -->
    <template v-if="panel === 'src'">
      <el-card class="filter-card" shadow="never">
        <div class="filter-row">
          <div class="filter-group">
            <label>月份：</label>
            <el-select v-model="src.month" size="small" style="width: 110px" @change="onSrcChange">
              <el-option label="全部" value="" />
              <el-option v-for="m in ot.months.value" :key="m" :label="m" :value="m" />
            </el-select>
          </div>
          <div class="filter-group">
            <label>部门：</label>
            <el-tree-select v-model="src.dept" :data="ot.deptTreeData.value" node-key="value"
                            :props="{ label: 'label', children: 'children' }" check-strictly clearable
                            size="small" style="width: 280px" @change="onSrcChange" />
          </div>
          <div class="filter-group">
            <label>类型：</label>
            <el-select v-model="src.workType" size="small" style="width: 130px" @change="onSrcChange">
              <el-option label="全部" value="all" />
              <el-option v-for="w in ot.workTypes.value" :key="w" :label="w" :value="w" />
            </el-select>
          </div>
        </div>
      </el-card>
      <div class="toolbar">
        <el-button size="small" type="primary" @click="searchSrc">搜索</el-button>
        <el-button size="small" @click="clearSrc">重置</el-button>
        <el-button size="small" type="primary" plain @click="openCreateApply">生成申请单</el-button>
        <span class="hint">勾选若干同类型、同部门或同上一级部门的记录，点"生成申请单"创建申请单</span>
      </div>
      <div class="table-card">
        <el-table :data="srcRows" border size="small" v-loading="loading" height="490"
                  @selection-change="(v) => (srcSelected = v)">
          <el-table-column type="selection" width="42" />
          <el-table-column prop="apply_no" label="编号" width="125" />
          <el-table-column prop="applyUserName" label="录入人" width="85" />
          <el-table-column prop="personnelName" label="加班人" width="85" />
          <el-table-column prop="deptName" label="部门" min-width="200" show-overflow-tooltip />
          <el-table-column prop="work_type" label="类型" width="115" />
          <el-table-column prop="settle_type" label="结算" width="70" />
          <el-table-column prop="apply_month" label="月份" width="80" />
          <el-table-column prop="total_hours" label="总时长(h)" width="95" />
          <el-table-column label="原始时长(h)" width="100">
            <template #default="{ row }">{{ Number(row.rawHours || 0).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="加班明细" min-width="260">
            <template #default="{ row }"><span v-html="row.timeSlots || ''"></span></template>
          </el-table-column>
          <el-table-column prop="create_time" label="操作时间" width="140" />
        </el-table>
        <div class="pager">
          <el-pagination v-model:current-page="srcPage" v-model:page-size="srcSize" :total="srcTotal"
                         :page-sizes="[50, 100, 200]" layout="total, sizes, prev, pager, next, jumper"
                         @current-change="loadSrc" @size-change="searchSrc" />
        </div>
      </div>
    </template>

    <!-- 申请单列表 -->
    <template v-else>
      <el-card class="filter-card" shadow="never">
        <div class="filter-row">
          <div class="filter-group">
            <label>月份：</label>
            <el-select v-model="f.month" size="small" style="width: 110px" @change="onApplyChange">
              <el-option v-for="m in ot.months.value" :key="m" :label="m" :value="m" />
            </el-select>
          </div>
          <div class="filter-group">
            <label>部门：</label>
            <el-tree-select v-model="f.dept" :data="ot.deptTreeData.value" node-key="value"
                            :props="{ label: 'label', children: 'children' }" check-strictly clearable
                            size="small" style="width: 280px" @change="onApplyChange" />
          </div>
          <div class="filter-group">
            <label>状态：</label>
            <el-select v-model="f.status" size="small" style="width: 115px" @change="onApplyChange">
              <el-option label="全部" value="all" />
              <el-option v-for="(t, k) in applyStatus" :key="k" :label="t" :value="k" />
            </el-select>
          </div>
          <div class="filter-group">
            <label>类型：</label>
            <el-select v-model="f.workType" size="small" style="width: 140px" @change="onApplyChange">
              <el-option label="全部" value="all" />
              <el-option v-for="w in ot.workTypes.value" :key="w" :label="w" :value="w" />
            </el-select>
          </div>
        </div>
      </el-card>
      <div class="toolbar">
        <el-button size="small" type="primary" @click="searchApply">搜索</el-button>
        <el-button size="small" @click="clearApply">重置</el-button>
        <el-button size="small" type="primary" plain @click="newApplyVisible = true">新建申请单</el-button>
      </div>
      <div class="table-card">
        <el-table :data="rows" border size="small" v-loading="loading" height="490"
                  @row-click="(r) => ot.openApplyDrawer(r)">
          <el-table-column prop="apply_no" label="编号" width="125" fixed="left" />
          <el-table-column prop="apply_month" label="月份" width="76" align="center" />
          <el-table-column prop="work_type" label="加班类型" width="118" />
          <el-table-column prop="settle_type" label="结算" width="68" />
          <el-table-column prop="applyUserName" label="制单人" width="88" />
          <el-table-column prop="deptName" label="部门" min-width="200" show-overflow-tooltip />
          <el-table-column label="总时长(h)" width="95" align="center">
            <template #default="{ row }">{{ Number(row.total_hours || 0).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="金额(元)" width="100" align="right">
            <template #default="{ row }">{{ row.settle_type === '补休' ? '—' : Math.round(row.total_amount || 0) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="84" align="center">
            <template #default="{ row }"><span :class="ot.tagClass(row.status)">{{ ot.tagText(row.status) }}</span></template>
          </el-table-column>
          <el-table-column label="操作" width="200" fixed="right">
            <template #default="{ row }">
              <div class="row-actions" @click.stop>
                <span v-if="row.status === 'draft'" class="grid-danger" @click="removeApply(row)">删除</span>
                <span v-if="row.status === 'draft' || row.status === 'printed'" class="grid-link" @click="exportOne(row)">导出</span>
                <template v-if="ot.dicts.value.approval_enabled">
                  <span v-if="row.status === 'draft'" class="grid-action" @click="submitApproval(row)">提交审批</span>
                  <span v-else-if="row.status === 'approved' || row.status === 'printed'" class="grid-link" style="font-weight: bold" @click="printApply(row)">打印</span>
                </template>
                <template v-else>
                  <span v-if="row.status === 'draft' || row.status === 'printed'" class="grid-link" style="font-weight: bold" @click="printApply(row)">打印</span>
                </template>
                <span v-if="row.status === 'rejected'" class="grid-link" @click="resubmit(row)">重新提交</span>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="apply_date" label="申请日期" width="105" />
          <el-table-column prop="remark" label="备注" width="150" show-overflow-tooltip />
          <el-table-column prop="create_time" label="操作时间" width="140" />
        </el-table>
        <div class="pager">
          <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
                         :page-sizes="[50, 100, 200]" layout="total, sizes, prev, pager, next, jumper"
                         @current-change="loadApply" @size-change="searchApply" />
        </div>
      </div>
    </template>

    <!-- 新建 / 生成申请单 -->
    <el-dialog v-model="newApplyVisible" title="新建申请单" width="460px" class="ot-dialog" append-to-body>
      <el-form label-width="90px" size="small">
        <el-form-item label="月份" required>
          <el-select v-model="newApply.apply_month" style="width: 220px">
            <el-option v-for="m in ot.months.value" :key="m" :label="m" :value="m" />
          </el-select>
        </el-form-item>
        <el-form-item label="加班类型" required>
          <el-select v-model="newApply.work_type" style="width: 220px">
            <el-option v-for="w in ot.workTypes.value" :key="w" :label="w" :value="w" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="newApply.remark" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="newApplyVisible = false">取消</el-button>
        <el-button type="primary" @click="doNewApply">创建</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="createVisible" title="生成申请单" width="460px" class="ot-dialog" append-to-body>
      <div class="hint" style="margin-bottom: 8px">已选 {{ srcSelected.length }} 条个人记录</div>
      <el-form label-width="90px" size="small">
        <el-form-item label="月份" required>
          <el-select v-model="createForm.apply_month" style="width: 220px">
            <el-option v-for="m in ot.months.value" :key="m" :label="m" :value="m" />
          </el-select>
        </el-form-item>
        <el-form-item label="加班类型" required>
          <el-select v-model="createForm.work_type" style="width: 220px">
            <el-option v-for="w in ot.workTypes.value" :key="w" :label="w" :value="w" />
          </el-select>
        </el-form-item>
        <el-form-item label="备注"><el-input v-model="createForm.remark" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="doCreateApply">确定生成</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { inject, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as api from '@/api/overtime'

const ot = inject('ot')
const applyStatus = {
  draft: '草稿', printed: '已打印', verified: '已核销',
  pending: '审批中', approved: '已通过', rejected: '已驳回',
}
const panel = ref('src')
const loading = ref(false)
const suppress = ref(false)

// 待汇总
const src = reactive({ month: '', dept: null, workType: 'all' })
const srcRows = ref([]), srcTotal = ref(0), srcPage = ref(1), srcSize = ref(50)
const srcSelected = ref([])
function srcParams() {
  const p = { page: srcPage.value, rows: srcSize.value, work_type: src.workType }
  if (src.month) p.month = src.month
  if (src.dept) p.dept_id = src.dept
  return p
}
async function loadSrc() {
  loading.value = true
  try {
    const r = await api.listSubmittedRecords(srcParams())
    srcRows.value = r.rows || []; srcTotal.value = r.total || 0
  } finally { loading.value = false }
}
function searchSrc() { srcPage.value = 1; loadSrc() }
function onSrcChange() { if (!suppress.value) searchSrc() }
function clearSrc() {
  suppress.value = true
  try { src.month = ''; src.dept = null; src.workType = 'all' } finally { suppress.value = false }
  searchSrc()
}

// 申请单列表
const f = reactive({ month: '', dept: null, status: 'all', workType: 'all' })
const rows = ref([]), total = ref(0), page = ref(1), size = ref(50)
function applyParams() {
  const p = { page: page.value, rows: size.value, status: f.status, work_type: f.workType }
  if (f.month) p.month = f.month
  if (f.dept) p.dept_id = f.dept
  return p
}
async function loadApply() {
  loading.value = true
  try {
    const r = await api.listApplies(applyParams())
    rows.value = r.rows || []; total.value = r.total || 0
  } finally { loading.value = false }
}
function searchApply() { page.value = 1; loadApply() }
function onApplyChange() { if (!suppress.value) searchApply() }
function clearApply() {
  // 旧系统:重置不改月份,保持用户当前选择避免数据集突变
  suppress.value = true
  try { f.dept = null; f.status = 'all'; f.workType = 'all' } finally { suppress.value = false }
  searchApply()
}
function switchPanel(p) { panel.value = p; p === 'src' ? loadSrc() : loadApply() }

watch(() => ot.currentMonth.value, (m) => { if (!f.month) f.month = m }, { immediate: true })
watch(() => ot.tick.value, () => { panel.value === 'src' ? loadSrc() : loadApply() })
onMounted(loadSrc)

async function removeApply(row) {
  await ot.confirm(`确定删除申请单 ${row.apply_no} 吗？`)
  await api.deleteApply(row.id); ElMessage.success('删除成功'); ot.bump(); loadApply()
}
async function exportOne(row) { await api.exportApply(row.id); ElMessage.success('已导出 Excel') }
async function submitApproval(row) {
  const r = await api.submitForApproval(row.id)
  ElMessage.success(r.msg); ot.bump(); loadApply()
}
async function resubmit(row) {
  await api.resubmitApply(row.id); ElMessage.success('已重新提交为草稿'); loadApply()
}
function printApply(row) { ot.openPrint(row.id) }

const newApplyVisible = ref(false)
const newApply = reactive({ apply_month: '', work_type: '', remark: '' })
watch(() => ot.currentMonth.value, (m) => { if (!newApply.apply_month) newApply.apply_month = m }, { immediate: true })
async function doNewApply() {
  if (!newApply.apply_month || !newApply.work_type) return ElMessage.warning('请选择月份和加班类型')
  const r = await api.saveApplyHeader({
    id: 0, apply_month: newApply.apply_month, work_type: newApply.work_type,
    apply_date: new Date().toISOString().slice(0, 10), remark: newApply.remark,
  })
  ElMessage.success('申请单已创建，点击申请单行可在抽屉中添加人员记录')
  newApplyVisible.value = false
  switchPanel('apply')
  ot.bump()
}

const createVisible = ref(false)
const createForm = reactive({ apply_month: '', work_type: '', remark: '' })
function openCreateApply() {
  if (!srcSelected.value.length) return ElMessage.warning('请至少选择一条个人加班记录')
  createForm.apply_month = ot.currentMonth.value
  createForm.work_type = srcSelected.value[0].work_type || ''
  createForm.remark = ''
  createVisible.value = true
}
async function doCreateApply() {
  const r = await api.createApplyFromPersonal({
    personalRecordIds: srcSelected.value.map((x) => x.id),
    apply: { id: 0, record_type: 'apply', apply_month: createForm.apply_month,
             work_type: createForm.work_type, apply_date: new Date().toISOString().slice(0, 10),
             remark: createForm.remark },
  })
  ElMessage.success(r.msg)
  createVisible.value = false
  f.month = createForm.apply_month
  switchPanel('apply')
  ot.bump()
}
</script>
