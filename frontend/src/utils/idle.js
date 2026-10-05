import { onMounted, onUnmounted } from 'vue'

// 公用电脑防护:N 分钟无任何操作自动执行回调(通常用于自动退出登录)
export function useIdleLogout(onIdle, minutes = 30) {
  const IDLE_MS = minutes * 60 * 1000
  let lastActive = Date.now()
  let interval = null

  const markActive = () => {
    lastActive = Date.now()
  }
  const events = ['click', 'keydown', 'mousemove', 'scroll', 'touchstart']

  onMounted(() => {
    events.forEach((e) => window.addEventListener(e, markActive, { passive: true }))
    interval = setInterval(() => {
      if (Date.now() - lastActive > IDLE_MS) onIdle()
    }, 60 * 1000)
  })

  onUnmounted(() => {
    events.forEach((e) => window.removeEventListener(e, markActive))
    if (interval) clearInterval(interval)
  })
}
