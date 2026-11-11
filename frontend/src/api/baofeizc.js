import request from './request'

export const getBaofeizcDicts = () => request.get('/baofeizc/dicts')
export const listBaofeizc = (params) => request.get('/baofeizc', { params })
export const getBaofeizc = (id) => request.get(`/baofeizc/${id}`)
export const createBaofeizc = (data) => request.post('/baofeizc', data)
export const updateBaofeizc = (id, data) => request.put(`/baofeizc/${id}`, data)
export const deleteBaofeizc = (id) => request.delete(`/baofeizc/${id}`)
export const listBaofeizcMx = (id) => request.get(`/baofeizc/${id}/mx`)
export const listBaofeizcCandidates = (params) => request.get('/baofeizc/candidates', { params })
export const addBaofeizcMx = (data) => request.post('/baofeizc/mx/add', data)
export const deleteBaofeizcMx = (data) => request.post('/baofeizc/mx/delete', data)
export const uploadBaofeizcImage = (formData) => request.post('/baofeizc/upload-image', formData, {
  headers: { 'Content-Type': 'multipart/form-data' },
})
export const deleteBaofeizcImage = (dizhi) => request.post('/baofeizc/delete-image', { dizhi })

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

export async function exportBaofeizc(id) {
  const blob = await request.get(`/baofeizc/export/${id}`, { responseType: 'blob' })
  saveBlob(blob, `清理报告（${id}）.xlsx`)
}
