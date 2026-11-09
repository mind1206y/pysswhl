export const CATEGORIES = ['更新改造', '大修理', '管道工程', '长期待摊', '中期更新', '中期大修']
export const MIDDLE_CATEGORIES = ['中期更新', '中期大修']
export const LEIBIE_OPTIONS = ['生产类', '安全类', '福利类', '研发类', '其他']

export const TODO_STATUS = [
  { value: '专管员落实', label: '待处理计划', type: 'info' },
  { value: '售水待汇总', label: '已提交计划', type: 'primary' },
  { value: '已回退', label: '已回退营业所', type: 'danger' },
  { value: '售水通过', label: '已通过计划', type: 'success' },
  { value: '删除', label: '已删除', type: 'info' },
]

export const SUMMARY_STATUS = [
  { value: '售水待汇总', label: '售水待汇总', type: 'primary' },
  { value: '已回退', label: '已回退营业所', type: 'danger' },
  { value: '售水通过', label: '已通过计划', type: 'success' },
  { value: '删除', label: '已删除', type: 'info' },
]

export function money(v, digits = 2) {
  if (v === null || v === undefined || v === '') return ''
  const n = Number(v)
  return Number.isFinite(n) ? n.toFixed(digits) : ''
}

export function tzInfo(row) {
  const jine = Number(row.jine || 0)
  if (row.startjine === null || row.startjine === undefined || row.startjine === '') return null
  const diff = Math.round((jine - Number(row.startjine)) * 100) / 100
  if (diff > 0) return { text: `调增 +${diff.toFixed(2)}`, color: '#c0392b' }
  if (diff < 0) return { text: `调减 -${Math.abs(diff).toFixed(2)}`, color: '#1e7e34' }
  return { text: '无调整', color: '#999999' }
}

export function statusType(zt) {
  if (zt === '售水通过' || zt === '已报售水') return 'success'
  if (zt === '已回退' || zt === '售水退回' || zt === '删除') return 'danger'
  if (zt === '售水待汇总') return 'warning'
  return 'info'
}

export function statusText(zt) {
  if (zt === '售水专管审批') return '已报售水'
  if (zt === '已回退') return '已回退营业所'
  if (zt === '售水通过') return '已通过计划'
  return zt || '-'
}

export function isCompleted(row) {
  const s = row.jdztMaxLx || row.jdzt || ''
  return ['完成计划', '付完质保金', '尚余质保金'].includes(s) || s.startsWith('完成所有手续')
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
