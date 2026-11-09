import request from './request'

export const listProjects = (params) => request.get('/projects', { params })
export const listProjectCategories = () => request.get('/projects/categories')
export const createProject = (data) => request.post('/projects', data)
export const updateProject = (id, data) => request.put(`/projects/${id}`, data)
export const deleteProject = (id) => request.delete(`/projects/${id}`)

// ===== 详情:进度 / 问题 / 附件 =====
export const listJindu = (gcglid) => request.get(`/projects/${gcglid}/jindu`)
export const addJindu = (gcglid, data) => request.post(`/projects/${gcglid}/jindu`, data)
export const updateJindu = (gcglid, id, jindu) => request.put(`/projects/${gcglid}/jindu/${id}`, { jindu })
export const deleteJindu = (gcglid, id) => request.delete(`/projects/${gcglid}/jindu/${id}`)

export const listJianguan = (gcglid) => request.get(`/projects/${gcglid}/jianguan`)
export const addJianguan = (gcglid, qingkuangshuoming) =>
  request.post(`/projects/${gcglid}/jianguan`, { qingkuangshuoming })
export const updateJianguan = (gcglid, id, qingkuangshuoming) =>
  request.put(`/projects/${gcglid}/jianguan/${id}`, { qingkuangshuoming })
export const resolveJianguan = (gcglid, id, isjiejue) =>
  request.put(`/projects/${gcglid}/jianguan/${id}/resolve`, { isjiejue })
export const deleteJianguan = (gcglid, id) => request.delete(`/projects/${gcglid}/jianguan/${id}`)

export const listFujian = (gcglid) => request.get(`/projects/${gcglid}/fujian`)
export const deleteFujian = (gcglid, id) => request.delete(`/projects/${gcglid}/fujian/${id}`)

// 下载:先拿短时效下载令牌,再拼直链(长期登录令牌不进 URL/访问日志)
export const createDownloadToken = (gcglid, id) =>
  request.post(`/projects/${gcglid}/fujian/${id}/download-token`)

// 上传地址(el-upload 用,token 通过 :headers 传)
export const fujianUploadUrl = (gcglid) => `/api/projects/${gcglid}/fujian`
