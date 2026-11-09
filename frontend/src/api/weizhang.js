import request from './request'

export const listWeizhang = (params) => request.get('/weizhang', { params })
export const getWeizhangDicts = () => request.get('/weizhang/dicts')
export const searchWeizhangVehicles = (q = '') =>
  request.get('/weizhang/vehicles', { params: { q } })
export const searchWeizhangContents = (q = '') =>
  request.get('/weizhang/wz-contents', { params: { q } })
export const getLatestWzDetail = (wz) =>
  request.get('/weizhang/latest-wz', { params: { wz } })
export const getWeizhangDriver = (chehao) =>
  request.get('/weizhang/driver', { params: { chehao } })
export const getWeizhang = (id) => request.get(`/weizhang/${id}`)
export const createWeizhang = (data) => request.post('/weizhang', data)
export const updateWeizhang = (id, data) => request.put(`/weizhang/${id}`, data)
export const deleteWeizhang = (id) => request.delete(`/weizhang/${id}`)

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

export async function exportWeizhang(params) {
  const blob = await request.get('/weizhang/export', { params, responseType: 'blob' })
  saveBlob(blob, '车辆违章信息表.xlsx')
}
