import request from './request'

export const listChuxian = (params) => request.get('/chuxian', { params })
export const getChuxianDicts = () => request.get('/chuxian/dicts')
export const searchChuxianVehicles = (q = '') =>
  request.get('/chuxian/vehicles', { params: { q } })
export const getChuxianCarExtra = (cheId, riqi) =>
  request.get('/chuxian/car-extra', { params: { cheId, riqi } })
export const getChuxian = (id) => request.get(`/chuxian/${id}`)
export const createChuxian = (data) => request.post('/chuxian', data)
export const updateChuxian = (id, data) => request.put(`/chuxian/${id}`, data)
export const deleteChuxian = (id) => request.delete(`/chuxian/${id}`)
export const createChuxianImageToken = (id) => request.post(`/chuxian/images/${id}/token`)

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

export async function exportChuxian(params) {
  const blob = await request.get('/chuxian/export', { params, responseType: 'blob' })
  saveBlob(blob, '车辆出险信息表.xlsx')
}
