<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createDepartment, deleteDepartment, listDepartments, updateDepartment } from '@/api/dept'
import { buildDeptTree } from '@/utils/dept'

const loading = ref(false)
const flatRows = ref([])
const treeRows = ref([])

async function load() {
  loading.value = true
  try {
    flatRows.value = await listDepartments()
    treeRows.value = buildDeptTree(flatRows.value)
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

// 上级部门下拉选项:显示完整层级路径;编辑时排除自己及所有后代(防环)
const parentOptions = computed(() => {
  const byId = new Map(flatRows.value.map((d) => [d.id, d]))
  const pathLabel = (d) => {
    const names = [d.name]
    let p = d.parent_id ? byId.get(d.parent_id) : null
    while (p) {
      names.unshift(p.name)
      p = p.parent_id ? byId.get(p.parent_id) : null
    }
    return names.join(' / ')
  }
  const excluded = new Set()
  if (editingId.value != null) {
    excluded.add(editingId.value)
    const collectDescendants = (pid) => {
      for (const d of flatRows.value) {
        if (d.parent_id === pid) {
          excluded.add(d.id)
          collectDescendants(d.id)
        }
      }
    }
    collectDescendants(editingId.value)
  }
  return [
    { id: 0, label: '作为顶级部门' },
    ...flatRows.value.filter((d) => !excluded.has(d.id)).map((d) => ({ id: d.id, label: pathLabel(d) })),
  ]
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
        <el-select v-model="form.parent_id" placeholder="选择上级部门" style="width: 100%">
          <el-option v-for="o in parentOptions" :key="o.id" :value="o.id" :label="o.label" />
        </el-select>
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
