import request from './request'

export const listUsers = (params) => request.get('/users', { params })
export const createUser = (data) => request.post('/users', data)
export const updateUser = (id, data) => request.put(`/users/${id}`, data)
export const deleteUser = (id) => request.delete(`/users/${id}`)
export const setUserStatus = (id, isActive) =>
  request.put(`/users/${id}/status`, { is_active: isActive })
export const resetUserPassword = (id) => request.put(`/users/${id}/password`)
export const setUserRoles = (id, roleIds) =>
  request.put(`/users/${id}/roles`, { role_ids: roleIds })
