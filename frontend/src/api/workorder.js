import request from './request'

// ==================== 字典 / 选料库存 ====================
export const getWorkOrderDicts = () => request.get('/workorder/dicts')
export const listWorkOrderStocks = (params) => request.get('/workorder/stocks', { params })

// ==================== 工单列表 / 提交 / 明细 ====================
export const listWorkOrders = (params) => request.get('/workorder/orders', { params })
export const submitWorkOrder = (data) => request.post('/workorder/orders/submit', data)
export const getOrderByNo = (workOrderNo) =>
  request.get('/workorder/orders/by-no', { params: { workOrderNo } })
export const getOrderByNo2 = (workOrderNo) =>
  request.get('/workorder/orders/by-no2', { params: { workOrderNo } })
export const getOrderDetails = (orderId) =>
  request.get(`/workorder/orders/${orderId}/details`)
export const deleteWorkOrder = (orderId) => request.delete(`/workorder/orders/${orderId}`)
// 工单详情抽屉:与 jcxt 的 /jcxt/gongdan-info 同上游、同返回结构,
// 但用 workorder:view 权限(领料用户不必有 jcxt:view)。
export const getExternalWorkOrder = (gongdanNo) =>
  request.get('/workorder/external/info', { params: { gongdanNo } })
export const getExternalImages = (flowId, gongdanNo) =>
  request.get('/workorder/external/images', {
    params: { flow_id: flowId, gongdanNo },
  })

// ==================== 附件 ====================
export const listAttachments = (params) => request.get('/workorder/attachments', { params })
export const uploadAttachment = (workorderid, file, onProgress) => {
  const formData = new FormData()
  formData.append('file', file)
  return request.post('/workorder/attachments', formData, {
    params: { workorderid },
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: onProgress,
  })
}
export const deleteAttachment = (id) => request.delete(`/workorder/attachments/${id}`)

// ==================== 导出 3 Sheet ====================
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

export async function exportWorkOrderStatistics(params) {
  const blob = await request.get('/workorder/export', { params, responseType: 'blob' })
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  saveBlob(blob, `领料统计_${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}.xlsx`)
}
