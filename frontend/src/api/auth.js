import request from './request'

export const login = (data) => request.post('/auth/login', data)
export const getMe = () => request.get('/auth/me')
export const changePassword = (data) => request.put('/auth/password', data)
