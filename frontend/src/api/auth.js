import request from './request'

let cachedPublicKey = null

// Web Crypto(crypto.subtle) 只在「安全上下文」暴露:https、localhost、127.0.0.1。
// 内网部署常用 http://<内网IP>:18080,此时 crypto.subtle 是 undefined,
// 直接调用会抛 TypeError: Cannot read properties of undefined (reading 'importKey')。
// 这种情况降级为带前缀的明文,后端 decrypt_password 认这个前缀(见 backend/app/core/security.py)。
// 一旦以后套上 HTTPS,这里会自动恢复加密,不用改代码。
const PLAIN_PREFIX = 'plain:'

function hasWebCrypto() {
  return typeof globalThis !== 'undefined' && !!globalThis.crypto?.subtle
}

// RSA-OAEP(SHA-256) 加密:后端下发公钥,密码不再明文出现在请求里
async function encryptPassword(password) {
  if (!hasWebCrypto()) return PLAIN_PREFIX + password
  if (!cachedPublicKey) {
    const res = await request.get('/auth/public-key')
    cachedPublicKey = res.publicKey
  }
  const pemBody = cachedPublicKey
    .replace(/-----BEGIN PUBLIC KEY-----/, '')
    .replace(/-----END PUBLIC KEY-----/, '')
    .replace(/\s+/g, '')
  const der = Uint8Array.from(atob(pemBody), (c) => c.charCodeAt(0))
  const key = await crypto.subtle.importKey(
    'spki',
    der.buffer,
    { name: 'RSA-OAEP', hash: 'SHA-256' },
    false,
    ['encrypt']
  )
  const encrypted = await crypto.subtle.encrypt(
    { name: 'RSA-OAEP' },
    key,
    new TextEncoder().encode(password)
  )
  return btoa(String.fromCharCode(...new Uint8Array(encrypted)))
}

// 后端重启会更换公钥,旧密文解不开;此时清缓存重新取公钥再试一次
function isDecryptError(err) {
  return err?.response?.data?.detail === '密码解密失败,请刷新页面后重试'
}

export const login = async (data) => {
  const encrypted = await encryptPassword(data.password)
  try {
    return await request.post('/auth/login', { username: data.username, password: encrypted })
  } catch (err) {
    if (!isDecryptError(err)) throw err
    cachedPublicKey = null
    const retried = await encryptPassword(data.password)
    return request.post('/auth/login', { username: data.username, password: retried })
  }
}

export const getMe = () => request.get('/auth/me')

export const changePassword = async (data) => {
  const send = async () => ({
    old_password: await encryptPassword(data.old_password),
    new_password: await encryptPassword(data.new_password),
  })
  try {
    return await request.put('/auth/password', await send())
  } catch (err) {
    if (!isDecryptError(err)) throw err
    cachedPublicKey = null
    return request.put('/auth/password', await send())
  }
}
