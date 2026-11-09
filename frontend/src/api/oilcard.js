import request from './request'

export const listOilCards = (params) => request.get('/oilcards', { params })
export const getOilCardDicts = () => request.get('/oilcards/dicts')
export const getOilCard = (id) => request.get(`/oilcards/${id}`)
export const createOilCard = (data) => request.post('/oilcards', data)
export const updateOilCard = (id, data) => request.put(`/oilcards/${id}`, data)
export const deleteOilCard = (id) => request.delete(`/oilcards/${id}`)

export const getMonthlyOilData = (id, year) =>
  request.get(`/oilcards/${id}/monthly-oil-data`, { params: { year } })
export const getOilMonthStat = (id, year) =>
  request.get(`/oilcards/${id}/oil-month-stat`, { params: { year } })

export const uploadOilCardExcel = (kind, formData) =>
  request.post(`/oilcards/upload/${kind}`, formData)
export const manualZero = () => request.post('/oilcards/manual-zero')

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

export async function downloadOilCardTemplate(type) {
  const blob = await request.get('/oilcards/template', { params: { type }, responseType: 'blob' })
  const names = { card: '油卡明细表模板.xlsx', yue: '余额记录模板.xlsx', xf: '消费明细模板.xlsx' }
  saveBlob(blob, names[type] || '模板.xlsx')
}

export async function exportOilCardBalance() {
  const blob = await request.get('/oilcards/export/balance', { responseType: 'blob' })
  saveBlob(blob, '油卡充值列表.xlsx')
}

export async function exportOilCardDiff(type, price) {
  const blob = await request.get('/oilcards/export/diff', {
    params: { type, price }, responseType: 'blob',
  })
  saveBlob(blob, '智能充值.xlsx')
}

export async function exportOilCardManual() {
  const blob = await request.get('/oilcards/export/manual', { responseType: 'blob' })
  saveBlob(blob, '油卡充值列表.xlsx')
}
