import request from './request'

function saveBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// ===== 台账 / 字典 =====
export const listCelou = (params) => request.get('/celou', { params })
export const getCelouDicts = () => request.get('/celou/dicts')
export const getCelouMonths = (nd) => request.get('/celou/months', { params: { nd } })
export const getCelouUsernames = () => request.get('/celou/usernames')

// ===== 管理操作 =====
export const deleteCelou = (ids) => request.post('/celou/delete', { ids })
export const batchNonYuding = (ids) => request.post('/celou/batch-non-yuding', { ids })
export const uploadCelou = (formData) =>
  request.post('/celou/upload', formData, { timeout: 120000 })

export async function downloadCelouTemplate() {
  const blob = await request.get('/celou/template', { responseType: 'blob' })
  saveBlob(blob, '测漏成果表.xls')
}

export async function exportCelou(params, year) {
  const blob = await request.get('/celou/export', { params, responseType: 'blob' })
  saveBlob(blob, `测漏成果明细表_${year || '全部年度'}.xlsx`)
}

// ===== 统计图表 =====
export const getChartTb = (params) => request.get('/celou/charts/tb', { params })
export const getChartPie = (params) => request.get('/celou/charts/pie', { params })
export const getChartBar = (params) => request.get('/celou/charts/bar', { params })

// ===== 热力图 / 工单 =====
export const getHeatmapPoints = (params) => request.get('/celou/heatmap/points', { params })
export const getHeatmapStats = (params) => request.get('/celou/heatmap/stats', { params })
export const getHeatmapTileToken = () => request.post('/celou/heatmap/tile-token')
export const getWorkOrder = (no) => request.get('/celou/workorder', { params: { no } })
