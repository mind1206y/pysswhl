import request from './request'

// ==================== 初始化字典 ====================
export const getGongdanDicts = () => request.get('/gongdan/dicts')
export const getGongdanDepartments = () => request.get('/gongdan/departments')
export const getGongdanCount = () => request.get('/gongdan/count')

// ==================== 列表 / 导出 ====================
export const listGongdan = (params) => request.get('/gongdan/list', { params })

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

export async function exportGongdan(params) {
  const blob = await request.get('/gongdan/export', { params, responseType: 'blob' })
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  saveBlob(blob, `工单材料数据_${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}`
    + `${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}.xlsx`)
}

// ==================== 下拉字典 ====================
export const searchNeirong = (q) => request.get('/gongdan/neirong', { params: { q } })
export const deleteNeirong = (value) => request.post('/gongdan/neirong/delete', { value })
export const searchCaizhi = (q) => request.get('/gongdan/caizhi', { params: { q } })
export const deleteCaizhi = (value) => request.post('/gongdan/caizhi/delete', { value })

// ==================== 抢修班组名单 ====================
export const listQiangxiu = (search) => request.get('/gongdan/qiangxiu', { params: { search } })
export const addQiangxiu = (name) => request.post('/gongdan/qiangxiu/add', { name })
export const editQiangxiu = (id, name) => request.post('/gongdan/qiangxiu/edit', { id, name })
export const deleteQiangxiu = (id) => request.post('/gongdan/qiangxiu/delete', { id })

// ==================== 工单号带出 / 领料明细 / 详情抽屉 ====================
export const getGongdanInfo = (gongdanhao) =>
  request.get('/gongdan/gongdan-info', { params: { gongdanhao } })
export const getOrderDetails = (gdId) =>
  request.get('/gongdan/order-details', { params: { gdId } })
// 工单详情抽屉:信息获取照抄 workorder 的 /workorder/external/info + /external/images,
// 同一上游、同一返回结构(success/message/data、images 固定 3 槽位);
// 这里换 /gongdan/* 路径只为使用 gongdan:view 权限(录入用户不必有 workorder:view)。
export const getExternalWorkOrder = (gongdanNo) =>
  request.get('/gongdan/by-no', { params: { gongdanNo } })
export const getExternalImages = (flowId, gongdanNo) =>
  request.get('/gongdan/images', { params: { flow_id: flowId, gongdanNo } })

// ==================== 增删改 ====================
export const addGongdan = (data) => request.post('/gongdan/add', data)
export const updateGongdan = (data) => request.post('/gongdan/update', data)
export const deleteGongdan = (id) => request.post('/gongdan/del', { id })
