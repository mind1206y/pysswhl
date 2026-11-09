import request from './request'

// ==================== 材料库存 ====================
export const listStocks = (params) => request.get('/materials', { params })
export const getMaterialDicts = () => request.get('/materials/dicts')
export const getStockWarning = () => request.get('/materials/warning')
export const saveMaterial = (data) => request.post('/materials', data)
// 注意:后端挂在 /api/materials 前缀下,新增/详情/删除分别是 POST ''、GET /{id}、DELETE /{id}
export const getMaterial = (id) => request.get(`/materials/${id}`)
export const deleteMaterial = (id) => request.delete(`/materials/${id}`)

// ==================== 入库 / 调整 / 盘点 ====================
export const saveInStock = (data) => request.post('/materials/in-stock', data)
export const deleteInStock = (id) => request.delete(`/materials/in-stock/${id}`)
export const adjustStock = (data) => request.post('/materials/adjust', data)
export const submitStockCheck = (list) =>
  request.post('/materials/stock-check', { list })

// ==================== 进出库记录 ====================
export const listInOut = (params) => request.get('/materials/in-out', { params })

// ==================== 图片 ====================
export const getMaterialImages = (materialId) =>
  request.get('/materials/images', { params: { id: materialId } })
export const uploadMaterialImages = (materialId, files) => {
  const formData = new FormData()
  files.forEach((f) => formData.append('files', f))
  return request.post('/materials/images', formData, {
    params: { materialId },
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
export const deleteMaterialImage = (id) => request.delete(`/materials/images/${id}`)

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

export async function exportStockCheck(dakoujing) {
  const blob = await request.get('/materials/export-stock-check', {
    params: dakoujing ? { dakoujing: 'on' } : {},
    responseType: 'blob',
  })
  saveBlob(blob, '材料盘点表.xlsx')
}

export async function exportInOutRecords(params) {
  const blob = await request.get('/materials/export-in-out', {
    params,
    responseType: 'blob',
  })
  saveBlob(blob, '进出库记录.xlsx')
}
