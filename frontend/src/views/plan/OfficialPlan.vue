<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  addProgress, copyPlanToTodo, exportOfficial, exportProgress, followPlans,
  getPlanDicts, getProgress, listOfficial, planPhotoUrl, savePlanZbj,
  togglePlanKhbj, unfollowPlans, updatePlanRemark, updatePlanZgy,
} from '@/api/plan'
import { CATEGORIES, isCompleted, money } from './common'

const router = useRouter()
const route = useRoute()
const dicts = reactive({
  years: [], default_year: null, departments: [], hosts: [], zgys: [],
  categories: CATEGORIES, jindu: [], all_jindu: [], perms: { manage: false },
})
const filters = reactive({
  nd: null, lb: '更新改造', mohu: '', zgy_list: [], bmid: null, zb: '',
  px: true, ck: false, ywc: false, GZck: false, ifzbj: false, khbj: false,
})
const rows = ref([])
const total = ref(0)
const page = ref(1)
const size = ref(25)
const loading = ref(false)
const summary = reactive({ allTotalJine: 0, khTotalJine: 0, khCompletedJine: 0, khCompletePct: 0, footer: [] })
const selection = ref([])
const progressMap = reactive({})
const expanded = ref([])

const selectedIds = computed(() => selection.value.map((r) => r.ID))
const selectedRows = computed(() => selection.value)

async function loadDicts() {
  const d = await getPlanDicts()
  Object.assign(dicts, d)
  if (!filters.nd) filters.nd = d.default_year
}

function buildParams(withPage = true) {
  const p = {
    nd: filters.nd, lb: filters.lb, mohu: filters.mohu,
    zgy_list: filters.zgy_list.join(','), bmid: filters.bmid || undefined,
    zb: filters.zb || undefined, px: filters.px, ck: filters.ck,
    ywc: filters.ywc, GZck: filters.GZck, ifzbj: filters.ifzbj, khbj: filters.khbj,
  }
  if (withPage) { p.page = page.value; p.size = size.value }
  return p
}

async function load() {
  loading.value = true
  try {
    const data = await listOfficial(buildParams())
    rows.value = data.rows
    total.value = data.total
    Object.assign(summary, {
      allTotalJine: data.allTotalJine, khTotalJine: data.khTotalJine,
      khCompletedJine: data.khCompletedJine, khCompletePct: data.khCompletePct,
      footer: data.footer,
    })
    expanded.value = []
  } finally {
    loading.value = false
  }
}

function search() { page.value = 1; load() }

function resetFilters() {
  Object.assign(filters, {
    nd: dicts.default_year, lb: '更新改造', mohu: '', zgy_list: [], bmid: null,
    zb: '', px: true, ck: false, ywc: false, GZck: false, ifzbj: false, khbj: false,
  })
  search()
}

function onSelectionChange(val) { selection.value = val }

// 液位胶囊的液位百分比：完成态 100%，其余取 jdztValue（0~100]，无值视为 0
function statusPct(row) {
  if (isCompleted(row)) return 100
  const v = row.jdztValue
  return v != null && v > 0 && v <= 100 ? v : 0
}

async function onExpand(row, expandedRows) {
  const isOpen = expandedRows.some((r) => r.ID === row.ID)
  if (!isOpen) return
  const data = await getProgress(row.ID)
  progressMap[row.ID] = data.rows
}

async function doFollow() {
  if (!selectedIds.value.length) return ElMessage.warning('请选择要关注的计划')
  try {
    await ElMessageBox.confirm('确定要关注选中的计划吗？', '关注计划', { type: 'info' })
  } catch { return }
  const r = await followPlans(selectedIds.value)
  ElMessage.success(`关注成功${r.added ? `（新增 ${r.added} 条）` : ''}`)
  load()
}

async function doUnfollow() {
  if (!selectedIds.value.length) return ElMessage.warning('请先选择拟取消的计划')
  try {
    await ElMessageBox.confirm('取消关注将删除您对该计划的所有进度记录，确定要取消关注吗？', '取消关注', { type: 'warning' })
  } catch { return }
  await unfollowPlans(selectedIds.value)
  ElMessage.success('已取消关注')
  load()
}

async function doCopy() {
  if (!selectedIds.value.length) return ElMessage.warning('请选择要复制的计划')
  try {
    await ElMessageBox.confirm('确定要复制到售水专管员待办计划？', '复制计划', { type: 'info' })
  } catch { return }
  const r = await copyPlanToTodo(selectedIds.value)
  ElMessage.success(`复制成功 ${r.copied} 条（${r.target === 'todo' ? '待办计划' : '营业所发起'}）`)
}

// ===== 添加进度 =====
const progDialog = ref(false)
const progRows = ref([])
const progForm = reactive({
  riqi: new Date().toISOString().slice(0, 10), zhuangtaiid: null,
  miaoshu: '', fukuan: 0, beizhu: '',
})
const progFiles = ref([])

function openProgress() {
  if (!selectedRows.value.length) return ElMessage.warning('请先选择计划')
  progRows.value = selectedRows.value
  Object.assign(progForm, {
    riqi: new Date().toISOString().slice(0, 10), zhuangtaiid: null,
    miaoshu: '', fukuan: 0, beizhu: '',
  })
  progFiles.value = []
  progDialog.value = true
}

function onStatusChange(id) {
  const jd = dicts.jindu.find((j) => j.id === id)
  if (jd && !progForm.miaoshu) progForm.miaoshu = jd.leixing
}

function onFileChange(_file, files) { progFiles.value = files }

const progSaving = ref(false)
async function submitProgress() {
  if (progSaving.value) return  // 防双击重复提交
  progSaving.value = true
  try {
    const targets = progRows.value
    let ok = 0
    for (const row of targets) {
      const form = new FormData()
      form.append('gzid', row.ID)
      form.append('guanzhuid', row.myGuanzhuid || 0)
      form.append('riqi', progForm.riqi || '')
      form.append('zhuangtaiid', progForm.zhuangtaiid || 0)
      form.append('miaoshu', progForm.miaoshu || '')
      form.append('fukuan', progForm.fukuan || 0)
      form.append('beizhu', progForm.beizhu || '')
      for (const f of progFiles.value) {
        if (f.raw) form.append('files', f.raw)
      }
      const r = await addProgress(form)
      if (r.ok) ok += 1
    }
    ElMessage.success(`添加成功 ${ok} 条`)
    progDialog.value = false
    load()
  } finally { progSaving.value = false }
}

// ===== 行内专管员 =====
const zgySaving = ref(false)
async function saveZgy(row) {
  if (zgySaving.value) return  // 防双击重复提交
  if (!dicts.perms.manage) return
  zgySaving.value = true
  try {
    await updatePlanZgy({ id: row.ID, zgy: row.zgy })
    ElMessage.success('专管员已更新')
  } finally { zgySaving.value = false }
}

// ===== 备注 / 考核 / 质保金 =====
const remarkDialog = ref(false)
const remarkRow = ref(null)
const remarkText = ref('')
const remarkSaving = ref(false)

function openRemark(row) {
  remarkRow.value = row
  remarkText.value = row.xmbz || ''
  remarkDialog.value = true
}

async function saveRemark() {
  if (remarkSaving.value) return  // 防双击重复提交
  remarkSaving.value = true
  try {
    await updatePlanRemark({ id: remarkRow.value.ID, remark: remarkText.value })
    ElMessage.success('备注已更新')
    remarkDialog.value = false
    load()
  } finally { remarkSaving.value = false }
}

async function toggleKh(row) {
  const r = await togglePlanKhbj(row.ID)
  row.khbj = r.khbj
  ElMessage.success(r.khbj ? '已标记考核' : '已取消考核')
}

const zbjDialog = ref(false)
const zbjRow = ref(null)
const zbjForm = reactive({ zbj: null, zbjrq: '' })
const zbjSaving = ref(false)

function openZbj(row) {
  zbjRow.value = row
  zbjForm.zbj = row.zbj
  zbjForm.zbjrq = row.zbjrq || ''
  zbjDialog.value = true
}

async function saveZbj() {
  if (zbjSaving.value) return  // 防双击重复提交
  zbjSaving.value = true
  try {
    await savePlanZbj({ id: zbjRow.value.ID, zbj: zbjForm.zbj, zbjrq: zbjForm.zbjrq })
    ElMessage.success('保存成功')
    zbjDialog.value = false
    load()
  } catch (e) {
    // 错误信息已由拦截器提示
  } finally { zbjSaving.value = false }
}

function viewPhoto(pic) {
  if (pic.missing) return ElMessage.warning('历史附件文件未迁移，无法查看')
  window.open(planPhotoUrl(pic.id), '_blank')
}

async function doExport() {
  await exportOfficial(buildParams(false))
  ElMessage.success('已导出计划')
}

async function doExportProgress() {
  await exportProgress({ nd: filters.nd })
  ElMessage.success('已导出年度进度')
}

onMounted(async () => {
  await loadDicts()
  if (route.query.nd) filters.nd = Number(route.query.nd)
  if (route.query.lb) filters.lb = String(route.query.lb)
  load()
})
</script>

<template>
  <div class="plan-page">
    <el-card shadow="never" class="banner">
      <div class="banner-title">
        <span>{{ filters.nd }}年售水事业部{{ filters.lb }}计划表（正式版）</span>
        <span class="banner-stats">
          所有记录合计：{{ money(summary.allTotalJine) }} 万元
          &nbsp;|&nbsp; 考核完成：{{ money(summary.khCompletedJine) }} / {{ money(summary.khTotalJine) }} 万元
          （{{ summary.khCompletePct }}%）
        </span>
      </div>
      <div class="category-row">
        <el-radio-group v-model="filters.lb" @change="search">
          <el-radio-button v-for="c in dicts.categories" :key="c" :label="c">{{ c }}</el-radio-button>
        </el-radio-group>
      </div>
      <el-form inline class="filter-form">
        <el-form-item label="关键字">
          <el-input v-model="filters.mohu" clearable style="width: 200px"
            placeholder="项目/说明/计划号/专管员" @keyup.enter="search" />
        </el-form-item>
        <el-form-item label="专管员">
          <el-select v-model="filters.zgy_list" multiple collapse-tags filterable clearable
            style="width: 180px" placeholder="选择专管员" @change="search">
            <el-option v-for="z in dicts.zgys" :key="z" :label="z" :value="z" />
          </el-select>
        </el-form-item>
        <el-form-item label="部门">
          <el-select v-model="filters.bmid" clearable filterable style="width: 150px"
            placeholder="选择部门" @change="search">
            <el-option v-for="d in dicts.departments" :key="d.id" :label="d.name" :value="d.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="主办">
          <el-select v-model="filters.zb" clearable filterable style="width: 150px"
            placeholder="选择主办单位" @change="search">
            <el-option v-for="h in dicts.hosts" :key="h" :label="h" :value="h" />
          </el-select>
        </el-form-item>
        <el-form-item label="年度">
          <el-select v-model="filters.nd" style="width: 100px" @change="search">
            <el-option v-for="y in dicts.years" :key="y" :label="y" :value="y" />
          </el-select>
        </el-form-item>
        <el-form-item label="未关注">
          <el-switch v-model="filters.GZck" @change="search" />
        </el-form-item>
        <el-form-item label="未完成">
          <el-switch v-model="filters.ck" @change="() => { if (filters.ck) filters.ywc = false; search() }" />
        </el-form-item>
        <el-form-item label="已完成">
          <el-switch v-model="filters.ywc" @change="() => { if (filters.ywc) filters.ck = false; search() }" />
        </el-form-item>
        <el-form-item label="按序号排序">
          <el-switch v-model="filters.px" @change="search" />
        </el-form-item>
        <el-form-item label="查看质保金">
          <el-switch v-model="filters.ifzbj" @change="search" />
        </el-form-item>
        <el-form-item label="仅考核">
          <el-switch v-model="filters.khbj" @change="search" />
        </el-form-item>
        <el-form-item>
          <el-button @click="resetFilters">重置</el-button>
        </el-form-item>
      </el-form>
    </el-card>

    <div class="toolbar">
      <el-button type="primary" @click="doFollow">我要关注</el-button>
      <el-button @click="doUnfollow">取消关注</el-button>
      <el-button @click="doCopy">复制到待办计划申报</el-button>
      <el-button type="success" plain @click="openProgress">添加进度</el-button>
      <el-button @click="doExport">导出计划</el-button>
      <el-button @click="doExportProgress">导出年度全部进度</el-button>
      <el-button @click="router.push('/plan/dashboard')">进度看板</el-button>
      <span class="hint">共 {{ total }} 条 · 展开行查看进度记录 · 双击无编辑</span>
    </div>

    <el-table v-loading="loading" :data="rows" border stripe size="small" row-key="ID"
      height="calc(100vh - 355px)"
      @selection-change="onSelectionChange" @expand-change="onExpand">
      <el-table-column type="selection" width="42" fixed />
      <el-table-column type="expand" width="40">
        <template #default="{ row }">
          <div class="progress-box">
            <el-empty v-if="!(progressMap[row.ID] || []).length" description="暂无进度记录" :image-size="50" />
            <el-table v-else :data="progressMap[row.ID]" size="small" border>
              <el-table-column prop="leixing" label="计划状态" width="150">
                <template #default="{ row: p }">
                  <span>{{ p.leixing || '—' }}</span>
                  <el-progress v-if="p.value >= 10 && p.value <= 100" :percentage="p.value"
                    :stroke-width="4" :show-text="false" class="mini-bar" />
                </template>
              </el-table-column>
              <el-table-column prop="riqi" label="日期" width="105" />
              <el-table-column prop="miaoshu" label="描述" min-width="220" show-overflow-tooltip />
              <el-table-column prop="beizhu" label="备注" min-width="180" show-overflow-tooltip />
              <el-table-column label="已付款(元)" width="100" align="right">
                <template #default="{ row: p }">{{ money(p.fukuan) }}</template>
              </el-table-column>
              <el-table-column prop="caozuotime" label="最后操作时间" width="150" />
              <el-table-column prop="username" label="操作者" width="90" />
              <el-table-column label="图片" width="160">
                <template #default="{ row: p }">
                  <el-tag v-for="pic in p.tps" :key="pic.id" size="small" class="pic-tag"
                    :type="pic.missing ? 'info' : 'primary'" @click="viewPhoto(pic)">
                    {{ pic.missing ? '历史附件(缺失)' : '查看附件' }}
                  </el-tag>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="numb" label="记录数" width="62" align="center" />
      <el-table-column prop="ssusers" label="已关注" width="130" show-overflow-tooltip />
      <el-table-column label="最新状态" width="190">
        <template #default="{ row }">
          <div class="jd-capsule" :title="'进度 ' + statusPct(row) + '%'">
            <span class="jd-pill">{{ row.jdzt || row.jdztDesc || '未开始' }}</span>
            <div class="jd-liquid" :style="{ width: statusPct(row) + '%' }"></div>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="xh" label="计划号" width="75" />
      <el-table-column prop="name" label="项目名称" min-width="240" />
      <el-table-column prop="bz" label="项目说明" min-width="450">
        <template #default="{ row }"><span class="bz-cell">{{ row.bz }}</span></template>
      </el-table-column>
      <el-table-column label="金额(万元)" width="100" align="right">
        <template #default="{ row }">{{ money(row.jine) }}</template>
      </el-table-column>
      <el-table-column label="总付(万元)" width="100" align="right">
        <template #default="{ row }">{{ money(row.zongji) }}</template>
      </el-table-column>
      <el-table-column prop="zb" label="主办单位" width="90" show-overflow-tooltip />
      <el-table-column prop="fzr" label="负责人" width="80" />
      <el-table-column prop="bm" label="所属部门" width="110" show-overflow-tooltip />
      <el-table-column prop="lb" label="类别" width="90" />
      <el-table-column label="专管员" width="110">
        <template #default="{ row }">
          <el-input v-model="row.zgy" size="small" placeholder="点击填写"
            @change="saveZgy(row)" @keyup.enter="$event.target.blur()" />
        </template>
      </el-table-column>
      <el-table-column prop="nd" label="年度" width="70" />
      <el-table-column label="考核" width="62" align="center">
        <template #default="{ row }">
          <el-button link type="success" @click="toggleKh(row)">
            {{ row.khbj ? '✓' : '＋' }}
          </el-button>
        </template>
      </el-table-column>
      <el-table-column label="编辑备注" width="75" align="center">
        <template #default="{ row }">
          <el-button link type="primary" @click="openRemark(row)">备注</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="xmbz" label="项目备注(可填设备编号)" width="180" show-overflow-tooltip />
      <el-table-column label="质保金" width="90" align="right">
        <template #default="{ row }">{{ money(row.zbj) }}</template>
      </el-table-column>
      <el-table-column prop="zbjrq" label="质保金到期" width="100" />
      <el-table-column label="质保金操作" width="90" align="center">
        <template #default="{ row }">
          <el-button link type="success" @click="openZbj(row)">登记</el-button>
        </template>
      </el-table-column>
      <el-table-column prop="zbjdjr" label="登记人" width="80" />
      <el-table-column prop="zbjdjriqi" label="登记日期" width="135" />
    </el-table>

    <div class="pager">
      <el-pagination v-model:current-page="page" v-model:page-size="size" :total="total"
        :page-sizes="[25, 50, 100, 200]" layout="total, sizes, prev, pager, next, jumper"
        @current-change="load" @size-change="search" />
    </div>

    <!-- 添加进度 -->
    <el-dialog v-model="progDialog" title="添加进度记录" width="620px" :close-on-click-modal="false">
      <el-alert type="info" :closable="false" show-icon class="mb10"
        :title="`将为 ${progRows.length} 条计划添加进度记录`" />
      <el-form label-width="90px">
        <el-form-item label="日期">
          <el-date-picker v-model="progForm.riqi" type="date" value-format="YYYY-MM-DD"
            style="width: 100%" />
        </el-form-item>
        <el-form-item label="进度状态">
          <el-select v-model="progForm.zhuangtaiid" clearable style="width: 100%"
            placeholder="选择进度状态（可留空，仅写描述）" @change="onStatusChange">
            <el-option v-for="j in dicts.jindu" :key="j.id" :label="j.leixing" :value="j.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-select v-model="progForm.miaoshu" filterable allow-create clearable
            default-first-option style="width: 100%" placeholder="选择或输入描述">
            <el-option v-for="j in dicts.all_jindu" :key="j.id" :label="j.leixing" :value="j.leixing" />
          </el-select>
        </el-form-item>
        <el-form-item label="付款金额(元)">
          <el-input-number v-model="progForm.fukuan" :min="0" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="progForm.beizhu" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="图片/附件">
          <el-upload multiple :auto-upload="false" :on-change="onFileChange" :limit="9">
            <el-button size="small">选择文件</el-button>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="progDialog = false">取消</el-button>
        <el-button type="primary" @click="submitProgress">提交</el-button>
      </template>
    </el-dialog>

    <!-- 项目备注 -->
    <el-dialog v-model="remarkDialog" title="编辑项目备注" width="480px">
      <el-form label-width="80px">
        <el-form-item label="备注内容">
          <el-input v-model="remarkText" type="textarea" :rows="4" placeholder="请输入备注" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="remarkDialog = false">取消</el-button>
        <el-button type="primary" @click="saveRemark">保存</el-button>
      </template>
    </el-dialog>

    <!-- 质保金 -->
    <el-dialog v-model="zbjDialog" title="登记质保金" width="420px">
      <el-form label-width="90px">
        <el-form-item label="质保金金额">
          <el-input-number v-model="zbjForm.zbj" :precision="2" :min="0" style="width: 100%" />
        </el-form-item>
        <el-form-item label="到期日期">
          <el-date-picker v-model="zbjForm.zbjrq" type="date" value-format="YYYY-MM-DD"
            style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="zbjDialog = false">取消</el-button>
        <el-button type="primary" @click="saveZbj">提交</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.plan-page { display: flex; flex-direction: column; gap: 8px; }
.banner :deep(.el-card__body) { padding: 10px 14px; }
.banner-title { display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px; font-size: 16px; font-weight: 700; color: #1c1e54; margin-bottom: 8px; }
.banner-stats { font-size: 13px; font-weight: 500; color: #385f8a; }
.category-row { margin-bottom: 4px; }
.filter-form :deep(.el-form-item) { margin-bottom: 4px; margin-right: 10px; }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.hint { margin-left: auto; color: #909399; font-size: 12px; }
.pager { display: flex; justify-content: flex-end; }
.bz-cell { display: inline-block; background: rgba(28, 30, 84, 0.06); border: 1px solid rgba(164, 180, 201, 0.35); border-radius: 6px; padding: 2px 6px; text-indent: 1em; line-height: 1.5; white-space: normal; word-break: break-word; }
/* 最新状态：液位胶囊（与 sswhl gxdxljihua 同款）——透明底+1px 细线外圈，
   白色文字胶囊居中，半透明蓝液体叠在其上按进度浸没 */
.jd-capsule {
  position: relative; display: inline-flex; align-items: center;
  width: 164px; height: 26px; padding: 3px;
  border-radius: 999px; background: transparent; border: 1px solid #dcdfe6;
  overflow: hidden; vertical-align: middle;
}
.jd-liquid {
  position: absolute; z-index: 2; top: 0; left: 0; bottom: 0;
  background: linear-gradient(180deg, rgba(102, 177, 255, 0.55), rgba(64, 158, 255, 0.42));
  border-radius: 999px; transition: width 0.3s ease;
  pointer-events: none; box-shadow: inset -1px 0 0 rgba(255, 255, 255, 0.55);
}
.jd-pill {
  position: relative; display: inline-flex; align-items: center; justify-content: center;
  gap: 4px; width: 100%; height: 100%; max-width: 100%;
  padding: 0 10px; border-radius: 999px; background: #fff;
  font-size: 12px; color: #1b1d21; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.mini-bar { margin-top: 2px; }
.progress-box { padding: 8px 16px; background: #fafbfc; }
.pic-tag { margin-right: 4px; cursor: pointer; }
.mb10 { margin-bottom: 10px; }
</style>
