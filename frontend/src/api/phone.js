import request from './request'

export const listPhones = (params) => request.get('/phones', { params })
export const getPhoneDicts = () => request.get('/phones/dicts')
export const getPhoneYears = () => request.get('/phones/years')
export const getPhone = (id) => request.get(`/phones/${id}`)

export const batchAddPhones = (data) => request.post('/phones/batch-add', data)
export const batchUpdateDept = (data) => request.post('/phones/batch-dept', data)
export const batchUpdateStatus = (data) => request.post('/phones/batch-status', data)
export const batchUpdateLiyou = (data) => request.post('/phones/batch-liyou', data)
export const batchDeletePhones = (data) => request.post('/phones/batch-delete', data)
export const scrapConfirm = (id) => request.post(`/phones/${id}/scrap-confirm`)

export const updatePhoneInfo = (id, data) => request.put(`/phones/${id}/info`, data)
export const savePhoneRemark = (id, remark) => request.put(`/phones/${id}/remark`, { remark })
export const getPhoneHistory = (id) => request.get(`/phones/${id}/history`)
export const getPhonePrintData = (id) => request.get(`/phones/${id}/print-data`)

export const lookupPhones = (q) => request.get('/phones/lookup', { params: { q } })
export const lookupPhoneDetail = (number) =>
  request.get('/phones/lookup-detail', { params: { number } })

export const getPhoneAttachments = (id) => request.get(`/phones/${id}/attachments`)
export const uploadPhoneAttachment = (id, formData) =>
  request.post(`/phones/${id}/attachments`, formData)
export const deletePhoneAttachment = (id) => request.delete(`/phones/attachments/${id}`)
export const getAttachmentToken = (id) => request.post(`/phones/attachments/${id}/token`)

export const getHuishouList = (params) => request.get('/phones/huishou', { params })
export const createHuishou = (data) => request.post('/phones/huishou', data)
export const deleteHuishou = (id) => request.delete(`/phones/huishou/${id}`)

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

export async function exportPhones(params) {
  const blob = await request.get('/phones/export', { params, responseType: 'blob' })
  saveBlob(blob, '基础信息导出.xlsx')
}
