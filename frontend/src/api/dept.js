import request from './request'

export const listDepartments = () => request.get('/departments')
export const createDepartment = (data) => request.post('/departments', data)
export const updateDepartment = (id, data) => request.put(`/departments/${id}`, data)
export const deleteDepartment = (id) => request.delete(`/departments/${id}`)
