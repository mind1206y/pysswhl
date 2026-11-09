<template>
  <div>
    <div class="sub-tabs">
      <div class="sub-tab" :class="{ on: panel === 'personnel' }" @click="panel = 'personnel'">人员管理</div>
      <div v-if="ot.perms.value.is_admin" class="sub-tab" :class="{ on: panel === 'approval' }" @click="switchApproval">审批配置</div>
    </div>

    <!-- 人员管理 -->
    <template v-if="panel === 'personnel'">
      <el-card class="filter-card" shadow="never">
        <div class="filter-row">
          <div class="filter-group">
            <label>部门：</label>
            <el-tree-select v-model="f.dept" :data="ot.deptTreeData.value" node-key="value"
                            :props="{ label: 'label', children: 'children' }" check-strictly clearable
                            size="small" style="width: 260px" @change="onChange" />
          </div>
          <div class="filter-group">
            <el-select v-model="f.maxDepth" size="small" style="width: 120px" @change="onChange">
              <el-option label="全部下级" value="" />
              <el-option label="本级" value="0" />
              <el-option v-for="i in 5" :key="i" :label="`本级+${i}`" :value="String(i)" />
            </el-select>
          </div>
          <el-input v-model="f.search" placeholder="搜索姓名/工号" size="small" clearable
                    style="width: 180px" @keyup.enter="search" />
          <el-button size="small" type="primary" @click="search">搜索</el-button>
          <el-button size="small" @click="clearFilter">重置</el-button>
          <el-checkbox v-model="f.showInactive" size="small" @change="search">显示停用人员</el-checkbox>
          <el-button size="small" type="primary" plain @click="openPersonnel()">新增人员</el-button>
          <el-button size="small" @click="$refs.personnelFile.click()">导入Excel</el-button>
          <el-button size="small" v-if="ot.perms.value.is_admin" @click="deptDrawer = true">部门管理</el-button>
          <input ref="personnelFile" type="file" accept=".xlsx,.xls" style="display: none" @change="onPersonnelFile" />
        </div>
      </el-card>
      <div class="table-card">
        <el-table :data="rows" border size="small" v-loading="loading" height="500">
          <el-table-column prop="name" label="姓名" width="110" />
          <el-table-column prop="employee_no" label="工号" width="130" />
          <el-table-column prop="deptName" label="部门" min-width="280" show-overflow-tooltip />
          <el-table-column prop="userName" label="系统用户" width="120" />
          <el-table-column label="日工资基数" width="120" align="right">
            <template #default="{ row }">{{ Number(row.daily_wage || 0).toFixed(2) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="80">
            <template #default="{ row }"><el-tag size="small" :type="row.is_active ? 'success' : 'info'">{{ row.is_active ? '启用' : '停用' }}</el-tag></template>
          </el-table-column>
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <div class="row-actions">
                <span class="grid-link" @click="openPersonnel(row)">编辑</span>
                <span v-if="row.is_active" class="grid-danger" @click="togglePersonnel(row, false)">停用</span>
                <span v-else style="color: #52c41a; cursor: pointer" @click="togglePersonnel(row, true)">启用</span>
              </div>
            </template>
          </el-table-column>
        </el-table>
        <div class="pager">
          <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
                         :page-sizes="[50, 100, 200]" layout="total, sizes, prev, pager, next, jumper"
                         @current-change="load" @size-change="search" />
        </div>
      </div>
    </template>

    <!-- 审批配置 -->
    <template v-else>
      <div style="background: #fffde7; border: 1px solid #f0e68c; padding: 7px 12px; border-radius: 6px; margin-bottom: 8px; display: flex; align-items: center; gap: 12px">
        <b style="color: #b8860b">审批流程</b>
        <el-switch v-model="switchOn" active-text="启用" inactive-text="关闭" @change="toggleSwitch" />
        <span class="hint">{{ switchOn ? '审批流模式：草稿→审批中→已通过→打印→核销' : '核销直通模式：草稿→打印→核销' }}</span>
      </div>
      <div class="table-card" style="margin-bottom: 8px">
        <div class="toolbar" style="padding: 7px 10px; margin: 0">
          <b>审批层级</b><span class="spacer"></span>
          <el-button size="small" type="primary" plain @click="openLevel()">新增层级</el-button>
        </div>
        <el-table :data="levels" border size="small" height="230">
          <el-table-column prop="level_name" label="层级名称" width="160" />
          <el-table-column prop="level_order" label="顺序" width="70" />
          <el-table-column label="路由" width="130">
            <template #default="{ row }">{{ routeText[row.route_type] || row.route_type }}</template>
          </el-table-column>
          <el-table-column label="指定部门" width="150">
            <template #default="{ row }">
              {{ row.dept_offset === -1 ? (row.deptName || '申请人部门')
                : (row.dept_offset === 0 ? '申请人部门' : `上级${row.dept_offset}级`) }}
            </template>
          </el-table-column>
          <el-table-column label="审批模式" width="120">
            <template #default="{ row }">{{ modeText[row.approval_mode] || row.approval_mode }}</template>
          </el-table-column>
          <el-table-column label="启用" width="70">
            <template #default="{ row }">{{ row.is_active ? '是' : '否' }}</template>
          </el-table-column>
          <el-table-column label="操作" width="130" fixed="right">
            <template #default="{ row }">
              <div class="row-actions">
                <span class="grid-link" @click="openLevel(row)">编辑</span>
                <span v-if="row.is_active" class="grid-danger" @click="delLevel(row)">停用</span>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <div class="table-card">
        <div class="toolbar" style="padding: 7px 10px; margin: 0">
          <b>审批人</b><span class="spacer"></span>
          <el-button size="small" type="primary" plain @click="openApprover()">新增审批人</el-button>
        </div>
        <el-table :data="approvers" border size="small" height="230">
          <el-table-column prop="userName" label="用户" width="130" />
          <el-table-column prop="levelName" label="所属层级" width="160" />
          <el-table-column label="加班类别" width="150">
            <template #default="{ row }">{{ row.work_type || '全部' }}</template>
          </el-table-column>
          <el-table-column prop="scopeDeptName" label="管辖部门" min-width="180" />
          <el-table-column label="操作" width="100" fixed="right">
            <template #default="{ row }">
              <div class="row-actions">
                <span class="grid-link" @click="openApprover(row)">编辑</span>
                <span class="grid-danger" @click="delApprover(row)">停用</span>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </template>

    <!-- 人员编辑 -->
    <el-dialog v-model="personnelVisible" :title="pForm.id ? '编辑人员' : '新增人员'" width="560px" class="ot-dialog" append-to-body>
      <el-form label-width="100px" size="small">
        <el-form-item label="姓名" required><el-input v-model="pForm.name" style="width: 280px" /></el-form-item>
        <el-form-item label="工号"><el-input v-model="pForm.employee_no" style="width: 280px" /></el-form-item>
        <el-form-item label="所属部门" required>
          <div style="width: 100%">
            <div style="color: #533afd; font-weight: bold; font-size: 12px; margin-bottom: 4px">{{ deptPathOf(pForm.bb_bumen_id) }}</div>
            <el-tree-select v-model="pForm.bb_bumen_id" :data="ot.deptTreeData.value" node-key="value"
                            :props="{ label: 'label', children: 'children' }" check-strictly
                            style="width: 100%" placeholder="默认选中根部门（本级），可展开选择下级部门" />
          </div>
        </el-form-item>
        <el-form-item label="绑定系统用户">
          <el-select v-model="pForm.bb_user_id" clearable filterable style="width: 280px">
            <el-option label="不绑定" :value="null" />
            <el-option v-for="u in ot.dicts.value.users" :key="u.id" :label="`${u.name} (${u.username})`" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="日工资基数"><el-input-number v-model="pForm.daily_wage" :precision="2" :min="0" style="width: 180px" /></el-form-item>
        <el-form-item label="上级（人事链）">
          <el-select v-model="pForm.parent_id" clearable filterable style="width: 280px">
            <el-option label="无（顶级）" :value="null" />
            <el-option v-for="p in allPersonnel" :key="p.id" :label="p.name" :value="p.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="personnelVisible = false">取消</el-button>
        <el-button type="primary" @click="savePersonnel">保存</el-button>
      </template>
    </el-dialog>

    <!-- 层级编辑 -->
    <el-dialog v-model="levelVisible" :title="lForm.id ? '编辑审批层级' : '新增审批层级'" width="580px" class="ot-dialog" append-to-body>
      <el-form label-width="100px" size="small">
        <el-form-item label="名称" required><el-input v-model="lForm.level_name" /></el-form-item>
        <el-form-item label="顺序">
          <el-select v-model="lForm.level_order" style="width: 150px">
            <el-option v-for="i in 20" :key="i" :label="i" :value="i" />
          </el-select>
        </el-form-item>
        <el-form-item label="路由">
          <el-select v-model="lForm.route_type" style="width: 100%">
            <el-option label="全部（基层+本部）" value="all" />
            <el-option label="基层（沿人事链）" value="field" />
            <el-option label="本部（指定审批人）" value="hq" />
          </el-select>
        </el-form-item>
        <el-form-item label="部门偏移">
          <el-select v-model="lForm.dept_offset" style="width: 100%">
            <el-option label="指定部门" :value="-1" />
            <el-option label="申请人部门" :value="0" />
            <el-option v-for="i in 5" :key="i" :label="`上${i}级部门`" :value="i" />
          </el-select>
        </el-form-item>
        <el-form-item label="指定部门" v-if="lForm.dept_offset === -1">
          <el-select v-model="lForm.mapped_bumen_id" clearable filterable style="width: 100%">
            <el-option v-for="d in sysDepts" :key="d.id" :label="d.text" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="审批模式">
          <el-select v-model="lForm.approval_mode" style="width: 100%">
            <el-option label="单人审批" value="single" />
            <el-option label="任一通过" value="any" />
            <el-option label="全部通过" value="all" />
          </el-select>
        </el-form-item>
        <el-form-item label="启用"><el-checkbox v-model="lForm.is_active" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="levelVisible = false">取消</el-button>
        <el-button type="primary" @click="saveLevel">保存</el-button>
      </template>
    </el-dialog>

    <!-- 审批人编辑 -->
    <el-dialog v-model="approverVisible" :title="aForm.id ? '编辑审批人' : '新增审批人'" width="520px" class="ot-dialog" append-to-body>
      <el-form label-width="100px" size="small">
        <el-form-item label="审批层级" required>
          <el-select v-model="aForm.approval_level_id" style="width: 100%">
            <el-option v-for="l in levels.filter((x) => x.is_active)" :key="l.id" :label="l.level_name" :value="l.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="用户" required>
          <el-select v-model="aForm.bb_user_id" filterable style="width: 100%">
            <el-option v-for="u in ot.dicts.value.users" :key="u.id" :label="`${u.name} (${u.username})`" :value="u.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="管辖部门">
          <el-select v-model="aForm.scope_bumen_id" clearable filterable style="width: 100%">
            <el-option label="全局" :value="null" />
            <el-option v-for="d in sysDepts" :key="d.id" :label="d.text" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="加班类别">
          <el-select v-model="aForm.work_type" clearable style="width: 100%">
            <el-option label="全部类别" value="" />
            <el-option v-for="w in ot.workTypes.value" :key="w" :label="w" :value="w" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="approverVisible = false">取消</el-button>
        <el-button type="primary" @click="saveApprover">保存</el-button>
      </template>
    </el-dialog>

    <!-- 部门管理抽屉 -->
    <el-drawer v-model="deptDrawer" size="450px" class="ot-drawer" title="加班部门管理" destroy-on-close>
      <div class="ad-body">
        <div class="toolbar">
          <el-button size="small" @click="openAddRoot">新增根部门</el-button>
          <el-button size="small" @click="openAddDept">新增子部门</el-button>
          <el-button size="small" @click="renameNode">改名</el-button>
          <el-button size="small" @click="moveNode">移动</el-button>
          <el-button size="small" @click="toggleNode">停用启用</el-button>
        </div>
        <el-tree ref="deptTreeRef" :data="deptTreeNodes" node-key="id" default-expand-all draggable
                 :props="{ label: 'text', children: 'children' }" highlight-current
                 @node-drop="onNodeDrop" @node-click="(d) => (currentDept = d)" />
        <div class="hint" style="margin-top: 10px">拖拽节点可调整同级排序；镜像节点跟随系统部门，不能手动改名/停用。</div>
      </div>
    </el-drawer>

    <el-dialog v-model="deptDlgVisible" :title="deptDlg.title" width="440px" class="ot-dialog" append-to-body>
      <el-form label-width="100px" size="small">
        <el-form-item label="方式" v-if="deptDlg.mode === 'add'">
          <el-radio-group v-model="deptMode">
            <el-radio value="mirror">从系统部门添加</el-radio>
            <el-radio value="free">创建自定义部门</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="系统部门" v-if="deptMode === 'mirror'">
          <el-select v-model="deptDlg.sysId" style="width: 100%">
            <el-option v-for="d in deptDlg.options" :key="d.id" :label="d.text" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="部门名称" v-if="deptDlg.mode === 'free' || deptMode === 'free'">
          <el-input v-model="deptDlg.name" />
        </el-form-item>
        <el-form-item label="目标上级" v-if="deptDlg.mode === 'move'">
          <el-tree-select v-model="deptDlg.target" :data="deptTreeNodes" node-key="id"
                          :props="{ label: 'text', children: 'children' }" check-strictly clearable
                          style="width: 100%" placeholder="留空则作为根部门" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="deptDlgVisible = false">取消</el-button>
        <el-button type="primary" @click="confirmDeptDlg">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { inject, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api/overtime'

const ot = inject('ot')
const panel = ref('personnel')
const f = reactive({ dept: null, maxDepth: '', search: '', showInactive: false })
const rows = ref([]), total = ref(0), page = ref(1), size = ref(50)
const loading = ref(false), suppress = ref(false)
const allPersonnel = ref([])

function params() {
  const p = { page: page.value, rows: size.value, show_inactive: f.showInactive }
  if (f.dept) p.dept_id = f.dept
  if (f.maxDepth !== '') p.max_depth = f.maxDepth
  if (f.search) p.search = f.search
  return p
}
async function load() {
  loading.value = true
  try {
    const r = await api.listPersonnel(params())
    rows.value = r.rows || []; total.value = r.total || 0
  } finally { loading.value = false }
}
function search() { page.value = 1; load() }
function onChange() { if (!suppress.value) search() }
function clearFilter() {
  suppress.value = true
  try { f.dept = null; f.maxDepth = ''; f.search = ''; f.showInactive = false } finally { suppress.value = false }
  search()
}
watch(() => ot.tick.value, () => load())
onMounted(load)

// ---- 人员
const personnelVisible = ref(false)
const blankPersonnel = () => ({ id: 0, name: '', employee_no: '', bb_bumen_id: null,
                                bb_user_id: null, daily_wage: 0, parent_id: null })
const pForm = reactive(blankPersonnel())
function deptPathOf(id) { return ot.dicts.value.dept_paths?.[id] || '' }
async function openPersonnel(row) {
  Object.assign(pForm, blankPersonnel(), row || {})
  if (!pForm.bb_bumen_id) pForm.bb_bumen_id = ot.dicts.value.user?.dept_id || null
  allPersonnel.value = await api.listActivePersonnel()
  personnelVisible.value = true
}
async function savePersonnel() {
  if (!pForm.name.trim()) return ElMessage.warning('请填写姓名')
  if (!pForm.bb_bumen_id) return ElMessage.warning('请选择部门')
  await api.savePersonnel({ ...pForm })
  ElMessage.success('保存成功'); personnelVisible.value = false; load(); ot.reloadDicts()
}
async function togglePersonnel(row, active) {
  await (active ? api.restorePersonnel(row.id) : api.deletePersonnel(row.id))
  ElMessage.success(active ? '已恢复' : '已停用'); load(); ot.reloadDicts()
}
async function onPersonnelFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  const r = await api.importPersonnelExcel(file)
  ElMessage.success(r.Msg)
  e.target.value = ''; load(); ot.reloadDicts()
}

// ---- 审批配置
const switchOn = ref(false)
const levels = ref([]), approvers = ref([]), sysDepts = ref([])
const routeText = { all: '全部', field: '基层人事链', hq: '本部审批人' }
const modeText = { single: '单人', any: '任一通过', all: '全部通过' }
async function switchApproval() {
  panel.value = 'approval'
  const [sw, lv, ap, sd] = await Promise.all([
    api.getApprovalSwitch(), api.listLevels(), api.listApprovers({ rows: 200 }), api.getSysDeptList(),
  ])
  switchOn.value = sw.enabled
  levels.value = lv || []
  approvers.value = (ap.rows || [])
  sysDepts.value = sd || []
}
async function toggleSwitch(v) {
  const r = await api.setApprovalSwitch(v)
  ElMessage.success(r.msg)
  ot.reloadDicts()
}
const levelVisible = ref(false)
const blankLevel = () => ({ id: 0, level_name: '', level_order: 1, route_type: 'all',
                            dept_offset: 0, mapped_bumen_id: null, approval_mode: 'single', is_active: true })
const lForm = reactive(blankLevel())
function openLevel(row) { Object.assign(lForm, blankLevel(), row || {}); levelVisible.value = true }
async function saveLevel() {
  if (!lForm.level_name.trim()) return ElMessage.warning('请填写层级名称')
  await api.saveLevel({ ...lForm })
  ElMessage.success('保存成功'); levelVisible.value = false; await switchApproval()
}
async function delLevel(row) { await api.deleteLevel(row.id); ElMessage.success('已停用'); await switchApproval() }

const approverVisible = ref(false)
const blankApprover = () => ({ id: 0, bb_user_id: null, approval_level_id: null,
                               scope_bumen_id: null, work_type: '' })
const aForm = reactive(blankApprover())
function openApprover(row) { Object.assign(aForm, blankApprover(), row || {}); approverVisible.value = true }
async function saveApprover() {
  if (!aForm.bb_user_id || !aForm.approval_level_id) return ElMessage.warning('请选择用户和层级')
  await api.saveApprover({ ...aForm })
  ElMessage.success('保存成功'); approverVisible.value = false; await switchApproval()
}
async function delApprover(row) { await api.deleteApprover(row.id); ElMessage.success('已停用'); await switchApproval() }

// ---- 部门管理
const deptDrawer = ref(false)
const deptTreeNodes = ref([])
const currentDept = ref(null)
const deptTreeRef = ref(null)
const deptDlgVisible = ref(false)
const deptMode = ref('mirror')
const deptDlg = reactive({ mode: '', title: '', name: '', sysId: null, target: null, options: [] })
async function reloadDeptTree() {
  deptTreeNodes.value = await api.getDeptTree()
  ot.reloadDicts()
}
watch(deptDrawer, (v) => { if (v) reloadDeptTree() })
async function openAddRoot() {
  deptDlg.mode = 'root'; deptDlg.title = '新增根部门'; deptDlg.options = await api.getTopSysDepts()
  deptDlg.sysId = null; deptMode.value = 'mirror'; deptDlgVisible.value = true
}
async function openAddDept() {
  if (!currentDept.value) return ElMessage.warning('请先在树中选择父部门')
  deptDlg.mode = 'add'; deptDlg.title = '新增子部门'
  deptDlg.options = await api.getMirrorChildren(currentDept.value.id)
  deptMode.value = deptDlg.options.length ? 'mirror' : 'free'
  deptDlg.sysId = null; deptDlg.name = ''; deptDlgVisible.value = true
}
async function renameNode() {
  if (!currentDept.value) return ElMessage.warning('请先选择部门')
  const r = await ElMessageBox.prompt('输入新名称', '改名', { inputValue: currentDept.value.text })
  await api.renameDept(currentDept.value.id, r.value)
  ElMessage.success('已改名'); await reloadDeptTree()
}
async function moveNode() {
  if (!currentDept.value) return ElMessage.warning('请先选择部门')
  deptDlg.mode = 'move'; deptDlg.title = '移动部门'; deptDlg.target = null
  deptDlgVisible.value = true
}
async function toggleNode() {
  if (!currentDept.value) return ElMessage.warning('请先选择部门')
  await api.toggleDept(currentDept.value.id)
  ElMessage.success('已更新'); await reloadDeptTree()
}
async function onNodeDrop() {
  const items = []
  const walk = (nodes, parentId) => {
    nodes.forEach((n, i) => { items.push({ id: n.id, sort_order: i }); walk(n.children || [], n.id) })
  }
  walk(deptTreeNodes.value, null)
  await api.sortDept(items)
  ElMessage.success('排序已保存')
}
async function confirmDeptDlg() {
  const id = currentDept.value?.id
  if (deptDlg.mode === 'root') {
    if (!deptDlg.sysId) return ElMessage.warning('请选择系统部门')
    await api.addMirrorRoot(deptDlg.sysId)
  } else if (deptDlg.mode === 'add') {
    if (deptMode.value === 'mirror') {
      if (!deptDlg.sysId) return ElMessage.warning('请选择系统部门')
      await api.addMirrorDept({ sysBumenId: deptDlg.sysId, parentId: id })
    } else {
      if (!deptDlg.name.trim()) return ElMessage.warning('请输入部门名称')
      await api.saveDept({ name: deptDlg.name, parentId: id })
    }
  } else if (deptDlg.mode === 'move') {
    await api.moveDept(id, deptDlg.target || 0)
  }
  ElMessage.success('操作成功')
  deptDlgVisible.value = false
  await reloadDeptTree()
}
</script>
