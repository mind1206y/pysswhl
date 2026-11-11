import request from './request'

export const listChelfytj = (params) => request.get('/chelfytj', { params })
export const getChelfytjDicts = () => request.get('/chelfytj/dicts')

export async function exportChelfytj(params) {
  const blob = await request.get('/chelfytj/export', { params, responseType: 'blob' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `费用统计_${new Date().toISOString().slice(0, 10)}.xlsx`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
