import request from './request'

// blob 下载:中文文件名由前端固定,规避各浏览器对 filename* 的解析差异
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

// ===== 公共字典 =====
export const getCdDicts = () => request.get('/cd/dicts')

// ===== 传导完好率 /cdwhl =====
export const listCdWhl = (params) => request.get('/cdwhl', { params })
export const generateCdWhl = (rq) => request.post('/cdwhl/generate', { rq })
export const getCdWhlRemark = (id) => request.get('/cdwhl/remark', { params: { id } })
export const saveCdWhlRemark = (data) => request.post('/cdwhl/remark', data)
export const setCdLock = (is_locked) => request.post('/cdwhl/lock', { is_locked })
export async function exportCdWhl(params) {
  const blob = await request.get('/cdwhl/export', { params, responseType: 'blob' })
  saveBlob(blob, '传导设备完好率汇总表.xlsx')
}

// ===== 传导故障 /cdgz =====
export const listCdGz = (params) => request.get('/cdgz', { params })
export const getCdGz = (id) => request.get(`/cdgz/${id}`)
export const addCdGz = (data) => request.post('/cdgz', data)
export const updateCdGz = (id, data) => request.put(`/cdgz/${id}`, data)
export const deleteCdGz = (id) => request.delete(`/cdgz/${id}`)

// ===== 传导大修 /cddaxiu =====
export const listCdDaxiu = (params) => request.get('/cddaxiu', { params })
export const getCdDaxiu = (id) => request.get(`/cddaxiu/${id}`)
export const addCdDaxiu = (data) => request.post('/cddaxiu', data)
export const updateCdDaxiu = (id, data) => request.put(`/cddaxiu/${id}`, data)
export const deleteCdDaxiu = (id) => request.delete(`/cddaxiu/${id}`)
export async function exportCdDaxiu(params) {
  const blob = await request.get('/cddaxiu/export', { params, responseType: 'blob' })
  saveBlob(blob, '传导设备大修明细.xlsx')
}

// ===== 传导变动表 /cdbd =====
export const listCdBd = (params) => request.get('/cdbd', { params })
export const getCdBd = (id) => request.get(`/cdbd/${id}`)
export const addCdBd = (data) => request.post('/cdbd', data)
export const updateCdBd = (id, data) => request.put(`/cdbd/${id}`, data)
export const deleteCdBd = (id) => request.delete(`/cdbd/${id}`)
export async function downloadCdBdTemplate() {
  const blob = await request.get('/cdbd/template', { responseType: 'blob' })
  saveBlob(blob, '传导设备变动表.xlsx')
}
export const uploadCdBdTemplate = (formData) => request.post('/cdbd/upload', formData, {
  headers: { 'Content-Type': 'multipart/form-data' },
})
