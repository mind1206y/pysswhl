import request from './request'

export const getGdzcDicts = () => request.get('/gdzc/dicts')
export const getGdzcQyYears = (nd) => request.get('/gdzc/qy-years', { params: { nd } })
export const listGdzc = (params) => request.get('/gdzc', { params })
export const saveGdzcRemark = (data) => request.post('/gdzc/remark', data)
export const checkGdzc = (data) => request.post('/gdzc/check', data)
export const getBaofeiDetail = (id) => request.get(`/gdzc/baofei/${id}`)

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

export async function exportGdzcDetail(params) {
  const blob = await request.get('/gdzc/export', { params, responseType: 'blob' })
  saveBlob(blob, '固定资产明细表.xlsx')
}

export async function exportGdzcPandian(params, nd) {
  const blob = await request.get('/gdzc/pandian-export', { params, responseType: 'blob' })
  saveBlob(blob, `${nd || ''}年度固定资产盘点表.xlsx`)
}

export const importGdzc = (formData) => request.post('/gdzc/import', formData, {
  headers: { 'Content-Type': 'multipart/form-data' },
})
