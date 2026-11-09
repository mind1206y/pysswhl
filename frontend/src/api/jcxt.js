import request from './request'

// ==================== 稽查系统 jcxt ====================
export const listJcxx = (params) => request.get('/jcxt', { params })
export const getJcxxDicts = () => request.get('/jcxt/dicts')
export const getJcxxDetail = (id) => request.get(`/jcxt/detail/${id}`)
export const addJcxx = (data) => request.post('/jcxt', data)
export const updateJcxx = (id, data) => request.put(`/jcxt/${id}`, data)
export const deleteJcxx = (id) => request.delete(`/jcxt/${id}`)

export const submitJcxxOne = (id) => request.post(`/jcxt/submit/${id}`)
export const submitJcxxRows = (ids) => request.post('/jcxt/submit-rows', { ids })
export const recallJcxxOne = (id) => request.post(`/jcxt/recall/${id}`)
export const recallJcxxRows = (ids) => request.post('/jcxt/recall-rows', { ids })

export const linkJcdan = (data) => request.post('/jcxt/link-jcdan', data)
export const unlinkJcdan = (data) => request.post('/jcxt/unlink-jcdan', data)

export const suggestWeizhangren = (query) =>
  request.get('/jcxt/weizhangren', { params: { query } })
export const getGongdanInfo = (gongdanhao) =>
  request.get('/jcxt/gongdan-info', { params: { gongdanhao } })
export const getGongdanImages = (flowId) =>
  request.get('/jcxt/gongdan-images', { params: { flow_id: flowId } })

export const getPie = (params) => request.get('/jcxt/pie', { params })

// 图片:先取短令牌再挂 <img> 的 query(登录令牌不进 URL)
export const getJcImageToken = (imageId) =>
  request.post(`/jcxt/images/${imageId}/token`)
export const uploadJcImage = (rowId, file) => {
  const form = new FormData()
  form.append('file', file)
  return request.post(`/jcxt/${rowId}/images`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
export const deleteJcImage = (imageId) => request.delete(`/jcxt/images/${imageId}`)

// 自选导出列
export const getExportColumns = () => request.get('/jcxt/export-columns')
export const selectExportColumn = (colname) =>
  request.post(`/jcxt/export-columns/${colname}`)
export const deleteExportColumn = (colname) =>
  request.delete(`/jcxt/export-columns/${colname}`)
export const selectAllExportColumns = (cid, ck) =>
  request.post('/jcxt/export-columns-all', { cid, ck })

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

export async function exportJcAll(params) {
  const blob = await request.get('/jcxt/export/all', { params, responseType: 'blob' })
  saveBlob(blob, '稽查信息明细表.xlsx')
}
export async function exportJcMe(params) {
  const blob = await request.get('/jcxt/export/me', { params, responseType: 'blob' })
  saveBlob(blob, '稽查信息.xlsx')
}
export async function exportJcReward(rqend) {
  const blob = await request.get('/jcxt/export/reward', {
    params: { rqend }, responseType: 'blob',
  })
  saveBlob(blob, '同安奖励名单.xlsx')
}
export async function downloadJcTemplate() {
  const blob = await request.get('/jcxt/template', { responseType: 'blob' })
  saveBlob(blob, '稽查报表.xlsx')
}

// 导入稽查报表
export function importJcReport(file) {
  const form = new FormData()
  form.append('file', file)
  return request.post('/jcxt/import', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

// ==================== 审批稽查 spjicha ====================
export const listSpjicha = (params) => request.get('/spjicha', { params })
export const getSpjichaDicts = () => request.get('/spjicha/dicts')
export const approveSpOne = (id) => request.post(`/spjicha/approve/${id}`)
export const approveSpRows = (ids) => request.post('/spjicha/approve-rows', { ids })
export const cancelSpOne = (id) => request.post(`/spjicha/cancel/${id}`)
export const cancelSpRows = (ids) => request.post('/spjicha/cancel-rows', { ids })
export const computReward = (date_str) =>
  request.post('/spjicha/comput', null, { params: { date_str } })
export const comptaTongan = (date_str) =>
  request.post('/spjicha/compta', null, { params: { date_str } })
export async function exportSpReward(date_str) {
  const blob = await request.get('/spjicha/export/reward', {
    params: { date_str }, responseType: 'blob',
  })
  saveBlob(blob, '稽查奖励报表.xlsx')
}
export async function heduiWorkOrder(file) {
  const form = new FormData()
  form.append('file', file)
  const blob = await request.post('/spjicha/hedui', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    responseType: 'blob',
  })
  saveBlob(blob, '工单核对结果文件.xlsx')
}

// ==================== 稽查单 jcdan ====================
export const listJcdan = (params) => request.get('/jcdan', { params })
export const getJcdanDicts = () => request.get('/jcdan/dicts')
export const listJcdanForJcxx = (params) => request.get('/jcdan/for-jcxx', { params })
export const getJcdanPz = (id) => request.get(`/jcdan/${id}/pz`)
export const addJcdan = (data) => request.post('/jcdan', data)
export const updateJcdan = (id, data) => request.put(`/jcdan/${id}`, data)
export const deleteJcdan = (id) => request.delete(`/jcdan/${id}`)

// ==================== 稽查奖励 jcjl ====================
export const listJcjl = (params) => request.get('/jcjl', { params })
export const getJcjlDicts = () => request.get('/jcjl/dicts')
export const getJcjlNames = (id) => request.get(`/jcjl/names/${id}`)
export const getJcjlRemain = (id) => request.get(`/jcjl/remain/${id}`)
export const assignJcjl = (data) => request.post('/jcjl/assign', data)
export const listJcjlFps = (id) => request.get(`/jcjl/${id}/fps`)
export const deleteJcjlFp = (id) => request.delete(`/jcjl/fps/${id}`)
