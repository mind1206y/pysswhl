import { defineStore } from 'pinia'
import { getMe, login as apiLogin } from '@/api/auth'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('token') || '',
    user: null,
  }),
  getters: {
    isLoggedIn: (state) => !!state.token,
    permissions: (state) => state.user?.permissions || [],
  },
  actions: {
    async login(form) {
      const data = await apiLogin(form)
      this.token = data.token
      this.user = data.user
      localStorage.setItem('token', data.token)
    },
    async loadUser() {
      if (!this.token) return
      if (!this.user) {
        this.user = await getMe()
      }
    },
    async refreshUser() {
      if (!this.token) return
      this.user = await getMe()
    },
    logout() {
      this.token = ''
      this.user = null
      localStorage.removeItem('token')
    },
    hasPerm(code) {
      if (this.user?.is_superuser) return true
      return this.permissions.includes(code)
    },
  },
})
