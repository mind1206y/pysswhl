<template>
  <el-dialog :model-value="modelValue" @update:model-value="close" title="加班明细录入"
             width="700px" top="4vh" class="ot-dialog" :close-on-click-modal="false"
             append-to-body destroy-on-close>
    <div class="entry-form-wrap">
      <el-form :disabled="readonly" size="small" @submit.prevent>
        <div class="form-row"><label class="form-label">结算方式：</label><div class="form-value">
          <el-select v-model="form.settleType" style="width: 150px" @change="onSettleChange">
            <el-option label="加班费" value="加班费" />
            <el-option label="补休" value="补休" :disabled="!canComp" />
          </el-select>
          <span class="e-tip">{{ settleTip }}</span>
        </div></div>
        <div class="form-row"><label class="form-label required">加班类别：</label><div class="form-value">
          <el-select v-model="form.workType" style="width: 250px" filterable @change="onWorkTypeChange">
            <el-option v-for="w in ot.workTypes.value" :key="w" :label="w" :value="w" />
          </el-select>
          <el-checkbox v-model="form.isFullDay" :disabled="!canFullDay" style="margin-left: 10px; white-space: nowrap"
                       @change="onFullDayChange">设为全天8小时加班</el-checkbox>
        </div></div>
        <div class="form-row"><label class="form-label required">所属月份：</label><div class="form-value">
          <el-select v-model="form.applyMonth" style="width: 160px">
            <el-option v-for="m in ot.months.value" :key="m" :label="m" :value="m" />
          </el-select>
        </div></div>
        <div class="form-row"><label class="form-label required">姓名：</label><div class="form-value">
          <el-select v-model="form.personnelId" filterable :disabled="personLocked"
                     style="width: 250px" @change="onPersonChange">
            <el-option v-for="p in personOptions" :key="p.id" :label="`${p.name} (${p.employee_no || '无工号'})`" :value="p.id" />
          </el-select>
        </div></div>

        <div class="form-sep"></div>
        <div class="form-row"><label class="form-label required">日期：</label><div class="form-value">
          <el-date-picker v-model="form.workDate" type="date" value-format="YYYY-MM-DD"
                          style="width: 150px" @change="onDateChange" />
          <span class="weekday-chip">{{ ot.weekLabel(form.workDate) }}</span>
        </div></div>
        <div class="form-row" v-if="showShift"><label class="form-label">班次：</label><div class="form-value">
          <el-select v-model="form.shiftType" style="width: 110px" clearable @change="onShiftChange"
                     :disabled="form.isFullDay">
            <el-option v-if="!form.isFullDay" label="不指定" value="" />
            <el-option label="白班" value="白班" />
            <el-option label="晚班" value="晚班" />
          </el-select>
          <template v-if="isExclusive">
            <span style="margin-left: 8px; font-size: 13px; white-space: nowrap">{{ form.shiftType === '晚班' ? '开始：' : '结束：' }}</span>
            <el-select v-model="form.fullDayEnd" style="width: 88px">
              <el-option label="18:00" value="18:00" />
              <el-option label="17:30" value="17:30" />
            </el-select>
            <span class="e-tip" v-if="form.shiftType === '晚班'">次日08:30结束</span>
          </template>
          <span class="e-tip">
            {{ form.isFullDay ? '全天固定8h，须指定班次' : '不指定则按自定义时间录入，不独占当日' }}
          </span>
        </div></div>
        <div class="form-row" v-if="!isExclusive"><label class="form-label required">开始时间：</label><div class="form-value">
          <el-input v-model="form.startQx" style="width: 110px" maxlength="4" placeholder="如 0830"
                    @input="calc" @blur="formatTime('startQx')" />
          <span class="e-tip">输入4位数字如0830→08:30</span>
        </div></div>
        <div class="form-row" v-if="!isExclusive"><label class="form-label required">结束时间：</label><div class="form-value">
          <el-input v-model="form.endQx" style="width: 110px" maxlength="4" placeholder="如 1730"
                    @input="calc" @blur="formatTime('endQx')" />
          <span class="e-tip">小于开始时间则为次日</span>
        </div></div>
        <div class="form-row" v-if="isWx"><label class="form-label required">工单号：</label><div class="form-value">
          <el-input v-model="form.workOrderNo" style="width: 250px" @blur="loadGongdan" />
        </div></div>
        <div class="form-row" v-if="isWx"><label class="form-label required">地址：</label><div class="form-value">
          <el-input v-model="form.address" />
        </div></div>

        <div class="form-sep"></div>
        <div class="form-row"><label class="form-label">工作内容：</label><div class="form-value">
          <div style="display: flex; align-items: center; width: 100%; gap: 6px">
            <el-input v-model="form.reason" placeholder="输入工作内容，或点历史标签填入" />
            <el-button size="small" @click="historyVisible = !historyVisible">▾</el-button>
          </div>
          <div v-if="historyVisible" style="flex-basis: 100%">
            <el-tag v-for="(h, i) in reasonHistory" :key="h" closable size="small" round
                    style="margin: 0 6px 5px 0; cursor: pointer" @click="form.reason = h"
                    @close="removeHistory(i)">{{ h }}</el-tag>
            <span class="e-tip" v-if="!reasonHistory.length">暂无历史记录</span>
          </div>
        </div></div>

        <div class="form-sep"></div>
        <div class="form-row" v-if="!isComp"><label class="form-label">倍数：</label><div class="form-value">
          <el-input-number v-model="form.multiplier" :precision="1" :min="0.5" :step="0.5" style="width: 110px" @change="mulTouched = true" />
          <span v-for="m in [1, 1.5, 2, 3]" :key="m" class="mul-tag"
                :class="{ active: form.multiplier === m }" @click="setMul(m)">{{ m.toFixed(1) }}</span>
          <span class="e-tip" v-if="isHoliday">法定节假日只能 2 或 3</span>
        </div></div>
        <div class="form-row"><label class="form-label">工资单价：</label><div class="form-value">
          <el-input-number v-model="form.dailyWage" :precision="2" :min="0" style="width: 140px" />
          <span class="e-unit">元/天</span>
          <span class="e-tip">特水开关阀门缺省 130；填 0 用人员配置</span>
        </div></div>

        <div class="e-sumbox">
          <div class="form-row"><label class="form-label">{{ isComp ? '补休时长：' : '时长(h)：' }}</label><div class="form-value">
            <span class="e-result">{{ rawHours.toFixed(2) }}</span>
            <span class="e-tip" v-if="isExclusive && !isComp">全天/班次固定 8 小时</span>
          </div></div>
          <div class="form-row" v-if="!isComp"><label class="form-label">加班时长：</label><div class="form-value">
            <span class="e-result">{{ totalHours.toFixed(2) }}</span><span class="e-unit">小时</span>
          </div></div>
          <div class="form-row"><label class="form-label">加班金额：</label><div class="form-value">
            <span class="e-result-lg">{{ displayAmount }}</span><span class="e-unit">元</span>
            <span class="e-tip" v-if="isComp">1:1 补助调休，无加班费</span>
          </div></div>
        </div>
      </el-form>

      <div v-if="showSubGrid" style="margin-top: 8px">
        <div style="border-top: 1px dashed #e3e8ee; padding-top: 8px; margin-bottom: 6px; font-weight: bold; font-size: 13px; color: #0d253d">已录时段</div>
        <el-table :data="subEntries" border size="small" max-height="180">
          <el-table-column prop="work_date" label="日期" width="110" />
          <el-table-column label="时段" width="140">
            <template #default="{ row }">{{ (row.start_time || '').slice(11, 16) }}-{{ (row.end_time || '').slice(11, 16) }}</template>
          </el-table-column>
          <el-table-column prop="total_hours" label="折算时长" width="90" />
          <el-table-column prop="multiplier" label="倍数" width="70" />
          <el-table-column label="操作" width="110">
            <template #default="{ row }">
              <span class="grid-link" @click="editSub(row)">编辑</span>
              <span class="grid-danger" style="margin-left: 8px" @click="deleteSub(row)">删除</span>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>

    <template #footer>
      <div style="display: flex; justify-content: center; gap: 10px; align-items: center">
        <el-button v-if="!readonly" type="primary" plain @click="save(false)" :loading="saving">保存并继续</el-button>
        <el-checkbox v-if="!readonly" v-model="keepName">保持姓名</el-checkbox>
        <el-button v-if="!readonly" type="primary" @click="save(true)" :loading="saving">保存并关闭</el-button>
        <el-button @click="close(false)">取消</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, inject, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import * as api from '@/api/overtime'

const props = defineProps({ modelValue: Boolean, options: { type: Object, default: () => ({}) } })
const emit = defineEmits(['update:modelValue', 'saved'])
const ot = inject('ot')

const readonly = ref(false)
const saving = ref(false)
const keepName = ref(false)
const mulTouched = ref(false)
const historyVisible = ref(false)
const reasonHistory = ref(JSON.parse(localStorage.getItem('sswhl-overtime-reason-history') || '[]'))
const subEntries = ref([])
const personOptions = computed(() => ot.personnel.value)

const blank = () => ({
  settleType: '加班费', workType: '', applyMonth: ot.currentMonth.value,
  personnelId: null, workDate: new Date().toISOString().slice(0, 10),
  isFullDay: false, shiftType: '', fullDayEnd: '18:00',
  startQx: '', endQx: '', workOrderNo: '', address: '', reason: '',
  multiplier: 1.5, dailyWage: 0, entryId: 0,
})
const form = reactive(blank())

const isHoliday = computed(() => form.workType === '法定节假日加班费')
const isTs = computed(() => form.workType === '特水开关阀门')
const isWx = computed(() => form.workType === '维抢修加班')
const isGw = computed(() => form.workType === '管网周末加班')
const isComp = computed(() => form.settleType === '补休')
const canComp = computed(() => !!ot.dicts.value.comp_leave_work_types?.includes(form.workType) || !form.workType)
const canFullDay = computed(() => !['法定节假日加班费', '应急响应值班', '管网周末加班', '特水开关阀门', '维抢修加班'].includes(form.workType) && !!form.workType)
const isExclusiveType = computed(() => !!ot.dicts.value.exclusive_work_types?.includes(form.workType))
const showShift = computed(() => isExclusiveType.value || form.isFullDay)
const isExclusive = computed(() => form.isFullDay || !!form.shiftType)
const showSubGrid = computed(() => !readonly.value && props.options.mode === 'personal' && !!props.options.detailId)
const personLocked = computed(() => props.options.mode === 'personal' && !ot.perms.value.is_admin && !!ot.dicts.value.my_personnel)
const settleTip = computed(() => isComp.value ? '1:1 补助调休，无加班费' : '按日工资和倍数计算加班费')

function defaultFullDayEnd(d) {
  if (!d) return '17:30'
  const dt = new Date(d.replace(/-/g, '/'))
  const m = dt.getMonth() + 1, day = dt.getDate()
  return ((m === 6 && day >= 1) || m === 7 || m === 8 || (m === 9 && day <= 30)) ? '18:00' : '17:30'
}
function toMin(s) {
  const v = String(s || '').replace(/\D/g, '')
  if (v.length < 4) return null
  return Number(v.slice(0, 2)) * 60 + Number(v.slice(2, 4))
}
const rawHours = computed(() => {
  if (isExclusive.value) return 8
  const a = toMin(form.startQx), b = toMin(form.endQx)
  if (a === null || b === null) return 0
  let diff = b - a
  if (diff <= 0) diff += 24 * 60
  return diff / 60
})
const totalHours = computed(() => rawHours.value * (isComp.value ? 1 : (Number(form.multiplier) || 0)))
const displayAmount = computed(() => {
  const wage = Number(form.dailyWage) || 0
  const mul = Number(form.multiplier) || 0
  if (isComp.value) return 0
  if (isExclusive.value || isTs.value) return Math.round(wage * mul)
  return Math.round(wage / 8 * rawHours.value * mul)
})

function setMul(v) { form.multiplier = v; mulTouched.value = true; calc() }
function calc() { /* computed 自动派生,保留占位以便与旧 JS 调用链一致 */ }
function formatTime(key) {
  const v = String(form[key] || '').replace(/\D/g, '')
  if (v.length === 4) form[key] = v
}
function autoMul() {
  if (mulTouched.value || isHoliday.value || isTs.value || isGw.value || isComp.value || form.shiftType) return
  if (!form.workDate) return
  const d = new Date(form.workDate.replace(/-/g, '/')).getDay()
  form.multiplier = (d === 0 || d === 6) ? 2 : 1.5
}
function onDateChange() {
  form.fullDayEnd = defaultFullDayEnd(form.workDate)
  autoMul()
}
function onWorkTypeChange() {
  const wt = form.workType
  if (isHoliday.value && isComp.value) form.settleType = '加班费'
  if (!canFullDay.value) { form.isFullDay = false }
  if (isExclusiveType.value) form.shiftType = '白班'
  else if (!form.isFullDay) form.shiftType = ''
  if (isTs.value) form.dailyWage = 130
  mulTouched.value = false
  form.multiplier = isHoliday.value ? 3 : (isGw.value ? 2 : 1.5)
  autoMul()
  if (isComp.value) form.multiplier = 1
}
function onSettleChange() {
  if (isComp.value) { form.multiplier = 1; form.settleType = '补休' }
  else if (form.multiplier === 1) form.multiplier = isHoliday.value ? 3 : 1.5
}
function onFullDayChange() {
  if (form.isFullDay) {
    if (!form.shiftType) form.shiftType = '白班'
    form.fullDayEnd = defaultFullDayEnd(form.workDate)
  } else if (!isExclusiveType.value) {
    form.shiftType = ''
  }
}
function onShiftChange() {
  if (form.isFullDay && !form.shiftType) { form.shiftType = '白班'; ElMessage.warning('勾选全天8小时加班时必须指定班次') }
}
function onPersonChange() {
  const p = personOptions.value.find((x) => x.id === form.personnelId)
  if (p) form.dailyWage = isTs.value ? 130 : Number(p.daily_wage || 0)
}
function pushHistory(text) {
  if (!text) return
  const list = [text, ...reasonHistory.value.filter((x) => x !== text)].slice(0, 12)
  reasonHistory.value = list
  localStorage.setItem('sswhl-overtime-reason-history', JSON.stringify(list))
}
function removeHistory(i) {
  reasonHistory.value.splice(i, 1)
  localStorage.setItem('sswhl-overtime-reason-history', JSON.stringify(reasonHistory.value))
}
async function loadGongdan() {
  if (!form.workOrderNo) return
  try {
    const r = await api.getGongdan(form.workOrderNo)
    if (r.success) { form.address = r.dizhi || form.address; if (r.riqi) form.workDate = String(r.riqi).slice(0, 10) }
  } catch { /* 工单模块未迁移时静默 */ }
}

function timePayload() {
  const day = form.workDate
  if (isExclusive.value) {
    if (form.shiftType === '晚班') {
      return { start: `${day} ${form.fullDayEnd}`, end: `${nextDay(day)} 08:30` }
    }
    return { start: `${day} 08:30`, end: `${day} ${form.fullDayEnd}` }
  }
  const a = toMin(form.startQx), b = toMin(form.endQx)
  if (a === null || b === null) return null
  const fmt = (m) => `${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
  return { start: `${day} ${fmt(a)}`, end: `${b <= a ? nextDay(day) : day} ${fmt(b)}` }
}
function nextDay(d) {
  const dt = new Date(d.replace(/-/g, '/'))
  dt.setDate(dt.getDate() + 1)
  return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`
}

async function loadSub() {
  const id = props.options.detailId || props.options.applyId
  if (!id || props.options.mode !== 'personal') return
  try {
    const r = await api.listEntries(id, 'personal')
    subEntries.value = r.rows || []
  } catch { subEntries.value = [] }
}
async function editSub(row) {
  form.entryId = row.id
  form.workType = row.work_type || form.workType
  form.workDate = row.work_date
  form.startQx = (row.start_time || '').slice(11, 16).replace(':', '')
  form.endQx = (row.end_time || '').slice(11, 16).replace(':', '')
  form.reason = row.reason || ''
  form.workOrderNo = row.work_order_no || ''
  form.address = row.address || ''
  form.multiplier = Number(row.multiplier || 1.5)
  form.dailyWage = Number(row.daily_wage || 0)
  form.isFullDay = !!row.is_full_day
  form.shiftType = row.shift_type || ''
  form.personnelId = row.personnelId || form.personnelId
  mulTouched.value = true
  onWorkTypeChange()
}
async function deleteSub(row) {
  await ot.confirm('确定删除该时段吗？')
  await api.deleteEntry(row.id)
  ElMessage.success('删除成功')
  await loadSub()
  emit('saved')
}

async function save(closeAfter) {
  if (!form.workType) return ElMessage.warning('请选择加班类别')
  if (!form.personnelId) return ElMessage.warning('请选择加班人员')
  if (!form.workDate) return ElMessage.warning('请选择日期')
  const tp = timePayload()
  if (!tp) return ElMessage.warning('请填写开始/结束时间（4位数字）')
  if (isWx.value && (!form.workOrderNo || !form.address)) return ElMessage.warning('维抢修加班必须填写工单号和地址')
  if (isHoliday.value && ![2, 3].includes(Number(form.multiplier))) return ElMessage.warning('法定节假日倍数只能填 2 或 3')
  const payload = {
    applyId: props.options.mode === 'apply' ? (props.options.applyId || 0) : (props.options.detailId || 0),
    entryId: form.entryId || 0,
    personnelId: form.personnelId,
    recordType: props.options.mode === 'apply' ? 'apply' : 'personal',
    workDate: form.workDate, startTime: tp.start, endTime: tp.end,
    workType: form.workType, multiplier: Number(form.multiplier),
    dailyWage: Number(form.dailyWage) || 0, reason: form.reason,
    workOrderNo: form.workOrderNo, address: form.address,
    shiftLabel: form.shiftType || '', settleType: form.settleType,
    isFullDay: !!form.isFullDay, applyMonth: form.applyMonth,
    applyDate: `${form.workDate} 00:00`,
    fullDayEnd: form.fullDayEnd,
  }
  saving.value = true
  try {
    const r = await api.saveEntry(payload)
    ElMessage.success(r.msg || '保存成功')
    pushHistory(form.reason)
    emit('saved')
    if (props.options.onSaved) props.options.onSaved()
    await loadSub()
    if (closeAfter) close(false)
    else {
      const keep = keepName.value ? form.personnelId : null
      Object.assign(form, blank())
      form.personnelId = keep
      mulTouched.value = false
      onWorkTypeChange()
    }
  } finally { saving.value = false }
}

function close(v) { emit('update:modelValue', !!v) }

watch(() => props.modelValue, async (open) => {
  if (!open) return
  const o = props.options || {}
  readonly.value = !!o.readonly
  Object.assign(form, blank())
  form.applyMonth = o.applyMonth || ot.currentMonth.value
  form.workType = o.workType || ''
  form.settleType = o.settleType || '加班费'
  form.applyMonth = o.applyMonth || ot.currentMonth.value
  if (o.mode === 'personal' && !ot.perms.value.is_admin && ot.dicts.value.my_personnel) {
    form.personnelId = ot.dicts.value.my_personnel.id
  } else if (o.personnelId) {
    form.personnelId = o.personnelId
  }
  mulTouched.value = false
  onPersonChange()
  onWorkTypeChange()
  onDateChange()
  if (o.entryId) {
    try {
      const id = o.detailId || o.applyId
      const r = await api.listEntries(id, o.mode === 'apply' ? 'apply' : 'personal')
      const row = (r.rows || []).find((x) => x.id === o.entryId)
      if (row) editSub(row)
    } catch { /* ignore */ }
  }
  await loadSub()
})
</script>
