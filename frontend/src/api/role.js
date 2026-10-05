import request from './request'

export const listRoles = () => request.get('/roles/all')
export const listPermissions = () => request.get('/roles/permissions')
export const createRole = (data) => request.post('/roles', data)
export const updateRole = (id, data) => request.put(`/roles/${id}`, data)
export const deleteRole = (id) => request.delete(`/roles/${id}`)
export const setRolePermissions = (id, permissionIds) =>
  request.put(`/roles/${id}/permissions`, { permission_ids: permissionIds })
