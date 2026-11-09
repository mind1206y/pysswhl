<script setup>
import { nextTick, onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createRole,
  deleteRole,
  listPermissions,
  listRoles,
  setRolePermissions,
  updateRole,
} from '@/api/role'

const loading = ref(false)
const rows = ref([])
const permissions = ref([])

async function load() {
  loading.value = true
  try {
    rows.value = await listRoles()
  } finally {
    loading.value = false
  }
}

onMounted(async () => {
  load()
  permissions.value = await listPermissions()
})

// ===== 新增 / 编辑 =====
const dialog = ref(false)
const editingId = ref(null)
const formRef = ref()
const form = reactive({ name: '', code: '', remark: '' })
const rules = {
  name: [{ required: true, message: '请输入角色名称', trigger: 'blur' }],
  code: [{ required: true, message: '请输入角色编码', trigger: 'blur' }],
}

function openCreate() {
  editingId.value = null
  Object.assign(form, { name: '', code: '', remark: '' })
  dialog.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, { name: row.name, code: row.code, remark: row.remark })
  dialog.value = true
}

async function submit() {
  await formRef.value.validate()
  if (editingId.value == null) {
    await createRole(form)
  } else {
    await updateRole(editingId.value, form)
  }
  ElMessage.success('保存成功')
  dialog.value = false
  load()
}

async function remove(row) {
  await ElMessageBox.confirm(`确定删除角色「${row.name}」?`, '提示', { type: 'warning' })
  await deleteRole(row.id)
  ElMessage.success('已删除')
  load()
}

// ===== 权限设置(按分类分组的树形勾选,支撑百级模块规模) =====
const permDialog = ref(false)
const permTarget = ref(null)
const permTreeRef = ref()
const permTree = ref([])
const permKeyword = ref('')
const permExpandAll = ref(false)
const permCheckedCount = ref(0)

// 把平铺权限按 category 组装成两级树;组节点用字符串 id,提交时按类型过滤掉
function buildPermTree(perms) {
  const groups = new Map()
  for (const p of perms) {
    const cat = p.category || '未分类'
    if (!groups.has(cat)) groups.set(cat, [])
    groups.get(cat).push(p)
  }
  let i = 0
  return [...groups.entries()].map(([cat, items]) => ({
    id: `__cat_${i++}`,
    label: `${cat} (${items.length})`,
    children: items.map((p) => ({ id: p.id, label: p.name, code: p.code })),
  }))
}

function openPerms(row) {
  permTarget.value = row
  permKeyword.value = ''
  permExpandAll.value = false
  permTree.value = buildPermTree(permissions.value)
  permDialog.value = true
  nextTick(() => {
    permTreeRef.value.setCheckedKeys(row.permissions.map((p) => p.id))
    updateCheckedCount()
  })
}

function realCheckedKeys() {
  return permTreeRef.value.getCheckedKeys().filter((k) => typeof k === 'number')
}

function updateCheckedCount() {
  permCheckedCount.value = realCheckedKeys().length
}

// 展开/折叠通过换 key 强制重渲染(恢复已勾选状态)
function toggleExpand() {
  const checked = realCheckedKeys()
  permExpandAll.value = !permExpandAll.value
  nextTick(() => {
    permTreeRef.value.setCheckedKeys(checked)
    updateCheckedCount()
  })
}

function clearPerms() {
  permTreeRef.value.setCheckedKeys([])
  updateCheckedCount()
}

watch(permKeyword, (kw) => permTreeRef.value?.filter(kw))

function filterNode(value, data) {
  if (!value) return true
  const kw = value.toLowerCase()
  return (
    (data.label || '').toLowerCase().includes(kw) ||
    (data.code || '').toLowerCase().includes(kw)
  )
}

async function submitPerms() {
  await setRolePermissions(permTarget.value.id, realCheckedKeys())
  ElMessage.success('已保存')
  permDialog.value = false
  load()
}
</script>

<template>
  <el-card>
    <div class="toolbar">
      <span style="color: #909399">角色决定用户能访问哪些功能,给角色勾选权限后,把角色分配给用户。</span>
      <div class="spacer" />
      <el-button type="primary" @click="openCreate">新增角色</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="name" label="角色名称" min-width="140" />
      <el-table-column prop="code" label="角色编码" min-width="120" />
      <el-table-column label="权限" min-width="280">
        <template #default="{ row }">
          <template v-if="row.permissions.length">
            <el-tag
              v-for="p in row.permissions.slice(0, 6)"
              :key="p.id"
              size="small"
              type="info"
              style="margin-right: 4px"
            >
              {{ p.name }}
            </el-tag>
            <el-tag v-if="row.permissions.length > 6" size="small" type="warning">
              +{{ row.permissions.length - 6 }}
            </el-tag>
          </template>
          <span v-else style="color: #c0c4cc">未分配</span>
        </template>
      </el-table-column>
      <el-table-column prop="remark" label="备注" min-width="160" />
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="primary" @click="openPerms(row)">权限设置</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <!-- 新增 / 编辑 -->
  <el-dialog v-model="dialog" :title="editingId == null ? '新增角色' : '编辑角色'" width="440px">
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="角色名称" prop="name">
        <el-input v-model="form.name" />
      </el-form-item>
      <el-form-item label="角色编码" prop="code">
        <el-input v-model="form.code" placeholder="如 admin、checker" />
      </el-form-item>
      <el-form-item label="备注">
        <el-input v-model="form.remark" type="textarea" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="dialog = false">取消</el-button>
      <el-button type="primary" @click="submit">保存</el-button>
    </template>
  </el-dialog>

  <!-- 权限设置:按分类分组 + 搜索 + 全选/清空 -->
  <el-dialog v-model="permDialog" :title="'权限设置 - ' + (permTarget?.name || '')" width="680px">
    <div class="perm-toolbar">
      <el-input
        v-model="permKeyword"
        placeholder="搜索权限名称或编码"
        clearable
        style="width: 220px"
      />
      <el-button link type="primary" @click="toggleExpand">
        {{ permExpandAll ? '全部折叠' : '全部展开' }}
      </el-button>
      <el-button link type="danger" @click="clearPerms">清空</el-button>
      <span class="perm-count">已选 {{ permCheckedCount }} 项</span>
    </div>
    <div class="perm-tree-wrap">
      <el-tree
        ref="permTreeRef"
        :key="permExpandAll ? 'expanded' : 'collapsed'"
        :data="permTree"
        show-checkbox
        node-key="id"
        :default-expand-all="permExpandAll"
        :filter-node-method="filterNode"
        @check="updateCheckedCount"
      >
        <template #default="{ data }">
          <span class="perm-node">
            {{ data.label }}
            <span v-if="data.code" class="perm-code">{{ data.code }}</span>
          </span>
        </template>
      </el-tree>
    </div>
    <template #footer>
      <el-button @click="permDialog = false">取消</el-button>
      <el-button type="primary" @click="submitPerms">保存</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  margin-bottom: 14px;
}
.spacer {
  flex: 1;
}
.perm-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}
.perm-count {
  margin-left: auto;
  color: #909399;
  font-size: 13px;
}
.perm-tree-wrap {
  max-height: 55vh;
  overflow: auto;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 8px 4px;
}
.perm-node {
  font-size: 14px;
}
.perm-code {
  margin-left: 8px;
  color: #c0c4cc;
  font-size: 12px;
  font-family: Consolas, monospace;
}
</style>
