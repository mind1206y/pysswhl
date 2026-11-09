import request from './request'

// ===== 列表与基础 =====
export const listWaterFee = (params) => request.get('/waterfee', { params })
export const listYears = () => request.get('/waterfee/years')
export const listDaoruOptions = () => request.get('/waterfee/daoru-options')
export const listStatistics = (nd) => request.get('/waterfee/statistics', { params: { nd } })
export const createWaterFee = (data) => request.post('/waterfee', data)
export const updateWaterFee = (id, data) => request.put(`/waterfee/${id}`, data)
export const batchUpdate = (ids, data) => request.post('/waterfee/batch-update', { ids, data })
export const batchDelete = (ids) => request.post('/waterfee/batch-delete', { ids })

// ===== 日志 =====
export const listLogs = (id, source = 'shuifeixitong') =>
  request.get(`/waterfee/logs/${id}`, { params: { source } })

// ===== 变动历史 =====
export const listRowHistory = (id) => request.get(`/waterfee/${id}/history`)
export const listBiandong = (params) => request.get('/waterfee/biandong', { params })
export const updateBiandong = (id, data) => request.put(`/waterfee/biandong/${id}`, data)
export const batchDeleteBiandong = (ids) => request.post('/waterfee/biandong/batch-delete', { ids })
export const extractToHistory = (ids, data) => request.post('/waterfee/extract', { ids, data })
export const batchInLishi = (ids) => request.post('/waterfee/batch-in-lishi', { ids })

// ===== 复制年度 =====
export const getCopyCount = (nd) => request.get('/waterfee/copy-count', { params: { nd } })
export const copyToNextYear = (nd) => request.post(`/waterfee/copy-to-next-year?nd=${nd}`)

// ===== Excel =====
// 导入新增:multipart 直接用 axios 原始实例不方便,这里用 request(FormData 自动设置 boundary)
// 解析 Excel 表头,供导入列选择
export function importHeaders(file) {
  const fd = new FormData()
  fd.append('file', file)
  return request.post('/waterfee/import-headers', fd)
}

export function importExcel(file, nd, opts = {}) {
  const fd = new FormData()
  fd.append('file', file)
  return request.post(
    `/waterfee/import?nd=${nd}` +
    `&is_quxiao=${!!opts.isQuxiao}` +
    (opts.quxiaoriqi ? `&quxiaoriqi=${opts.quxiaoriqi}` : '') +
    `&cancel_writeback=${!!opts.cancelWriteback}` +
    // 后端参数名是 selected_cols(下划线),别改成驼峰否则勾选的列会被忽略
    (opts.selectedCols ? `&selected_cols=${opts.selectedCols.join(',')}` : ''),
    fd
  )
}

export function importUpdateExcel(file, nd, selectedCols = []) {
  const fd = new FormData()
  fd.append('file', file)
  const cols = selectedCols.length ? `&selected_cols=${selectedCols.join(',')}` : ''
  return request.post(`/waterfee/import-update?nd=${nd}${cols}`, fd)
}

import axios from 'axios'
export async function downloadExport(kind, params, filename) {
  const path = {
    full: '/waterfee/export',
    simplified: '/waterfee/export?simplified=true',
    ls: '/waterfee/biandong/export',
    report: '/waterfee/export-report',
  }[kind]
  const query = Object.entries(params || {})
    .filter(([, v]) => v !== '' && v !== null && v !== undefined)
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')
  const resp = await axios.get(`/api${path}${query ? '&' + query : ''}`, {
    responseType: 'blob',
    headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
  })
  const url = URL.createObjectURL(resp.data)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
