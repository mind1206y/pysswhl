import request from './request'

export const getDailyDicts = () => request.get('/vehicle-daily/dicts')
export const listDaily = (params) => request.get('/vehicle-daily', { params })
export const listDailyDrivers = (params) => request.get('/vehicle-daily/drivers', { params })
export const getDailyCarInfo = (carId) => request.get(`/vehicle-daily/car-info/${carId}`)
export const getDaily = (id) => request.get(`/vehicle-daily/${id}`)
export const createDaily = (data) => request.post('/vehicle-daily', data)
export const updateDaily = (id, data) => request.put(`/vehicle-daily/${id}`, data)
export const deleteDaily = (id) => request.delete(`/vehicle-daily/${id}`)
export const bulkDeleteDaily = (ids) => request.post('/vehicle-daily/bulk-delete', { ids })

export const uploadDailyImages = (id, formData) =>
  request.post(`/vehicle-daily/${id}/images`, formData)
export const createDailyImageToken = (id) =>
  request.post(`/vehicle-daily/images/${id}/token`)
export const deleteDailyImage = (id) => request.delete(`/vehicle-daily/images/${id}`)

export const listDailyAbnormal = (params) => request.get('/vehicle-daily/abnormal', { params })
export const cleanDailyAbnormal = () => request.post('/vehicle-daily/abnormal/clean')
export const extractYearMileage = (year) =>
  request.post('/vehicle-daily/extract-mileage', null, { params: { year } })

export const importDaily = (formData) =>
  request.post('/vehicle-daily/import', formData, { timeout: 120000 })

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

export async function exportDaily(params) {
  const blob = await request.get('/vehicle-daily/export', { params, responseType: 'blob' })
  saveBlob(blob, '用车登记表.xlsx')
}

export async function exportDailyOverlap(params) {
  const blob = await request.get('/vehicle-daily/export-overlap', { params, responseType: 'blob' })
  saveBlob(blob, '公里数出错列表.xlsx')
}

export async function exportDailyGap(params) {
  const blob = await request.get('/vehicle-daily/export-gap', { params, responseType: 'blob' })
  saveBlob(blob, '公里数空挡列表.xlsx')
}
