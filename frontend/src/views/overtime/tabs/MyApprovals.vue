<template>
  <div>
    <div class="table-card">
      <el-table :data="rows" border size="small" v-loading="loading" height="600">
        <el-table-column label="申请单编号" width="170">
          <template #default="{ row }"><span class="grid-link" @click="ot.openApplyDrawer({ id: row.apply_id })">{{ row.apply_no }}</span></template>
        </el-table-column>
        <el-table-column prop="applyUserName" label="制单人" width="100" />
        <el-table-column prop="levelName" label="当前层级" width="150" />
        <el-table-column prop="step_order" label="审批顺序" width="100" align="center" />
        <el-table-column prop="apply_month" label="月份" width="100" align="center" />
        <el-table-column prop="total_hours" label="总时长(h)" width="110" align="center" />
        <el-table-column prop="create_time" label="提交时间" width="160" />
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <span class="grid-action" @click="approve(row, true)">通过</span>
              <span class="grid-action-danger" @click="approve(row, false)">驳回</span>
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
  </div>
</template>

<script setup>
import { inject, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api/overtime'

const ot = inject('ot')
const rows = ref([]), total = ref(0), page = ref(1), size = ref(50), loading = ref(false)

async function load() {
  loading.value = true
  try {
    const r = await api.listMyApprovals({ page: page.value, rows: size.value })
    rows.value = r.rows || []; total.value = r.total || 0
  } finally { loading.value = false }
}
function search() { page.value = 1; load() }
watch(() => ot.tick.value, () => load())
onMounted(load)

async function approve(row, ok) {
  let comment = ''
  try {
    const r = await ElMessageBox.prompt(ok ? '审批意见（可留空）' : '请填写驳回意见', ok ? '通过审批' : '驳回申请', {
      inputType: 'textarea', inputPlaceholder: '请输入意见', confirmButtonText: '确定', cancelButtonText: '取消',
    })
    comment = r.value || ''
  } catch { return }
  const res = ok
    ? await api.approveApply(row.approval_id, true, comment)
    : await api.rejectApply(row.approval_id, comment)
  ElMessage.success(res.msg)
  ot.bump()
  load()
}
</script>
