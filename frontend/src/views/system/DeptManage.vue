<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createDepartment, deleteDepartment, listDepartments, updateDepartment } from '@/api/dept'
import { buildDeptTree } from '@/utils/dept'

const loading = ref(false)
const treeRows = ref([])

async function load() {
  loading.value = true
  try {
    treeRows.value = buildDeptTree(await listDepartments())
  } finally {
    loading.value = false
  }
}

onMounted(load)

// ===== 新增 / 编辑 =====
const dialog = ref(false)
const editingId = ref(null)
const formRef = ref()
const form = reactive({ name: '', parent_id: 0, remark: '' })
const rules = {
  name: [{ required: true, message: '请输入部门名称', trigger: 'blur' }],
}

// 编辑时上级部门候选要排除自己及自己的子树,否则会形成环
function removeSubtree(nodes, id) {
  return nodes
    .filter((n) => n.id !== id)
    .map((n) => (n.children ? { ...n, children: removeSubtree(n.children, id) } : { ...n }))
}

const parentOptions = computed(() => {
  const tree = editingId.value == null ? treeRows.value : removeSubtree(treeRows.value, editingId.value)
  return [{ id: 0, name: '作为顶级部门', children: tree }]
})

function openCreate() {
  editingId.value = null
  Object.assign(form, { name: '', parent_id: 0, remark: '' })
  dialog.value = true
}

function openEdit(row) {
  editingId.value = row.id
  Object.assign(form, { name: row.name, parent_id: row.parent_id || 0, remark: row.remark })
  dialog.value = true
}

async function submit() {
  await formRef.value.validate()
  if (editingId.value == null) {
    await createDepartment(form)
  } else {
    await updateDepartment(editingId.value, form)
  }
  ElMessage.success('保存成功')
  dialog.value = false
  load()
}

async function remove(row) {
  await ElMessageBox.confirm(`确定删除部门「${row.name}」?`, '提示', { type: 'warning' })
  await deleteDepartment(row.id)
  ElMessage.success('已删除')
  load()
}
</script>

<template>
  <el-card>
    <div class="toolbar">
      <span style="color: #909399">部门为树形结构,支持多级;用户与部门是多对多关系。</span>
      <div class="spacer" />
      <el-button type="primary" @click="openCreate">新增部门</el-button>
    </div>

    <el-table
      v-loading="loading"
      :data="treeRows"
      row-key="id"
      default-expand-all
      :tree-props="{ children: 'children' }"
      stripe
    >
      <el-table-column prop="name" label="部门名称" min-width="280" />
      <el-table-column prop="remark" label="备注" min-width="200" />
      <el-table-column prop="created_at" label="创建时间" width="170" />
      <el-table-column label="操作" width="150" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-button link type="danger" @click="remove(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <!-- 新增 / 编辑 -->
  <el-dialog v-model="dialog" :title="editingId == null ? '新增部门' : '编辑部门'" width="440px">
    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px">
      <el-form-item label="部门名称" prop="name">
        <el-input v-model="form.name" placeholder="如:办公室 / 财务科 / 信息中心" />
      </el-form-item>
      <el-form-item label="上级部门">
        <el-tree-select
          v-model="form.parent_id"
          :data="parentOptions"
          :props="{ label: 'name' }"
          node-key="id"
          default-expand-all
          style="width: 100%"
        />
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
