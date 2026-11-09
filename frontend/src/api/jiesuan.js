import request from './request'

// 材料结算单查看(只读)
export const listJiesuanView = (params) => request.get('/jiesuan/details', { params })
