<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createUser,
  listUsers,
  resetUserPassword,
  setUserRoles,
  setUserStatus,
  updateUser,
} from '@/api/user'
import { listRoles } from '@/api/role'
import { listDepartments } from '@/api/dept'
import { buildDeptTree } from '@/utils/dept'

// ===== 列表 =====
const loading = ref(false)
const keyword = ref('')
const page = ref(1)
const size = ref(10)
const total = ref(0)
const rows = ref([])

async function load() {
  loading.value = true
  try {
    const data = await listUsers({ page: page.value, size: size.value, keyword: keyword.value })
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
  allDepartments.value = await listDepartments()
})

// ===== 新增 / 编辑 =====
const editDialog = ref(false)
const editingId = ref(null)
const editFormRef = ref()
const allDepartments = ref([])
const deptTree = computed(() => buildDeptTree(allDepartments.value))
const editForm = reactive({ username: '', real_name: '', department_ids: [], phone: '' })
const editRules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  real_name: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
}

function openCreate() {
  editingId.value = null
  // 创建时只填姓名/用户名并勾选部门,密码用初始密码,用户首次登录强制修改
  Object.assign(editForm, { username: '', real_name: '', department_ids: [], phone: '' })
  editDialog.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(editForm, {
    username: row.username,
    real_name: row.real_name,
    department_ids: (row.departments || []).map((d) => d.id),
    phone: row.phone,
  })
  editDialog.value = true
}

async function submitEdit() {
  await editFormRef.value.validate()
  if (editingId.value == null) {
    await createUser(editForm)
  } else {
    await updateUser(editingId.value, {
      real_name: editForm.real_name,
      department_ids: editForm.department_ids,
      phone: editForm.phone,
    })
  }
  ElMessage.success(editingId.value == null ? '已创建,初始密码 abc123456' : '保存成功')
  editDialog.value = false
  load()
}

// ===== 启用 / 停用 =====
async function toggleStatus(row) {
  try {
    await setUserStatus(row.id, row.is_active)
    ElMessage.success(row.is_active ? '已启用' : '已停用')
  } catch {
    load()
  }
}

// ===== 重置密码:重置回初始密码 abc123456,用户下次登录强制修改 =====
async function resetPwd(row) {
  try {
    await ElMessageBox.confirm(
      `将把 ${row.username} 的密码重置为初始密码 abc123456,该用户下次登录时须先修改密码。确定重置?`,
      '重置密码',
      { type: 'warning', confirmButtonText: '重置', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  await resetUserPassword(row.id)
  ElMessage.success('已重置为初始密码 abc123456')
  load()
}

// ===== 分配角色 =====
const roleDialog = ref(false)
const roleTarget = ref(null)
const checkedRoleIds = ref([])
const allRoles = ref([])

async function openRoles(row) {
  roleTarget.value = row
  checkedRoleIds.value = row.roles.map((r) => r.id)
  if (!allRoles.value.length) {
    allRoles.value = await listRoles()
  }
  roleDialog.value = true
}

async function submitRoles() {
  await setUserRoles(roleTarget.value.id, checkedRoleIds.value)
  ElMessage.success('已保存')
  roleDialog.value = false
  load()
}
</script>

<template>
  <el-card>
    <div class="toolbar">
      <el-input
        v-model="keyword"
        placeholder="用户名 / 姓名"
        clearable
        style="width: 220px"
        @keyup.enter="search"
        @clear="search"
      />
      <el-button type="primary" @click="search">查询</el-button>
      <div class="spacer" />
      <el-button type="primary" @click="openCreate">新增用户</el-button>
    </div>

    <el-table v-loading="loading" :data="rows" stripe>
      <el-table-column prop="id" label="ID" width="70" />
      <el-table-column prop="username" label="用户名" min-width="120" />
      <el-table-column prop="real_name" label="姓名" min-width="100" />
      <el-table-column label="部门" min-width="150">
        <template #default="{ row }">
          <el-tag v-for="d in row.departments" :key="d.id" size="small" style="margin-right: 4px">
            {{ d.name }}
          </el-tag>
          <span v-if="!(row.departments || []).length" style="color: #c0c4cc">未分配</span>
        </template>
      </el-table-column>
      <el-table-column prop="phone" label="手机号" min-width="130" />
      <el-table-column label="角色" min-width="150">
        <template #default="{ row }">
          <el-tag v-for="r in row.roles" :key="r.id" size="small" style="margin-right: 4px">
            {{ r.name }}
          </el-tag>
          <span v-if="row.is_superuser" style="color: #e6a23c; font-size: 12px">超级管理员</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-switch v-model="row.is_active" @change="toggleStatus(row)" />
        </template>
      </el-table-column>
      <el-table-column prop="last_login_at" label="最后登录" width="170" />
      <el-table-column prop="created_at" label="创建时间" width="170" />
      <el-table-column label="操作" width="220" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="primary" @click="openRoles(row)">分配角色</el-button>
          <el-button link type="warning" @click="resetPwd(row)">重置密码</el-button>
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
  <el-dialog v-model="editDialog" :title="editingId == null ? '新增用户' : '编辑用户'" width="440px">
    <el-form ref="editFormRef" :model="editForm" :rules="editRules" label-width="80px">
      <el-form-item label="用户名" prop="username">
        <el-input v-model="editForm.username" :disabled="editingId != null" placeholder="登录账号,创建后不可修改" />
      </el-form-item>
      <el-form-item label="姓名" prop="real_name">
        <el-input v-model="editForm.real_name" placeholder="登录后显示的姓名" />
      </el-form-item>
      <el-form-item label="部门">
        <el-tree-select
          v-model="editForm.department_ids"
          :data="deptTree"
          :props="{ label: 'name' }"
          node-key="id"
          multiple
          collapse-tags
          collapse-tags-tooltip
          default-expand-all
          placeholder="可多选,需先在「部门管理」中维护"
          style="width: 100%"
        />
      </el-form-item>
      <el-form-item v-if="editingId != null" label="手机号">
        <el-input v-model="editForm.phone" />
      </el-form-item>
      <el-alert
        v-if="editingId == null"
        type="info"
        show-icon
        :closable="false"
        title="创建后使用初始密码 abc123456 登录,首次登录时强制修改为复杂密码"
      />
    </el-form>
    <template #footer>
      <el-button @click="editDialog = false">取消</el-button>
      <el-button type="primary" @click="submitEdit">保存</el-button>
    </template>
  </el-dialog>

  <!-- 分配角色 -->
  <el-dialog v-model="roleDialog" :title="'分配角色 - ' + (roleTarget?.username || '')" width="400px">
    <el-checkbox-group v-model="checkedRoleIds">
      <el-checkbox v-for="r in allRoles" :key="r.id" :value="r.id" :label="r.name" />
    </el-checkbox-group>
    <template #footer>
      <el-button @click="roleDialog = false">取消</el-button>
      <el-button type="primary" @click="submitRoles">保存</el-button>
    </template>
  </el-dialog>
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
</style>
