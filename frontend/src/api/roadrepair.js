import request from './request'

export const listRepairs = (params) => request.get('/roadrepair', { params })
export const getRepairDicts = () => request.get('/roadrepair/dicts')
export const getRepairById = (id) => request.get(`/roadrepair/${id}`)
export const createRepair = (data) => request.post('/roadrepair', data)
export const updateRepair = (id, data) => request.put(`/roadrepair/${id}`, data)
export const deleteRepair = (id) => request.delete(`/roadrepair/${id}`)
export const listProgress = (id) => request.get(`/roadrepair/${id}/progress`)
export const updateProgress = (id, progress) =>
  request.post(`/roadrepair/${id}/progress`, { progress })
export const batchUpdateProgress = (ids, progress) =>
  request.post('/roadrepair/progress-batch', { ids, progress })

// 价格管理
export const listPrices = (params) => request.get('/roadrepair/prices', { params })
export const getPriceOptions = (company) =>
  request.get('/roadrepair/price-options', { params: { company } })
export const matchPrice = (company, road_type) =>
  request.get('/roadrepair/match-price', { params: { company, road_type } })
export const savePrice = (data) => request.post('/roadrepair/prices', data)
export const deletePrice = (id) => request.delete(`/roadrepair/prices/${id}`)

// 附件
export const listAttachments = (id) => request.get(`/roadrepair/${id}/attachments`)
export const uploadAttachment = (id, file) => {
  const formData = new FormData()
  formData.append('file', file)
  return request.post(`/roadrepair/${id}/attachments`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
export const deleteAttachment = (id) => request.delete(`/roadrepair/attachments/${id}`)

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

export async function exportRepairs(params) {
  const blob = await request.get('/roadrepair/export', { params, responseType: 'blob' })
  saveBlob(blob, `道路维修记录_${new Date().toISOString().slice(0, 10)}.xlsx`)
}

// 附件下载:先换短令牌再走浏览器下载
export async function downloadAttachment(att) {
  const res = await request.post(`/roadrepair/attachments/${att.id}/token`)
  const url = `/api${res.url.replace(/^\/api/, '')}`
  const a = document.createElement('a')
  a.href = url
  a.download = att.file_name || '附件'
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}
