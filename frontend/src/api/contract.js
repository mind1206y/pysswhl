import axios from 'axios'
import request from './request'

// ===== 公共字典 =====
export const getContractDicts = () => request.get('/contracts/dicts')

// ===== 合同登记 =====
export const listContracts = (params) => request.get('/contracts', { params })
export const listRegisterYears = () => request.get('/contracts/years')
export const getDuixiangOptions = (query) =>
  request.get('/contracts/duixiang-options', { params: { query } })
export const getContract = (id) => request.get(`/contracts/${id}`)
export const createContract = (data) => request.post('/contracts', data)
export const updateContract = (id, data) => request.put(`/contracts/${id}`, data)
export const deleteContract = (id) => request.delete(`/contracts/${id}`)
export const lockContract = (id) => request.post(`/contracts/${id}/lock`)
export const unlockContract = (id) => request.post(`/contracts/${id}/unlock`)

// ===== 附件 =====
export function uploadContractAttachments(id, files) {
  const fd = new FormData()
  files.forEach((f) => fd.append('files', f))
  return request.post(`/contracts/${id}/attachments`, fd)
}
export const createAttachmentToken = (id) =>
  request.post(`/contracts/attachments/${id}/token`)
export const deleteAttachment = (id) => request.delete(`/contracts/attachments/${id}`)

// ===== 合同归集 =====
export const listCollect = (params) => request.get('/contracts/collect', { params })
export const listCollectYears = () => request.get('/contracts/collect/years')
export const listCollectSubmitters = (nd) =>
  request.get('/contracts/collect/submitters', { params: { nd } })
export const collectContract = (id) => request.post(`/contracts/${id}/collect`)
export const uncollectContract = (id) => request.post(`/contracts/${id}/uncollect`)
export const updateMemo = (id, bz) => request.put(`/contracts/${id}/memo`, { bz })

// ===== 导出 =====
async function downloadBlob(path, params, filename) {
  const query = Object.entries(params || {})
    .filter(([, v]) => v !== '' && v !== null && v !== undefined)
    .map(([k, v]) => `${k}=${encodeURIComponent(v)}`)
    .join('&')
  const resp = await axios.get(`/api${path}${query ? '?' + query : ''}`, {
    responseType: 'blob',
    headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
  })
  const url = URL.createObjectURL(resp.data)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export const exportContracts = (params) =>
  downloadBlob('/contracts/export', params, `合同明细表_${new Date().toISOString().slice(0, 10)}.xlsx`)

export const exportCollect = (params) =>
  downloadBlob('/contracts/collect/export', params, `合同归集明细_${new Date().toISOString().slice(0, 10)}.xlsx`)
