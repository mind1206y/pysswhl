<script setup>
import { onMounted, reactive, ref } from 'vue'
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

// ===== 权限设置 =====
const permDialog = ref(false)
const permTarget = ref(null)
const checkedPermIds = ref([])

function openPerms(row) {
  permTarget.value = row
  checkedPermIds.value = row.permissions.map((p) => p.id)
  permDialog.value = true
}

async function submitPerms() {
  await setRolePermissions(permTarget.value.id, checkedPermIds.value)
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
      <el-table-column label="权限" min-width="240">
        <template #default="{ row }">
          <el-tag
            v-for="p in row.permissions"
            :key="p.id"
            size="small"
            type="info"
            style="margin-right: 4px"
          >
            {{ p.name }}
          </el-tag>
          <span v-if="!row.permissions.length" style="color: #c0c4cc">未分配</span>
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

  <!-- 权限设置 -->
  <el-dialog v-model="permDialog" :title="'权限设置 - ' + (permTarget?.name || '')" width="420px">
    <el-checkbox-group v-model="checkedPermIds">
      <el-checkbox v-for="p in permissions" :key="p.id" :value="p.id" :label="p.name" />
    </el-checkbox-group>
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
</style>
