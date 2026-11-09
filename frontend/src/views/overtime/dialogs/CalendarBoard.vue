<template>
  <div class="cal-wrap">
    <div v-if="!months.length" class="hint" style="padding: 16px">{{ emptyText }}</div>
    <div v-for="m in months" :key="m.key" class="cal-month">
      <div class="cal-month-title">{{ m.year }}年{{ m.month }}月</div>
      <div class="cal-weekhead">
        <div v-for="(w, i) in ['一', '二', '三', '四', '五', '六', '日']" :key="w"
             class="cal-wh" :class="{ 'cal-wh-we': i >= 5 }">{{ w }}</div>
      </div>
      <div class="cal-grid">
        <template v-for="(c, i) in m.cells" :key="i">
          <div v-if="!c.day" class="cal-cell cal-cell-blank"></div>
          <div v-else class="cal-cell">
            <div class="cal-daynum" :class="{ sun: c.dow === 6, sat: c.dow === 5 }">{{ c.day }}</div>
            <div v-for="(e, j) in c.entries" :key="j" class="cal-entry" :class="'cal-lv' + level(e.rawHours)"
                 :title="tip(e)">{{ Number(e.rawHours || 0).toFixed(2) }}h</div>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  rows: { type: Array, default: () => [] },
  emptyText: { type: String, default: '该记录暂无加班明细' },
})

function level(h) {
  const v = Number(h) || 0
  if (v <= 0) return 0
  if (v < 2) return 1
  if (v < 4) return 2
  if (v < 6) return 3
  if (v < 8) return 4
  return 5
}
function tip(e) {
  const s = (e.startTime || '').slice(11, 16) || (e.start_time || '').slice(11, 16)
  const t = (e.endTime || '').slice(11, 16) || (e.end_time || '').slice(11, 16)
  return `${s}-${t} | 原始${Number(e.rawHours ?? e.raw_hours ?? 0).toFixed(2)}h | ${e.workType || e.work_type || ''} | ${e.reason || ''}`
}
const months = computed(() => {
  const byMonth = {}
  for (const e of props.rows || []) {
    const d = e.workDate || e.work_date
    if (!d) continue
    const key = String(d).slice(0, 7)
    ;(byMonth[key] ||= {})[Number(String(d).slice(8, 10))] ||= []
    byMonth[key][Number(String(d).slice(8, 10))].push(e)
  }
  return Object.keys(byMonth).sort().map((key) => {
    const [year, month] = key.split('-').map(Number)
    const first = new Date(year, month - 1, 1)
    const offset = (first.getDay() + 6) % 7
    const days = new Date(year, month, 0).getDate()
    const cells = Array.from({ length: offset }, () => ({ day: 0 }))
    for (let d = 1; d <= days; d++) {
      const dow = (new Date(year, month - 1, d).getDay() + 6) % 7
      cells.push({ day: d, dow, entries: byMonth[key][d] || [] })
    }
    while (cells.length % 7) cells.push({ day: 0 })
    return { key, year, month, cells }
  })
})
</script>
