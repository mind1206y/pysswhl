import request from './request'

// ==================== 记录列表 ====================
export const listJiaban = (params) => request.get('/jiaban/records', { params })

// ==================== 加班人员 ====================
export const listRenyuan = (params) => request.get('/jiaban/renyuan', { params })
export const listRenyuanAll = () => request.get('/jiaban/renyuan-list')
export const getBmlbOptions = () => request.get('/jiaban/bmlb-options')
export const addRenyuan = (data) => request.post('/jiaban/renyuan/add', data)
export const updateRenyuan = (data) => request.post('/jiaban/renyuan/update', data)
export const deleteRenyuan = (id) => request.post('/jiaban/renyuan/delete', { id })

// ==================== 工单号带出 / 详情抽屉 ====================
// 外部工单详情与 jcxt/gongdan/workorder 同源(/jiaban/by-no + /jiaban/images),
// 仅为使用 jiaban:view 权限换路径,返回结构与 workorder 完全一致。
export const getJiabanGongdanInfo = (gongdanNo, nameid) =>
  request.get('/jiaban/gongdan-info', { params: { gongdanNo, nameid: nameid || undefined } })
export const getExternalWorkOrder = (gongdanNo) =>
  request.get('/jiaban/by-no', { params: { gongdanNo } })
export const getExternalImages = (flowId) =>
  request.get('/jiaban/images', { params: { flow_id: flowId } })

// ==================== 记录增删改 ====================
export const addJiaban = (data) => request.post('/jiaban/add', data)
export const updateJiaban = (data) => request.post('/jiaban/update', data)
export const deleteJiaban = (id) => request.post('/jiaban/delete', { id })

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

async function exportBlob(url, params, prefix) {
  const blob = await request.get(url, { params, responseType: 'blob' })
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  saveBlob(blob, `${prefix}_${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}`
    + `${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}.xlsx`)
}

// ==================== 4 个导出 ====================
export const exportByName = (params) => exportBlob('/jiaban/export', params, '加班记录_按姓名')
export const exportByAddress = (params) => exportBlob('/jiaban/export-by-address', params, '加班审批表')
export const exportSummary = (params) => exportBlob('/jiaban/export-summary', params, '加班工资汇总表')
export const exportForOvertime = (params) => exportBlob('/jiaban/export-for-overtime', params, '维抢修加班_导出')

// ==================== 附件 ====================
export const listAttachments = (params) => request.get('/jiaban/attachments', { params })
export const uploadAttachment = (year, month, file, onProgress) => {
  const fd = new FormData()
  fd.append('file', file)
  return request.post(`/jiaban/attachments/upload?year=${year}&month=${month}`, fd, {
    onUploadProgress: (e) => {
      if (onProgress && e.total) onProgress(Math.round((e.loaded / e.total) * 100))
    },
  })
}
export const deleteAttachment = (id) => request.post('/jiaban/attachments/delete', { id })
