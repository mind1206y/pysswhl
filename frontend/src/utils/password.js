// 复杂密码要求:至少 8 位,且同时包含大写字母、小写字母、数字、符号
export function passwordIssues(password) {
  const issues = []
  if (!password || password.length < 8) issues.push('至少 8 位')
  if (!/[A-Z]/.test(password || '')) issues.push('需包含大写字母')
  if (!/[a-z]/.test(password || '')) issues.push('需包含小写字母')
  if (!/\d/.test(password || '')) issues.push('需包含数字')
  if (!/[^A-Za-z0-9]/.test(password || '')) issues.push('需包含符号')
  return issues
}

// 可直接放进 el-form rules 的复杂密码校验规则
export const passwordRule = {
  validator: (rule, value, callback) => {
    const issues = passwordIssues(value)
    if (issues.length) {
      callback(new Error('密码' + issues.join('、')))
    } else {
      callback()
    }
  },
  trigger: 'blur',
}

export const PASSWORD_TIP = '至少 8 位,需包含大写字母、小写字母、数字和符号'
