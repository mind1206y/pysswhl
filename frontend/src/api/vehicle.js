import request from './request'

export const listVehicles = (params) => request.get('/vehicles', { params })
export const getVehicleDicts = () => request.get('/vehicles/dicts')
export const getVehicle = (id) => request.get(`/vehicles/${id}`)
export const createVehicle = (data) => request.post('/vehicles', data)
export const updateVehicle = (id, data) => request.put(`/vehicles/${id}`, data)
export const deleteVehicle = (id) => request.delete(`/vehicles/${id}`)
export const scrapVehicle = (id) => request.put(`/vehicles/${id}/scrap`)

// 年检
export const inspectVehicle = (id, riqi) => request.post(`/vehicles/${id}/inspect`, { riqi: riqi || null })
export const undoInspectVehicle = (id) => request.post(`/vehicles/${id}/undo-inspect`)
export const batchInspect = (ids, riqi) => request.post('/vehicles/batch-inspect', { ids, riqi: riqi || null })

// 图片(短时效令牌直链)
export const createImageToken = (id, kind = 'car') =>
  request.post(`/vehicles/images/${id}/token`, null, { params: { kind } })
export const uploadVehicleImages = (id, formData) =>
  request.post(`/vehicles/${id}/images`, formData)
export const deleteVehicleImage = (id) => request.delete(`/vehicles/images/${id}`)
export const deleteAccidentImage = (id) => request.delete(`/vehicles/accident-images/${id}`)
export const uploadAccidentImages = (id, formData) =>
  request.post(`/vehicles/accidents/${id}/images`, formData)

// 出险
export const listAccidents = (id, year) =>
  request.get(`/vehicles/${id}/accidents`, { params: year ? { year } : {} })
export const addAccident = (id, data) => request.post(`/vehicles/${id}/accidents`, data)
export const updateAccident = (id, data) => request.put(`/vehicles/accidents/${id}`, data)
export const deleteAccident = (id) => request.delete(`/vehicles/accidents/${id}`)
export const listAccidentImages = (id) => request.get(`/vehicles/accidents/${id}/images`)

// 统计
export const getOilMonthStat = (id, year) =>
  request.get(`/vehicles/${id}/oil-month-stat`, { params: { year } })

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

// 导出(与列表同一套筛选条件)
export async function exportVehicles(params) {
  const blob = await request.get('/vehicles/export', { params, responseType: 'blob' })
  saveBlob(blob, '车辆信息表.xlsx')
}

export async function exportVehiclesPdf(ids) {
  const blob = await request.post('/vehicles/export-pdf', { ids }, { responseType: 'blob' })
  saveBlob(blob, '车辆图片资料.pdf')
}
