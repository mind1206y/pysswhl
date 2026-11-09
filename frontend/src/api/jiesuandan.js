import request from './request'

// ==================== 字典 / 初始化 ====================
export const getJiesuanDicts = () => request.get('/jiesuandan/dicts')
export const getJiesuanCreateInit = () => request.get('/jiesuandan/create-init')

// ==================== 结算单 ====================
export const listJiesuanOrders = (params) => request.get('/jiesuandan/orders', { params })
export const getJiesuanOrder = (id) => request.get(`/jiesuandan/orders/${id}`)
export const getJiesuanDetails = (id) => request.get(`/jiesuandan/orders/${id}/details`)
export const saveJiesuanOrder = (data) => request.post('/jiesuandan/orders/save', data)
export const deleteJiesuanOrder = (id) => request.delete(`/jiesuandan/orders/${id}`)

// ==================== 可结算领料明细 ====================
export const listJiesuanCandidates = (params) => request.get('/jiesuandan/candidates', { params })

// ==================== 结算明细 ====================
export const addJiesuanDetails = (orderId, Details) =>
  request.post(`/jiesuandan/orders/${orderId}/details`, { Details })
export const updateJiesuanDetail = (detailId, data) =>
  request.put(`/jiesuandan/details/${detailId}`, data)
export const deleteJiesuanDetail = (detailId) =>
  request.delete(`/jiesuandan/details/${detailId}`)

// ==================== 附件 ====================
export const listJiesuanAttachments = (orderId) =>
  request.get(`/jiesuandan/orders/${orderId}/attachments`)
export const uploadJiesuanAttachment = (orderId, file) => {
  const formData = new FormData()
  formData.append('files', file)
  return request.post(`/jiesuandan/orders/${orderId}/attachments`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
export const deleteJiesuanAttachment = (fileId) =>
  request.delete(`/jiesuandan/attachments/${fileId}`)

// ==================== 打印数据 ====================
export const getJiesuanPrintData = (id, params) =>
  request.get(`/jiesuandan/orders/${id}/print-data`, { params })

// ==================== 导出 ====================
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

function stamp() {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}`
    + `${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
}

export async function exportJiesuanDetail(id, danno) {
  const blob = await request.get(`/jiesuandan/orders/${id}/export`, { responseType: 'blob' })
  saveBlob(blob, `销售结算表_${danno || id}.xlsx`)
}

export async function exportJiesuanCg(id, type, sgbm, sgyy, danno) {
  const blob = await request.get(`/jiesuandan/orders/${id}/cg-excel`, {
    params: { type, sgbm, sgyy },
    responseType: 'blob',
  })
  const prefix = type === 2 ? '物资采购验收单' : '物资采购申请单'
  saveBlob(blob, `${prefix}_${danno || id}_${stamp()}.xlsx`)
}
