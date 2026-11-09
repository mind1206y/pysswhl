import request from './request'

export const listSimCards = (params) => request.get('/simcard', { params })
export const getSimCardDicts = () => request.get('/simcard/dicts')
export const getSimCardHistory = (id) => request.get(`/simcard/${id}/history`)
export const getSimCardFees = (id, year) =>
  request.get(`/simcard/${id}/fees`, { params: { year } })
export const createSimCard = (data) => request.post('/simcard', data)
export const updateSimCard = (id, data) => request.put(`/simcard/${id}`, data)
export const deleteSimCard = (id) => request.delete(`/simcard/${id}`)
export const deleteSimTaocan = (value) =>
  request.delete('/simcard/taocan', { params: { value } })

export async function uploadSimTemplate(file, defaultBmid) {
  const fd = new FormData()
  fd.append('file', file)
  if (defaultBmid) fd.append('default_bmid', defaultBmid)
  return request.post('/simcard/import', fd, { timeout: 120000 })
}

export async function uploadStatusFile(file) {
  const fd = new FormData()
  fd.append('file', file)
  return request.post('/simcard/status-import', fd, { timeout: 120000 })
}

export async function uploadFeeFile({ file, bmid, year, month, fileType }) {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('bmid', bmid)
  fd.append('year', year)
  fd.append('month', month)
  fd.append('file_type', fileType)
  return request.post('/simcard/fees/upload', fd, { timeout: 120000 })
}

export async function uploadReconcile(file) {
  const fd = new FormData()
  fd.append('file', file)
  const blob = await request.post('/simcard/reconcile', fd, {
    timeout: 120000,
    responseType: 'blob',
  })
  saveBlob(blob, 'sim卡核对结果文件.xlsx')
}

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

async function download(url, filename) {
  const blob = await request.get(url, { responseType: 'blob', timeout: 120000 })
  saveBlob(blob, filename)
}

export const downloadSimTemplate = () => download('/simcard/template/sim', 'SIM卡模板文件.xlsx')
export const downloadFeeTemplate = () => download('/simcard/template/fee', '话费清单模板.xlsx')
export const downloadStatusTemplate = () =>
  download('/simcard/template/status', '批量状态更改模板.xlsx')

export async function exportSimCards(params) {
  const blob = await request.get('/simcard/export', {
    params,
    responseType: 'blob',
    timeout: 120000,
  })
  saveBlob(blob, 'SIM卡列表.xlsx')
}
