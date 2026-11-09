import request from './request'

export const listIps = (params) => request.get('/ipadress', { params })
export const getIpDicts = () => request.get('/ipadress/dicts')
export const createIpNetwork = (data) => request.post('/ipadress/networks', data)
export const deleteIpNetwork = (netname) =>
  request.delete('/ipadress/networks', { params: { netname } })
export const claimIp = (id, data) => request.post(`/ipadress/${id}/claim`, data)
export const recycleIp = (id) => request.post(`/ipadress/${id}/recycle`)

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

export async function exportIps(params) {
  const blob = await request.get('/ipadress/export', { params, responseType: 'blob' })
  saveBlob(blob, 'IP地址信息表.xlsx')
}
