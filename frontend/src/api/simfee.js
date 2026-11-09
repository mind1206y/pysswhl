import request from './request'

export const listSimFees = (params) => request.get('/simfees', { params })
export const getSimFeeDicts = () => request.get('/simfees/dicts')
export const getSimFeeMonths = (year) => request.get('/simfees/months', { params: { year } })

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

export async function exportSimFees(params) {
  const blob = await request.get('/simfees/export', {
    params,
    responseType: 'blob',
    timeout: 120000,
  })
  saveBlob(blob, `费用明细_${params.year}_${params.month}.xlsx`)
}

export async function exportEmptyYongtu(year) {
  const blob = await request.get('/simfees/export-empty', {
    params: { year },
    responseType: 'blob',
    timeout: 120000,
  })
  saveBlob(blob, `费用明细_年度${year}_yongtu空.xlsx`)
}
