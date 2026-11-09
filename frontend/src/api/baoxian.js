import request from './request'

export const listBaoxian = (params) => request.get('/baoxian', { params })
export const getBaoxianDicts = () => request.get('/baoxian/dicts')
export const searchBaoxianVehicles = (q = '') =>
  request.get('/baoxian/vehicles', { params: { q } })
export const getBxcomList = () => request.get('/baoxian/bxcoms')
export const getBaoxian = (id) => request.get(`/baoxian/${id}`)
export const createBaoxian = (data) => request.post('/baoxian', data)
export const updateBaoxian = (id, data) => request.put(`/baoxian/${id}`, data)
export const deleteBaoxian = (id) => request.delete(`/baoxian/${id}`)

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

export async function downloadTemplate() {
  const blob = await request.get('/baoxian/template', { responseType: 'blob' })
  saveBlob(blob, '保险导入模板.xlsx')
}

export async function uploadBaoxian(file) {
  const fd = new FormData()
  fd.append('file', file)
  const res = await request.post('/baoxian/import', fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })
  return res
}

export async function exportBaoxian(params) {
  const blob = await request.get('/baoxian/export', { params, responseType: 'blob' })
  saveBlob(blob, `保险费用清单（${new Date().toLocaleDateString('zh-CN')}）.xlsx`)
}
