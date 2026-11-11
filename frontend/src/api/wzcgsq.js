import request from './request'

export const getWzcgsqDicts = () => request.get('/wzcgsq/dicts')
export const listWzcgsq = (params) => request.get('/wzcgsq', { params })
export const getWzcgsq = (id) => request.get(`/wzcgsq/${id}`)
export const getWzcgsqMx = (id) => request.get(`/wzcgsq/${id}/mx`)
export const getWzcgsqEdit = (id) => request.get(`/wzcgsq/${id}/edit`)
export const getWzcgsqPrint = (id) => request.get(`/wzcgsq/${id}/print`)
export const createWzcgsq = (data) => request.post('/wzcgsq', data)
export const updateWzcgsq = (id, data) => request.put(`/wzcgsq/${id}`, data)
export const deleteWzcgsq = (id) => request.delete(`/wzcgsq/${id}`)
export const uploadWzcgsqMx = (formData) => request.post('/wzcgsq/upload-mx', formData, {
  headers: { 'Content-Type': 'multipart/form-data' },
})

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

export async function downloadWzcgsqTemplate() {
  const blob = await request.get('/wzcgsq/template', { responseType: 'blob' })
  saveBlob(blob, '物资采购明细模板.xlsx')
}

export async function downloadWzcgsqSq(id, bumen = '') {
  const blob = await request.get(`/wzcgsq/${id}/download-sq`, { responseType: 'blob' })
  saveBlob(blob, `物资采购申请单（${bumen}）.xlsx`)
}

export async function downloadWzcgsqYs(id, bumen = '') {
  const blob = await request.get(`/wzcgsq/${id}/download-ys`, { responseType: 'blob' })
  saveBlob(blob, `物资采购验收单（${bumen}）.xlsx`)
}
