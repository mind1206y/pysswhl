import request from './request'

// 车辆油量统计报表(照旧 oiltj)
export const getOiltjDicts = () => request.get('/oiltj/dicts')
export const getOiltjMonths = (year) => request.get('/oiltj/months', { params: { year } })
export const getOiltjCars = (bmid) => request.get('/oiltj/cars', { params: bmid ? { bmid } : {} })
export const listOiltj = (params) => request.get('/oiltj', { params })

// 行展开子表 / 图表
export const getYouliang = (cheid, year) =>
  request.get(`/oiltj/${cheid}/youliang`, { params: { year } })
export const getOilChart = (cheid, year) =>
  request.get(`/oiltj/${cheid}/chart`, { params: { year } })
export const getGlChart = (cheid, year) =>
  request.get(`/oiltj/${cheid}/glchart`, { params: { year } })
export const getZChart = (params) => request.get('/oiltj/zchart', { params })
export const getMonthStat = (cheid, year) =>
  request.get('/oiltj/month-stat', { params: { cheid, year } })

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

// 三个导出(与列表同一套筛选条件)
export async function exportOiltjMonth(params) {
  const blob = await request.get('/oiltj/export-month', { params, responseType: 'blob' })
  saveBlob(blob, '加油统计表.xlsx')
}
export async function exportOiltjYear(params) {
  const blob = await request.get('/oiltj/export-year', { params, responseType: 'blob' })
  saveBlob(blob, '油耗统计表.xlsx')
}
export async function exportOiltjFinance(params) {
  const blob = await request.get('/oiltj/export-finance', { params, responseType: 'blob' })
  saveBlob(blob, '加油财务表.xlsx')
}
