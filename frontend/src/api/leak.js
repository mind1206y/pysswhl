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

export const listLeaks = (params) => request.get('/leak', { params })
export const getLeakMonths = () => request.get('/leak/months')
export const getLeakDetectComs = () => request.get('/leak/detect-coms')
export const getLeakFormComs = () => request.get('/leak/form-coms')
export const getLeakDetail = (id) => request.get(`/leak/${id}`)
export const createLeak = (formData) =>
  request.post('/leak', formData, { timeout: 600000 })
export const updateLeak = (id, formData) =>
  request.put(`/leak/${id}`, formData, { timeout: 600000 })
export const deleteLeak = (id) => request.delete(`/leak/${id}`)

export function uploadLeakFile(file, onProgress, storage = 'local') {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('storage', storage)
  return request.post('/leak/upload', fd, {
    timeout: 600000,
    onUploadProgress: (e) => {
      if (e.total && onProgress) onProgress(Math.round((e.loaded / e.total) * 100))
    },
  })
}

export const cleanupLeakUploads = (urls) => request.post('/leak/cleanup', { urls })

export async function downloadLeakPdf(id, filename) {
  const blob = await request.get(`/leak/${id}/pdf`, {
    responseType: 'blob',
    timeout: 180000,
  })
  saveBlob(blob, filename)
}
