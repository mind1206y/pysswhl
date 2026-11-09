import request from './request'

export const listRepairs = (params) => request.get('/repairs', { params })
export const getRepairDicts = () => request.get('/repairs/dicts')
export const searchRepairVehicles = (num) => request.get('/repairs/vehicles', { params: { num } })
export const getVehicleHistory = (cheid) =>
  request.get('/repairs/vehicle-history', { params: { cheid } })
export const getRepair = (id) => request.get(`/repairs/${id}`)
export const createRepair = (data) => request.post('/repairs', data)
export const updateRepair = (id, data) => request.put(`/repairs/${id}`, data)
export const deleteRepair = (id) => request.delete(`/repairs/${id}`)
export const auditRepairs = (ids, approved) =>
  request.post('/repairs/audit', { ids, approved })

export const listRepairDetails = (id) => request.get(`/repairs/${id}/details`)
export const searchRepairDetails = (params) => request.get('/repairs/details', { params })
export const addRepairDetail = (id, data) => request.post(`/repairs/${id}/details`, data)
export const updateRepairDetail = (id, data) => request.put(`/repairs/details/${id}`, data)
export const deleteRepairDetail = (id) => request.delete(`/repairs/details/${id}`)
export const getRepairRemaining = (id, params) =>
  request.get(`/repairs/${id}/remaining`, { params })

// 图片(短时效令牌直链)
export const createRepairImageToken = (id) => request.post(`/repairs/images/${id}/token`)
export const uploadRepairImages = (id, formData) => request.post(`/repairs/${id}/images`, formData)
export const deleteRepairImage = (id) => request.delete(`/repairs/images/${id}`)

export const getRepairChart = (params) => request.get('/repairs/chart', { params })

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

export async function exportRepairs(params, kind = 'dan') {
  const blob = await request.get('/repairs/export', {
    params: { ...params, kind }, responseType: 'blob',
  })
  saveBlob(blob, kind === 'mx' ? '车辆维修明细.xlsx' : '车辆维修单.xlsx')
}
