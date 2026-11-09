import request from './request'

export const listPlusOil = (params) => request.get('/plusoil', { params })
export const getPlusOilDicts = () => request.get('/plusoil/dicts')

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

export async function exportPlusOil(params) {
  const blob = await request.get('/plusoil/export', { params, responseType: 'blob' })
  saveBlob(blob, '加油记录.xlsx')
}
