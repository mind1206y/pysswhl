import axios from 'axios'
import request from './request'

const B = '/overtime'

// ---- 上下文 / 字典
export const getOvertimeDicts = () => request.get(`${B}/dicts`)
export const getGongdan = (no) => request.get(`${B}/gongdan`, { params: { no } })

// ---- 我的加班
export const listMyRecords = (params) => request.get(`${B}/my-records`, { params })
export const savePersonalRecord = (data) => request.post(`${B}/personal-record`, data)
export const submitPersonal = (id) => request.post(`${B}/personal/records/${id}/submit`)
export const recallPersonal = (id) => request.post(`${B}/personal/records/${id}/recall`)
export const batchSubmitPersonal = (ids) => request.post(`${B}/personal/records/batch-submit`, { ids })
export const batchDeletePersonal = (ids) => request.post(`${B}/personal/records/batch-delete`, { ids })
export const deletePersonal = (id) => request.post(`${B}/personal/records/${id}/delete`)
export const savePersonalHeader = (data) => request.post(`${B}/personal/header`, data)
export const getPersonalDetail = (id) => request.get(`${B}/personal/records/${id}/detail`)
export const saveBatchRecords = (data) => request.post(`${B}/batch-records`, data)
export const listSubmittedRecords = (params) => request.get(`${B}/submitted-records`, { params })

// ---- 申请单
export const listApplies = (params) => request.get(`${B}/applies`, { params })
export const getApplyInfo = (id, recordType = 'apply') =>
  request.get(`${B}/applies/${id}`, { params: { record_type: recordType } })
export const createApplyFromPersonal = (data) => request.post(`${B}/applies/from-personal`, data)
export const saveApply = (data) => request.post(`${B}/applies`, data)
export const saveApplyHeader = (data) => request.post(`${B}/applies/header`, data)
export const addRecordsToApply = (id, detailIds) =>
  request.post(`${B}/applies/${id}/records`, { detailIds })
export const updateApplyDept = (id, deptId) => request.post(`${B}/applies/${id}/dept`, { deptId })
export const updateApplyRemark = (id, remark) => request.post(`${B}/applies/${id}/remark`, { remark })
export const deleteApply = (id) => request.post(`${B}/applies/${id}/delete`)

// ---- 时段明细
export const listEntries = (applyId, recordType = 'apply') =>
  request.get(`${B}/entries`, { params: { apply_id: applyId, record_type: recordType } })
export const saveEntry = (data) => request.post(`${B}/entries`, data)
export const deleteEntry = (id) => request.post(`${B}/entries/${id}/delete`)

// ---- 校验
export const checkDuplicate = (params) => request.get(`${B}/check-duplicate`, { params })
export const checkOverlap = (data) => request.post(`${B}/check-overlap`, data)
export const checkOverlaps = (items) => request.post(`${B}/check-overlaps`, { items })
export const checkMonthlyHours = (data) => request.post(`${B}/check-monthly-hours`, data)
export const checkMonthlyHoursBatch = (personnelIds, accountingMonth) =>
  request.post(`${B}/check-monthly-hours-batch`, { personnelIds, accountingMonth })

// ---- 审批
export const getApprovalSwitch = () => request.get(`${B}/approval-switch`)
export const setApprovalSwitch = (enabled) => request.post(`${B}/approval-switch`, { enabled })
export const listMyApprovals = (params) => request.get(`${B}/my-approvals`, { params })
export const submitForApproval = (id) => request.post(`${B}/approval/submit`, { id })
export const approveApply = (approvalId, approved, comment) =>
  request.post(`${B}/approval/approve`, { approvalId, approved, comment })
export const rejectApply = (approvalId, comment) =>
  request.post(`${B}/approval/reject`, { approvalId, comment })
export const resubmitApply = (id) => request.post(`${B}/approval/resubmit`, { id })

// ---- 核销 / 补休
export const batchVerify = (ids) => request.post(`${B}/verify/batch`, { ids })
export const unverifyApply = (id) => request.post(`${B}/verify/unverify`, { id })
export const revertToDraft = (id) => request.post(`${B}/verify/revert`, { id })
export const getCompBalance = (personnelId) =>
  request.get(`${B}/comp-leave/balance`, { params: { personnelId } })
export const listCompLeave = (personnelId) =>
  request.get(`${B}/comp-leave/list`, { params: { personnelId } })
export const saveCompLeave = (data) => request.post(`${B}/comp-leave/save`, data)
export const deleteCompLeave = (id) => request.post(`${B}/comp-leave/delete`, { id })

// ---- 汇总 / 打印
export const getSummary = (params) => request.get(`${B}/summary`, { params })
export const getSummaryDetail = (params) => request.get(`${B}/summary/detail`, { params })
export const getPrintData = (id) => request.get(`${B}/print-data`, { params: { id } })

// ---- 配置
export const listPersonnel = (params) => request.get(`${B}/personnel`, { params })
export const listActivePersonnel = (deptId) => request.get(`${B}/personnel/active`, { params: { dept_id: deptId } })
export const listSiblingPersonnel = () => request.get(`${B}/personnel/sibling`)
export const getMyPersonnel = () => request.get(`${B}/personnel/my`)
export const savePersonnel = (data) => request.post(`${B}/personnel/save`, data)
export const deletePersonnel = (id) => request.post(`${B}/personnel/delete`, { id })
export const restorePersonnel = (id) => request.post(`${B}/personnel/restore`, { id })
export const getDeptTree = () => request.get(`${B}/depts/tree`, { params: { full: true } })
export const getSysDeptList = () => request.get(`${B}/depts/sys-list`)
export const getTopSysDepts = () => request.get(`${B}/depts/top-sys`)
export const getMirrorChildren = (parentOtNodeId) =>
  request.get(`${B}/depts/mirror-children`, { params: { parentOtNodeId } })
export const saveDept = (data) => request.post(`${B}/depts/save`, data)
export const addMirrorDept = (data) => request.post(`${B}/depts/mirror`, data)
export const addMirrorRoot = (sysBumenId) => request.post(`${B}/depts/mirror-root`, { sysBumenId })
export const renameDept = (id, newName) => request.post(`${B}/depts/rename`, { id, newName })
export const toggleDept = (id) => request.post(`${B}/depts/toggle`, { id })
export const moveDept = (id, newParentId) => request.post(`${B}/depts/move`, { id, newParentId })
export const sortDept = (items) => request.post(`${B}/depts/sort`, { items })
export const listLevels = () => request.get(`${B}/levels`)
export const saveLevel = (data) => request.post(`${B}/levels/save`, data)
export const deleteLevel = (id) => request.post(`${B}/levels/delete`, { id })
export const listApprovers = (params) => request.get(`${B}/approvers`, { params })
export const saveApprover = (data) => request.post(`${B}/approvers/save`, data)
export const deleteApprover = (id) => request.post(`${B}/approvers/delete`, { id })

// ---- 文件下载 / 上传
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

function filenameFrom(res, fallback) {
  const cd = res.headers?.['content-disposition'] || ''
  const m = /filename\*=UTF-8''([^;]+)/i.exec(cd)
  return m ? decodeURIComponent(m[1]) : fallback
}

export async function exportApply(id) {
  const blob = await request.get(`${B}/export/apply`, { params: { id }, responseType: 'blob' })
  saveBlob(blob, '加班审批单.xlsx')
}

export async function exportRecords(params) {
  const blob = await request.get(`${B}/export/records`, { params, responseType: 'blob' })
  saveBlob(blob, '加班记录.xlsx')
}

export async function exportQx(params) {
  const blob = await request.get(`${B}/export/qx`, { params, responseType: 'blob' })
  saveBlob(blob, '维抢修加班审批表.xlsx')
}

export async function downloadTemplate(params) {
  const blob = await request.get(`${B}/import/template`, { params, responseType: 'blob' })
  saveBlob(blob, '加班明细批量导入模板.xlsx')
}

export async function uploadSummary(formData) {
  const res = await axios.post('/api/overtime/summary/upload', formData, {
    headers: { Authorization: `Bearer ${localStorage.getItem('token') || ''}` },
    responseType: 'blob',
  })
  saveBlob(res.data, filenameFrom(res, '加班汇总.xlsx'))
  return { matched: Number(res.headers['x-matched-count'] || 0), unmatched: Number(res.headers['x-unmatched-count'] || 0) }
}

export async function importPersonalExcel(file) {
  const fd = new FormData()
  fd.append('file', file)
  return request.post(`${B}/import/personal`, fd)
}

export async function importPersonnelExcel(file) {
  const fd = new FormData()
  fd.append('file', file)
  return request.post(`${B}/import/personnel`, fd)
}
