<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getPlanCalendar } from '@/api/plan'
import { money } from './common'

const router = useRouter()
const now = new Date()
const year = ref(now.getFullYear())
const month = ref(now.getMonth() + 1)
const dateMap = ref({})
const loading = ref(false)
const drawer = ref(false)
const drawerDate = ref('')
const dayItems = ref([])

const weekLabels = ['一', '二', '三', '四', '五', '六', '日']

const cells = computed(() => {
  const first = new Date(year.value, month.value - 1, 1)
  const startOffset = (first.getDay() + 6) % 7
  const start = new Date(year.value, month.value - 1, 1 - startOffset)
  const result = []
  for (let i = 0; i < 42; i += 1) {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i)
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    const info = dateMap.value[key]
    result.push({
      key,
      day: d.getDate(),
      inMonth: d.getMonth() + 1 === month.value,
      count: info?.count || 0,
      summary: info?.summary || '',
      isToday: key === `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`,
    })
  }
  return result
})

async function load() {
  loading.value = true
  try {
    const data = await getPlanCalendar({ year: year.value, month: month.value })
    dateMap.value = data.dateMap || {}
  } finally {
    loading.value = false
  }
}

function prevMonth() {
  month.value -= 1
  if (month.value === 0) { month.value = 12; year.value -= 1 }
  load()
}

function nextMonth() {
  month.value += 1
  if (month.value === 13) { month.value = 1; year.value += 1 }
  load()
}

async function openDay(cell) {
  if (!cell.count) return
  drawerDate.value = cell.key
  const data = await getPlanCalendar({ year: year.value, month: month.value, date_text: cell.key })
  dayItems.value = data.items || []
  drawer.value = true
}

onMounted(load)
</script>

<template>
  <div class="dash-page">
    <el-card shadow="never">
      <div class="dash-head">
        <div class="title">进度看板</div>
        <div class="month-nav">
          <el-button size="small" @click="prevMonth">上月</el-button>
          <span class="month-text">{{ year }}年{{ month }}月</span>
          <el-button size="small" @click="nextMonth">下月</el-button>
        </div>
        <div class="right">
          <span class="legend-dot" /> 有进度
          <span class="legend-dot today" /> 今天
          <el-button size="small" type="primary" plain @click="router.push('/plan')">返回列表</el-button>
        </div>
      </div>

      <div class="week-row">
        <div v-for="w in weekLabels" :key="w" class="week-cell">{{ w }}</div>
      </div>
      <div v-loading="loading" class="calendar">
        <div v-for="cell in cells" :key="cell.key" class="day-cell"
          :class="{ muted: !cell.inMonth, today: cell.isToday, has: cell.count }"
          @click="openDay(cell)">
          <div class="day-num">{{ cell.day }}</div>
          <template v-if="cell.count">
            <div class="day-count">{{ cell.count }} 条</div>
            <div class="day-summary">{{ cell.summary }}</div>
          </template>
        </div>
      </div>
    </el-card>

    <el-drawer v-model="drawer" :title="drawerDate" size="500px">
      <div class="drawer-sub">共 {{ dayItems.length }} 条进度</div>
      <el-timeline>
        <el-timeline-item v-for="item in dayItems" :key="item.id"
          :timestamp="item.caozuotime" placement="top">
          <div class="tl-title">{{ item.planName }} <span class="tl-xh">{{ item.xh }}</span></div>
          <div class="tl-meta">{{ item.lb }} · {{ item.bm }} · {{ item.leixing || '未设状态' }}</div>
          <div v-if="item.miaoshu" class="tl-desc">{{ item.miaoshu }}</div>
          <div class="tl-foot">
            操作人：{{ item.caozuoren }}
            <span v-if="item.fukuan"> · 付款：{{ money(Number(item.fukuan) / 10000, 4) }} 万元</span>
          </div>
        </el-timeline-item>
      </el-timeline>
    </el-drawer>
  </div>
</template>

<style scoped>
.dash-page { display: flex; flex-direction: column; gap: 10px; }
.dash-head { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
.title { font-size: 18px; font-weight: 700; color: #1c1e54; }
.month-nav { display: flex; align-items: center; gap: 10px; }
.month-text { font-size: 16px; font-weight: 600; min-width: 110px; text-align: center; }
.right { margin-left: auto; display: flex; align-items: center; gap: 8px; font-size: 12px; color: #667; }
.legend-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: #533afd; }
.legend-dot.today { background: #ffb400; margin-left: 8px; }
.week-row { display: grid; grid-template-columns: repeat(7, 1fr); margin-top: 12px; }
.week-cell { text-align: center; font-weight: 600; color: #556; padding: 6px 0; background: #f5f7fa; }
.calendar { display: grid; grid-template-columns: repeat(7, 1fr); border-left: 1px solid #ebeef5; border-top: 1px solid #ebeef5; }
.day-cell { min-height: 96px; padding: 6px 8px; border-right: 1px solid #ebeef5; border-bottom: 1px solid #ebeef5; cursor: default; position: relative; }
.day-cell.has { cursor: pointer; background: #f6f3ff; }
.day-cell.has:hover { background: #ede7ff; }
.day-cell.muted { color: #c0c4cc; background: #fafafa; }
.day-cell.today { outline: 2px solid #ffb400; outline-offset: -2px; }
.day-num { font-size: 13px; font-weight: 600; }
.day-count { margin-top: 4px; display: inline-block; background: #533afd; color: #fff; border-radius: 10px; font-size: 11px; padding: 0 7px; }
.day-summary { margin-top: 4px; font-size: 11px; color: #6b5ca5; line-height: 1.35; }
.drawer-sub { color: #909399; font-size: 12px; margin-bottom: 12px; }
.tl-title { font-weight: 600; color: #1c1e54; }
.tl-xh { color: #533afd; font-weight: 500; margin-left: 6px; }
.tl-meta { color: #7c8ba0; font-size: 12px; margin: 2px 0; }
.tl-desc { color: #333; font-size: 13px; margin: 4px 0; }
.tl-foot { color: #909399; font-size: 12px; }
</style>
