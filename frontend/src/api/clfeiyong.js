import request from './request'

export const listClFeiyong = (params) => request.get('/clfeiyong', { params })
export const getClFeiyongDicts = () => request.get('/clfeiyong/dicts')
export const getClFeiyongVehicles = (q = '') =>
  request.get('/clfeiyong/vehicles', { params: { q } })
export const getClFeiyongUnits = (q = '') =>
  request.get('/clfeiyong/units', { params: { q } })
export const getClFeiyong = (id) => request.get(`/clfeiyong/${id}`)
export const createClFeiyong = (data) => request.post('/clfeiyong', data)
export const updateClFeiyong = (id, data) => request.put(`/clfeiyong/${id}`, data)
export const deleteClFeiyong = (id) => request.delete(`/clfeiyong/${id}`)

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

export async function exportClFeiyong(params) {
  const blob = await request.get('/clfeiyong/export', { params, responseType: 'blob' })
  saveBlob(blob, '车辆其他费用清单.xlsx')
}
