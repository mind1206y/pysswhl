<template>
  <el-dialog :model-value="modelValue" @update:model-value="close" title="批量新建加班记录"
             width="760px" top="4vh" class="ot-dialog"
             :close-on-click-modal="false" append-to-body destroy-on-close>
    <!-- Step 1 选人 -->
    <template v-if="step === 1">
      <div class="batch-step-tip" style="display: flex; justify-content: space-between; align-items: center">
        <div>
          <b>第 1 步 / 共 2 步 · 选择人员</b>
          <span class="e-tip" style="margin-left: 10px">可跨部门多选，下一步为所选人员填写相同的加班内容</span>
        </div>
        <span style="color: #533afd; font-weight: bold; white-space: nowrap; margin-left: 12px">已选 {{ selectedIds.length }} 人</span>
      </div>
      <div class="filter-row" style="margin-bottom: 8px">
        <div class="filter-group">
          <label>部门：</label>
          <el-tree-select v-model="deptFilter" :data="ot.deptTreeData.value" node-key="value"
                          :props="{ label: 'label', children: 'children' }" check-strictly clearable
                          style="width: 230px" size="small" />
        </div>
        <div class="filter-group">
          <el-input v-model="personSearch" placeholder="搜索姓名/工号" size="small" clearable style="width: 160px" />
        </div>
        <el-button size="small" @click="selectAll">全选</el-button>
        <el-button size="small" @click="selectedIds = []">取消全选</el-button>
      </div>
      <div class="transfer-body">
        <div class="transfer-panel">
          <div class="transfer-title">可选人员</div>
          <div class="transfer-list">
            <el-checkbox-group v-model="selectedIds" style="display: block">
              <div v-for="p in filteredPersonnel" :key="p.id" style="padding: 3px 2px">
                <el-checkbox :value="p.id">
                  {{ p.name }} <span class="e-tip">{{ p.employee_no }}</span>
                  <span class="e-tip" style="float: right">¥{{ p.daily_wage || 0 }}</span>
                </el-checkbox>
              </div>
            </el-checkbox-group>
            <div v-if="!filteredPersonnel.length" class="hint" style="padding: 12px">无可选项</div>
          </div>
        </div>
        <div class="transfer-panel" style="max-width: 210px">
          <div class="transfer-title">已选人员（{{ selectedIds.length }}）</div>
          <div class="transfer-list">
            <div v-for="id in selectedIds" :key="id" style="display: flex; justify-content: space-between; padding: 3px 2px; font-size: 12px">
              <span>{{ nameOf(id) }}</span>
              <span class="grid-danger" @click="selectedIds = selectedIds.filter((x) => x !== id)">×</span>
            </div>
          </div>
        </div>
      </div>
    </template>

    <!-- Step 2 填单 -->
    <template v-else>
      <div class="batch-step-tip">
        <b>第 2 步 / 共 2 步 · 填写加班内容</b>
        <span class="e-tip" style="margin-left: 10px">将为 <b style="color: #533afd">{{ selectedIds.length }}</b> 人创建相同记录：{{ selectedNames }}</span>
      </div>
      <div class="form-card">
        <el-form label-width="100px" size="small" class="form-grid">
          <el-form-item label="结算方式">
            <el-select v-model="form.settleType" style="width: 150px" @change="onSettleChange">
              <el-option label="加班费" value="加班费" />
              <el-option label="补休" value="补休" :disabled="!canComp" />
            </el-select>
            <span class="e-tip" style="margin-left: 8px">{{ settleTip }}</span>
          </el-form-item>
          <el-form-item label="加班类别" class="required">
            <el-select v-model="form.workType" style="width: 220px" filterable @change="onWorkTypeChange">
              <el-option v-for="w in ot.workTypes.value" :key="w" :label="w" :value="w" />
            </el-select>
            <el-checkbox v-model="form.isFullDay" :disabled="!canFullDay || multiDate" style="margin-left: 10px"
                         @change="onFullDayChange">设为全天8小时</el-checkbox>
          </el-form-item>
          <el-form-item label="所属月份" class="required">
            <el-select v-model="form.applyMonth" style="width: 160px">
              <el-option v-for="m in ot.months.value" :key="m" :label="m" :value="m" />
            </el-select>
          </el-form-item>
          <el-form-item label="日期" class="required" v-if="!multiDate">
            <el-date-picker v-model="form.workDate" type="date" value-format="YYYY-MM-DD"
                            style="width: 150px" @change="onDateChange" />
            <span class="weekday-chip" style="margin-left: 8px">{{ ot.weekLabel(form.workDate) }}</span>
          </el-form-item>
          <el-form-item label="选择日期" class="span2 required" v-if="multiDate">
            <div style="width: 100%">
              <div class="filter-row" style="margin-bottom: 6px">
                <el-select v-model="gridMonth" style="width: 120px" @change="rebuildDateGrid">
                  <el-option v-for="m in ot.months.value" :key="m" :label="m" :value="m" />
                </el-select>
                <el-button size="small" @click="setAllDates(false)">全选工作日</el-button>
                <el-button size="small" @click="setAllDates(true)">全选</el-button>
                <el-button size="small" @click="clearDates">清空</el-button>
                <span style="color: #533afd; font-weight: bold">已选 {{ selectedDates.length }} 天</span>
              </div>
              <div class="date-grid">
                <div v-for="w in ['一', '二', '三', '四', '五', '六', '日']" :key="w" class="date-cell" style="text-align: center; font-weight: bold">{{ w }}</div>
                <div v-for="(c, i) in dateCells" :key="i" class="date-cell" :class="{ blank: !c.day, we: c.we }">
                  <label v-if="c.day">
                    <input type="checkbox" :value="c.date" v-model="selectedDates" />
                    <span :class="{ sun: c.dow === 6, sat: c.dow === 5 }">{{ c.day }}</span>
                  </label>
                </div>
              </div>
              <div class="e-tip" style="margin-top: 4px">多日期模式不支持跨天时段；勾选的日期会与下方每个时段组合生成记录。</div>
            </div>
          </el-form-item>
          <el-form-item label="每日时段" class="span2 required" v-if="multiDate">
            <div style="width: 100%">
              <div v-for="(s, i) in slots" :key="i" class="slot-row">
                <span class="e-tip">时段{{ i + 1 }}</span>
                <el-input v-model="s.start" style="width: 100px" maxlength="5" placeholder="0830" />
                <span>至</span>
                <el-input v-model="s.end" style="width: 100px" maxlength="5" placeholder="1200" />
                <el-button size="small" :disabled="slots.length <= 1" @click="slots.splice(i, 1)">×</el-button>
              </div>
              <el-button size="small" :disabled="slots.length >= 3" @click="slots.push({ start: '', end: '' })">添加时段</el-button>
              <span class="e-tip" style="margin-left: 8px">每天可添加 1~3 个时段，结束时间必须晚于开始时间</span>
            </div>
          </el-form-item>
          <el-form-item label="班次" v-if="!multiDate && (isExclusiveType || form.isFullDay)">
            <el-select v-model="form.shiftType" style="width: 110px" clearable :disabled="form.isFullDay">
              <el-option v-if="!form.isFullDay" label="不指定" value="" />
              <el-option label="白班" value="白班" />
              <el-option label="晚班" value="晚班" />
            </el-select>
            <el-select v-model="form.fullDayEnd" style="width: 88px; margin-left: 8px">
              <el-option label="18:00" value="18:00" />
              <el-option label="17:30" value="17:30" />
            </el-select>
          </el-form-item>
          <template v-if="!multiDate && !isExclusive">
            <el-form-item label="开始时间" class="required">
              <el-input v-model="form.startQx" style="width: 110px" maxlength="4" placeholder="如 0830"
                        @blur="formatTime('startQx')" />
              <span class="e-tip" style="margin-left: 8px">4位数字，如 0830 → 08:30</span>
            </el-form-item>
            <el-form-item label="结束时间" class="required">
              <el-input v-model="form.endQx" style="width: 110px" maxlength="4" placeholder="如 1730"
                        @blur="formatTime('endQx')" />
              <span class="e-tip" style="margin-left: 8px">小于开始时间则为次日</span>
            </el-form-item>
          </template>
          <el-form-item label="工单号" class="required" v-if="isWx">
            <el-input v-model="form.workOrderNo" style="width: 240px" />
          </el-form-item>
          <el-form-item label="地址" class="span2 required" v-if="isWx">
            <el-input v-model="form.address" />
          </el-form-item>
          <el-form-item label="工作内容" class="span2">
            <div style="display: flex; width: 100%; gap: 6px">
              <el-input v-model="form.reason" placeholder="输入工作内容，或点历史标签填入" />
              <el-button size="small" @click="historyVisible = !historyVisible">▾</el-button>
            </div>
            <div v-if="historyVisible" style="width: 100%; margin-top: 6px">
              <el-tag v-for="(h, i) in reasonHistory" :key="h" closable size="small" round
                      style="margin: 0 6px 5px 0; cursor: pointer" @click="form.reason = h"
                      @close="removeHistory(i)">{{ h }}</el-tag>
              <span class="e-tip" v-if="!reasonHistory.length">暂无历史记录</span>
            </div>
          </el-form-item>
          <el-form-item label="倍数" class="span2" v-if="!isComp">
            <el-input-number v-model="form.multiplier" :precision="1" :min="0.5" :step="0.5" style="width: 120px" @change="mulTouched = true" />
            <span v-for="m in [1, 1.5, 2, 3]" :key="m" class="mul-tag"
                  :class="{ active: form.multiplier === m }" @click="setMul(m)">{{ m.toFixed(1) }}</span>
            <span class="e-tip" v-if="isHoliday" style="margin-left: 8px">法定节假日只能 2 或 3</span>
          </el-form-item>
          <el-form-item label="工资单价" class="span2">
            <el-input-number v-model="form.dailyWage" :precision="2" :min="0" style="width: 150px" />
            <span style="margin-left: 6px">元/天</span>
            <span class="e-tip" style="margin-left: 10px">特水开关阀门缺省 130；填 0 用各人配置，填数值则全员统一</span>
          </el-form-item>
        </el-form>
        <div class="sumbox"><span v-html="estimate"></span></div>
      </div>
    </template>

    <template #footer>
      <div style="display: flex; justify-content: center; gap: 10px">
        <template v-if="step === 1">
          <el-button type="primary" @click="goStep2">下一步 »</el-button>
          <el-button @click="close(false)">取消</el-button>
        </template>
        <template v-else>
          <el-button type="primary" :loading="saving" @click="doCreate">确认创建</el-button>
          <el-button v-if="!selfMode" @click="step = 1">« 返回选人</el-button>
          <el-button @click="close(false)">取消</el-button>
        </template>
      </div>
    </template>

    <el-dialog v-model="resultVisible" title="批量创建结果" width="520px" class="ot-dialog" append-to-body>
      <div style="font-size: 14px; margin-bottom: 10px">{{ result.msg }}</div>
      <div v-if="result.hourWarnings?.length" style="color: #f0ad4e; font-size: 12px">
        <div v-for="(w, i) in result.hourWarnings" :key="i">{{ w.name }}：{{ w.reason }}</div>
      </div>
      <el-table v-if="result.warnings?.length" :data="result.warnings" size="small" border style="margin-top: 8px">
        <el-table-column prop="name" label="人员" width="120" />
        <el-table-column prop="reason" label="跳过原因" />
      </el-table>
      <template #footer><el-button type="primary" @click="resultVisible = false">知道了</el-button></template>
    </el-dialog>
  </el-dialog>
</template>

<script setup>
import { computed, inject, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import * as api from '@/api/overtime'

const props = defineProps({ modelValue: Boolean })
const emit = defineEmits(['update:modelValue', 'saved'])
const ot = inject('ot')

const step = ref(1)
// 用 computed 而不是在 watch 里算一次:字典异步就绪前 perms 为空会误判成「非核销员」,
// 导致第 2 步的「返回选人」按钮一直不出现。
const selfMode = computed(() => !ot.perms.value.is_verifier)
const saving = ref(false)
const deptFilter = ref(null)
const personSearch = ref('')
const selectedIds = ref([])
const resultVisible = ref(false)
const result = ref({})
// 与「加班明细录入」共用同一份工作内容历史、同一套倍数手动改写标记
const mulTouched = ref(false)
const historyVisible = ref(false)
const reasonHistory = ref(JSON.parse(localStorage.getItem('sswhl-overtime-reason-history') || '[]'))

const blank = () => ({
  settleType: '加班费', workType: '', applyMonth: ot.currentMonth.value,
  workDate: new Date().toISOString().slice(0, 10), isFullDay: false,
  shiftType: '', fullDayEnd: '18:00', startQx: '', endQx: '',
  workOrderNo: '', address: '', reason: '', multiplier: 1.5, dailyWage: 0,
})
const form = reactive(blank())
const slots = ref([{ start: '', end: '' }])
const gridMonth = ref(ot.currentMonth.value)
const selectedDates = ref([])
const dateCells = ref([])

const isComp = computed(() => form.settleType === '补休')
const isHoliday = computed(() => form.workType === '法定节假日加班费')
const isTs = computed(() => form.workType === '特水开关阀门')
const isWx = computed(() => form.workType === '维抢修加班')
const isGw = computed(() => form.workType === '管网周末加班')
const isExclusiveType = computed(() => !!ot.dicts.value.exclusive_work_types?.includes(form.workType))
const multiDate = computed(() => !!ot.dicts.value.multi_date_work_types?.includes(form.workType))
const canComp = computed(() => !!ot.dicts.value.comp_leave_work_types?.includes(form.workType) || !form.workType)
const canFullDay = computed(() => !['法定节假日加班费', '应急响应值班', '管网周末加班', '特水开关阀门', '维抢修加班'].includes(form.workType) && !!form.workType)
const isExclusive = computed(() => form.isFullDay || !!form.shiftType)
const settleTip = computed(() => isComp.value ? '1:1 补助调休，无加班费' : '按日工资和倍数计算加班费')
const filteredPersonnel = computed(() => {
  const kw = (personSearch.value || '').trim().toLowerCase()
  return ot.personnel.value.filter((p) => {
    if (deptFilter.value && p.dept_id !== deptFilter.value) return false
    if (kw && !(`${p.name} ${p.employee_no}`.toLowerCase().includes(kw))) return false
    return true
  })
})
const selectedNames = computed(() => selectedIds.value.slice(0, 8).map(nameOf).join('、') +
  (selectedIds.value.length > 8 ? ` 等${selectedIds.value.length}人` : ''))
function nameOf(id) { return ot.personnel.value.find((p) => p.id === id)?.name || `ID:${id}` }
function selectAll() { selectedIds.value = filteredPersonnel.value.map((p) => p.id) }

function toMin(s) {
  const v = String(s || '').replace(/\D/g, '')
  return v.length >= 4 ? Number(v.slice(0, 2)) * 60 + Number(v.slice(2, 4)) : null
}
function perDayHours() {
  if (multiDate.value) {
    let sum = 0
    for (const s of slots.value) {
      const a = toMin(s.start), b = toMin(s.end)
      if (a === null || b === null || b <= a) return 0
      sum += (b - a) / 60
    }
    return sum
  }
  if (isExclusive.value) return 8
  const a = toMin(form.startQx), b = toMin(form.endQx)
  if (a === null || b === null) return 0
  let d = b - a
  if (d <= 0) d += 24 * 60
  return d / 60
}
const estimate = computed(() => {
  const h = perDayHours()
  const days = multiDate.value ? selectedDates.value.length : 1
  const mul = isComp.value ? 1 : (Number(form.multiplier) || 0)
  if (!h || !days) return '请填写完整信息'
  const wages = selectedIds.value.map((id) => {
    const p = ot.personnel.value.find((x) => x.id === id)
    return form.dailyWage > 0 ? form.dailyWage : Number(p?.daily_wage || 0)
  })
  const amount = wages.reduce((acc, w) => acc + Math.round(w / 8 * h * mul) * days, 0)
  const wageTip = form.dailyWage > 0 ? `统一日工资${form.dailyWage}` : '按各自配置工资'
  return multiDate.value
    ? `每人 <b>${days}天</b> × 每天 <b>${h.toFixed(2)}h</b>，${selectedIds.value.length}人合计 <b>￥${amount}元</b>（${wageTip}）`
    : `每人 <b>${h.toFixed(2)}h</b>，${selectedIds.value.length}人合计 <b>￥${amount}元</b>（${wageTip}）`
})

function defaultFullDayEnd(d) {
  if (!d) return '17:30'
  const dt = new Date(d.replace(/-/g, '/'))
  const m = dt.getMonth() + 1, day = dt.getDate()
  return ((m === 6 && day >= 1) || m === 7 || m === 8 || (m === 9 && day <= 30)) ? '18:00' : '17:30'
}
// 以下倍数/班次联动与 EntryDialog 保持同源:用户手改过倍数后,切日期或类别不得再覆盖
function setMul(v) { form.multiplier = v; mulTouched.value = true }
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
  if (isHoliday.value && isComp.value) form.settleType = '加班费'
  if (multiDate.value) { form.isFullDay = false; form.shiftType = ''; rebuildDateGrid() }
  else if (isExclusiveType.value) form.shiftType = '白班'
  else if (!form.isFullDay) form.shiftType = ''
  if (!canFullDay.value) form.isFullDay = false
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
  // 旧逻辑缺这个联动:勾「全天8小时」但班次为空时,buildEntries 会当成普通自定义时段提交
  if (form.isFullDay) {
    if (!form.shiftType) form.shiftType = '白班'
    form.fullDayEnd = defaultFullDayEnd(form.workDate)
  } else if (!isExclusiveType.value) {
    form.shiftType = ''
  }
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

function rebuildDateGrid() {
  const m = gridMonth.value || ot.currentMonth.value
  const y = Number(m.slice(0, 4)), mo = Number(m.slice(4, 6))
  const first = new Date(y, mo - 1, 1)
  const offset = (first.getDay() + 6) % 7
  const days = new Date(y, mo, 0).getDate()
  const cells = Array(offset).fill({ day: 0 })
  for (let d = 1; d <= days; d++) {
    const dt = new Date(y, mo - 1, d)
    const dow = (dt.getDay() + 6) % 7 // 0=周一
    cells.push({ day: d, dow, we: dow >= 5,
      date: `${y}-${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')}` })
  }
  dateCells.value = cells
}
function setAllDates(all) {
  const cur = new Set(selectedDates.value.filter((d) => !d.startsWith(gridMonth.value.slice(0, 4) + '-' + gridMonth.value.slice(4))))
  for (const c of dateCells.value) {
    if (c.day && (all || c.dow < 5)) cur.add(c.date)
  }
  selectedDates.value = [...cur].sort()
}
function clearDates() {
  selectedDates.value = selectedDates.value.filter((d) => !d.startsWith(gridMonth.value.slice(0, 4) + '-' + gridMonth.value.slice(4)))
}

function goStep2() {
  if (!selectedIds.value.length) return ElMessage.warning('请至少选择一名人员')
  step.value = 2
}
function close(v) { emit('update:modelValue', !!v) }

function buildEntries() {
  const out = []
  const mul = isComp.value ? 1 : Number(form.multiplier)
  const common = {
    work_type: form.workType, multiplier: mul,
    daily_wage: form.dailyWage > 0 ? form.dailyWage : null,
    reason: form.reason, work_order_no: form.workOrderNo, address: form.address,
    is_full_day: multiDate.value ? false : !!form.isFullDay,
    shift_type: multiDate.value ? '' : (form.shiftType || ''),
    full_day_end: form.fullDayEnd,
  }
  const fmt = (m) => `${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`
  const next = (d) => {
    const dt = new Date(d.replace(/-/g, '/'))
    dt.setDate(dt.getDate() + 1)
    return `${dt.getFullYear()}-${String(dt.getMonth() + 1).padStart(2, '0')}-${String(dt.getDate()).padStart(2, '0')}`
  }
  if (multiDate.value) {
    for (const d of selectedDates.value) {
      for (const s of slots.value) {
        const a = toMin(s.start), b = toMin(s.end)
        if (a === null || b === null || b <= a) continue
        out.push({ ...common, work_date: d, start_time: `${d} ${fmt(a)}`, end_time: `${d} ${fmt(b)}` })
      }
    }
    return out
  }
  const d = form.workDate
  if (isExclusive.value) {
    if (form.shiftType === '晚班') {
      out.push({ ...common, work_date: d, start_time: `${d} ${form.fullDayEnd}`, end_time: `${next(d)} 08:30` })
    } else {
      out.push({ ...common, work_date: d, start_time: `${d} 08:30`, end_time: `${d} ${form.fullDayEnd}` })
    }
  } else {
    const a = toMin(form.startQx), b = toMin(form.endQx)
    if (a === null || b === null) return []
    out.push({ ...common, work_date: d, start_time: `${d} ${fmt(a)}`,
               end_time: `${b <= a ? next(d) : d} ${fmt(b)}` })
  }
  return out
}

function formatTime(key) {
  const v = String(form[key] || '').replace(/\D/g, '')
  if (v.length === 4) form[key] = v
}
async function doCreate() {
  if (!form.workType) return ElMessage.warning('请选择加班类别')
  if (!form.applyMonth) return ElMessage.warning('请选择所属月份')
  if (!multiDate.value && !form.workDate) return ElMessage.warning('请选择日期')
  if (isHoliday.value && ![2, 3].includes(Number(form.multiplier))) return ElMessage.warning('法定节假日倍数只能填 2 或 3')
  if (isWx.value && (!form.workOrderNo || !form.address)) return ElMessage.warning('维抢修加班必须填写工单号和地址')
  if (multiDate.value && !selectedDates.value.length) return ElMessage.warning('请至少选择一个日期')
  const entries = buildEntries()
  if (!entries.length) return ElMessage.warning('请填写有效的加班时段')
  saving.value = true
  try {
    const r = await api.saveBatchRecords({
      personnelIds: selectedIds.value, settle_type: form.settleType,
      work_type: form.workType, apply_month: form.applyMonth, timeEntries: entries,
    })
    pushHistory(form.reason)
    result.value = r
    resultVisible.value = true
    emit('saved')
    if (r.created) close(false)
  } finally { saving.value = false }
}

watch(() => props.modelValue, (open) => {
  if (!open) return
  Object.assign(form, blank())
  slots.value = [{ start: '', end: '' }]
  selectedDates.value = []
  gridMonth.value = ot.currentMonth.value
  deptFilter.value = null
  personSearch.value = ''
  mulTouched.value = false
  historyVisible.value = false
  reasonHistory.value = JSON.parse(localStorage.getItem('sswhl-overtime-reason-history') || '[]')
  if (selfMode.value && ot.dicts.value.my_personnel) {
    selectedIds.value = [ot.dicts.value.my_personnel.id]
    step.value = 2
  } else {
    selectedIds.value = []
    step.value = 1
  }
  rebuildDateGrid()
  onWorkTypeChange()
  onDateChange()
})

// /dicts 是异步的:若弹窗在字典返回前打开,blank() 取到的当前月为空,
// 下拉会停在「请选择」。字典就绪后补一次,保证初值与其它 Tab 一样是当前月。
watch(() => ot.currentMonth.value, (m) => {
  if (m && !form.applyMonth) {
    form.applyMonth = m
    gridMonth.value = m
    rebuildDateGrid()
  }
}, { immediate: true })
</script>
