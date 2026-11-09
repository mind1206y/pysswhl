import request from './request'

// ==================== 字典 / 材料下拉 ====================
export const getLingliaoDicts = () => request.get('/lingliao/dicts')
export const listLingliaoMaterials = () => request.get('/lingliao/materials')

// ==================== 列表 / 明细 / 编辑回显 ====================
export const listLingliaoOrders = (params) => request.get('/lingliao/orders', { params })
export const getLingliaoOrder = (id) => request.get(`/lingliao/orders/${id}`)
export const getLingliaoDetails = (id) => request.get(`/lingliao/orders/${id}/details`)

// ==================== 保存 / 流程动作 ====================
export const saveLingliaoOrder = (data) => request.post('/lingliao/orders/save', data)
export const submitLingliaoOrder = (id) => request.post(`/lingliao/orders/${id}/submit`)
export const auditLingliaoOrder = (id) => request.post(`/lingliao/orders/${id}/audit`)
export const reverseAuditLingliaoOrder = (id) =>
  request.post(`/lingliao/orders/${id}/reverse-audit`)
export const rejectLingliaoOrder = (id) => request.post(`/lingliao/orders/${id}/reject`)
export const cancelLingliaoOrder = (id) => request.post(`/lingliao/orders/${id}/cancel`)
export const deleteLingliaoOrder = (id) => request.delete(`/lingliao/orders/${id}`)
export const updateLingliaoRenum = (orderId, detailId, renum) =>
  request.post(`/lingliao/orders/${orderId}/details/${detailId}/renum`, { renum })

// ==================== 附件 ====================
export const listLingliaoFiles = (orderId) => request.get(`/lingliao/orders/${orderId}/files`)
export const uploadLingliaoFile = (orderId, file) => {
  const formData = new FormData()
  formData.append('file', file)
  return request.post(`/lingliao/orders/${orderId}/files`, formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
export const uploadLingliaoTempFile = (file) => {
  const formData = new FormData()
  formData.append('file', file)
  return request.post('/lingliao/files/temp', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
export const deleteLingliaoFile = (fileId) => request.delete(`/lingliao/files/${fileId}`)

// ==================== 导出材料需求单 ====================
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

export async function exportLingliaoOrder(id, danno) {
  const blob = await request.get(`/lingliao/orders/${id}/export`, { responseType: 'blob' })
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  saveBlob(
    blob,
    `材料需求单_${danno || id}_${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}`
      + `${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}.xlsx`,
  )
}
