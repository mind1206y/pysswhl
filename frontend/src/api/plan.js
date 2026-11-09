import request from './request'

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

async function download(url, params, filename) {
  const blob = await request.get(url, { params, responseType: 'blob' })
  saveBlob(blob, filename)
}

async function upload(url, file) {
  const form = new FormData()
  form.append('file', file)
  return request.post(url, form, { headers: { 'Content-Type': 'multipart/form-data' } })
}

// ==================== 正式计划 ====================
export const getPlanDicts = () => request.get('/plan/dicts')
export const listOfficial = (params) => request.get('/plan/list', { params })
export const followPlans = (ids) => request.post('/plan/follow', { ids })
export const unfollowPlans = (ids) => request.post('/plan/unfollow', { ids })
export const getProgress = (gzid) => request.get(`/plan/progress/${gzid}`)

export const addProgress = (formData) =>
  request.post('/plan/progress', formData, { headers: { 'Content-Type': 'multipart/form-data' } })

export const updatePlanRemark = (data) => request.post('/plan/remark', data)
export const updatePlanZgy = (data) => request.post('/plan/zgy', data)
export const togglePlanKhbj = (id) => request.post('/plan/khbj', { id })
export const savePlanZbj = (data) => request.post('/plan/zbj', data)
export const copyPlanToTodo = (ids, target = '') =>
  request.post('/plan/copy-to-todo', { ids, target })
export const getPlanCalendar = (params) => request.get('/plan/calendar', { params })
export const exportOfficial = (params) => download('/plan/export', params, '正式计划.xlsx')
export const exportProgress = (params) => download('/plan/export-progress', params, '年度进度明细.xlsx')

export const planPhotoUrl = (picId) => `/api/plan/photo/${picId}`

// ==================== 实施单表 ====================
export const getTodoDicts = () => request.get('/jhssdb/dicts')
export const listTodo = (params) => request.get('/jhssdb/list', { params })
export const getTodoItem = (id) => request.get(`/jhssdb/item/${id}`)
export const createTodo = (data) => request.post('/jhssdb/create', data)
export const updateTodo = (id, data) => request.post(`/jhssdb/update/${id}`, data)
export const deleteTodo = (ids) => request.post('/jhssdb/delete', { ids })
export const changeTodoStatus = (data) => request.post('/jhssdb/status', data)
export const batchTodoZb = (ids, bumid) => request.post('/jhssdb/batch/zb', { ids, bumid })
export const batchTodoJhlb = (ids, value) => request.post('/jhssdb/batch/jhlb', { ids, value })
export const batchTodoLeibie = (ids, value) => request.post('/jhssdb/batch/leibie', { ids, value })
export const getTodoLogs = (id) => request.get(`/jhssdb/logs/${id}`)
export const sendTodoSms = (data) => request.post('/jhssdb/sms', data)
export const exportTodo = (params) => download('/jhssdb/export', params, '售水事业部计划.xlsx')
export const exportTodoPage = (ids, lb = '') =>
  download('/jhssdb/export-page', { ids: ids.join(','), lb }, '当前页计划.xlsx')

// ==================== 实施汇总 ====================
export const getSummaryDicts = () => request.get('/jhsshz/dicts')
export const listSummary = (params) => request.get('/jhsshz/list', { params })
export const getSummaryItem = (id) => request.get(`/jhsshz/item/${id}`)
export const createSummary = (data) => request.post('/jhsshz/create', data)
export const updateSummary = (id, data) => request.post(`/jhsshz/update/${id}`, data)
export const deleteSummary = (ids) => request.post('/jhsshz/delete', { ids })
export const changeSummaryStatus = (data) => request.post('/jhsshz/status', data)
export const batchSummaryLeibie = (ids, value) => request.post('/jhsshz/batch/leibie', { ids, value })
export const batchSummaryZb = (ids, bumid) => request.post('/jhsshz/batch/zb', { ids, bumid })
export const batchSummaryJhlb = (ids, value) => request.post('/jhsshz/batch/jhlb', { ids, value })
export const checkRenumber = () => request.get('/jhsshz/renumber/check')
export const renumber = (ids, skipBenbu) => request.post('/jhsshz/renumber', { ids, skipBenbu })
export const copyToOfficial = (nd, lb) => request.post('/jhsshz/copy-to-official', { nd, lb })
export const getPlanLocks = () => request.get('/jhsshz/locks')
export const setPlanLock = (key, value) => request.post('/jhsshz/locks', { key, value })
export const getSummaryLogs = (id) => request.get(`/jhsshz/logs/${id}`)
export const downloadSummaryTemplate = () => download('/jhsshz/template', {}, '计划.xlsx')
export const importSummary = (file) => upload('/jhsshz/import', file)
export const exportSummary = (params) => download('/jhsshz/export', params, '售水事业部计划.xlsx')
export const exportSummaryPage = (ids, lb = '') =>
  download('/jhsshz/export-page', { ids: ids.join(','), lb }, '当前页计划.xlsx')

// ==================== 营业所发起 ====================
export const getApplyDicts = () => request.get('/jhyyfaqi/dicts')
export const listApply = (params) => request.get('/jhyyfaqi/list', { params })
export const listReported = (params) => request.get('/jhyyfaqi/reported', { params })
export const getApplyItem = (id) => request.get(`/jhyyfaqi/item/${id}`)
export const createApply = (data) => request.post('/jhyyfaqi/create', data)
export const updateApply = (id, data) => request.post(`/jhyyfaqi/update/${id}`, data)
export const deleteApply = (ids) => request.post('/jhyyfaqi/delete', { ids })
export const submitApply = (ids, iftel = false) => request.post('/jhyyfaqi/submit', { ids, iftel })
export const getApplyDetail = (id, ul = 0) => request.get(`/jhyyfaqi/detail/${id}`, { params: { ul } })
export const downloadApplyTemplate = () => download('/jhyyfaqi/template', {}, '更新改造计划.xlsx')
export const importApply = (file) => upload('/jhyyfaqi/import', file)
export const exportApply = (params) => download('/jhyyfaqi/export', params, '营业所计划.xlsx')
export const exportReported = (params) => download('/jhyyfaqi/export-reported', params, '售水填报记录.xlsx')
