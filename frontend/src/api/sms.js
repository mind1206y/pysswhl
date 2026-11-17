import request from './request'

// 短信发送记录(照旧 SmsRecord/GetList:模糊匹配六字段,riqi 倒序分页,只读)
export const listSmsRecords = (params) => request.get('/sms-records', { params })
