<script setup>
import { onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { getPhonePrintData } from '@/api/phone'

const route = useRoute()
const data = ref(null)
const error = ref('')

const todayText = (() => {
  const d = new Date()
  return `${d.getFullYear()}年${String(d.getMonth() + 1).padStart(2, '0')}月${String(d.getDate()).padStart(2, '0')}日`
})()

function money(v) {
  return Number(v || 0).toFixed(2)
}
function day(v) {
  return v ? String(v).slice(0, 10) : ''
}
function doPrint() {
  window.print()
}
function doClose() {
  window.close()
}

onMounted(async () => {
  const id = route.query.id
  if (!id) {
    error.value = '缺少手机记录 id'
    return
  }
  try {
    data.value = await getPhonePrintData(id)
    document.title = `手机签收单 - ${data.value.bh || ''}`
  } catch {
    error.value = '加载签收单失败'
  }
})
</script>

<template>
  <div class="print-page">
    <div class="no-print">
      <button @click="doPrint">打印</button>
      <button class="btn-close" @click="doClose">关闭</button>
    </div>

    <div v-if="error" class="error">{{ error }}</div>

    <template v-else-if="data">
      <template v-for="(copy, idx) in ['第一联（留存联）', '第二联（领用人联）']" :key="copy">
      <div class="copy-wrap">
        <div class="copy-tag">—————— {{ copy }} ——————</div>
        <h2>手机签收单</h2>
        <table class="main">
          <tr>
            <td class="label">部门</td>
            <td class="value">{{ data.bm }}</td>
            <td class="label">手机编号</td>
            <td class="value">{{ data.bh }}</td>
          </tr>
          <tr>
            <td class="label">品牌</td>
            <td class="value">{{ data.pinpai }}</td>
            <td class="label">规格</td>
            <td class="value">{{ data.guige }}</td>
          </tr>
          <tr>
            <td class="label">使用人</td>
            <td class="value">{{ data.shiyongren }}</td>
            <td class="label">用途</td>
            <td class="value">{{ data.yongtu }}</td>
          </tr>
          <tr>
            <td class="label">号码</td>
            <td class="value">{{ data.haoma }}</td>
            <td class="label">启用日期</td>
            <td class="value">{{ day(data.qiyongdate) }}</td>
          </tr>
          <tr>
            <td class="label">价格</td>
            <td colspan="3" class="value">{{ money(data.jiage) }} 元</td>
          </tr>
          <tr>
            <td class="label">备注</td>
            <td colspan="3" class="remarks-area"><div class="remark-inner"></div></td>
          </tr>
          <tr>
            <td class="label">领用签字</td>
            <td colspan="3" class="sign-area">
              <div class="sign-inner">
                签名：<span class="sig-line"></span>
                日期：<span class="sig-line sig-line-s"></span>年<span class="sig-line sig-line-s"></span>月<span class="sig-line sig-line-s"></span>日
              </div>
            </td>
          </tr>
        </table>
        <div class="print-date">打印日期：{{ todayText }}</div>
      </div>
      <div v-if="idx === 0" class="cut-line"><span>··· 裁 ·· 切 ···</span></div>
      </template>
    </template>
  </div>
</template>

<style scoped>
* { box-sizing: border-box; }
.print-page {
  font-family: "SimSun", "Microsoft YaHei", sans-serif;
  font-size: 14px; color: #000; width: 210mm; min-height: 297mm;
  margin: 0 auto; padding: 12mm 16mm 10mm 16mm; background: #fff;
}
.no-print { text-align: center; margin-bottom: 10px; }
.no-print button {
  padding: 5px 24px; font-size: 13px; cursor: pointer; margin: 0 6px;
  border: none; background: #1890ff; color: #fff; border-radius: 3px;
}
.no-print .btn-close { background: #fff; color: #1890ff; border: 1px solid #1890ff; }
.error { text-align: center; color: #f56c6c; padding: 40px 0; }
.copy-wrap { margin-bottom: 6px; }
.copy-tag { text-align: center; font-size: 12px; font-weight: bold; padding: 2px 0; margin-bottom: 4px; color: #555; }
h2 { text-align: center; font-size: 18px; letter-spacing: 6px; margin-bottom: 8px; }
table.main { width: 100%; border-collapse: collapse; border-top: 2px solid #000; border-bottom: 2px solid #000; }
table.main td { padding: 6px 10px; border: 1px solid #666; font-size: 13px; height: 32px; vertical-align: middle; }
table.main td.label { background: #f8f8f8; width: 90px; text-align: center; font-weight: bold; white-space: nowrap; }
table.main td.value { padding-left: 12px; }
.remarks-area { padding: 8px 10px !important; }
.remark-inner { min-height: 50px; }
.sign-area { padding: 8px 10px !important; }
.sign-inner { min-height: 60px; padding-top: 30px; }
.sig-line { display: inline-block; border-bottom: 1px solid #000; width: 100px; margin: 0 4px; }
.sig-line-s { width: 36px; }
.cut-line { text-align: center; margin: 16px 0 14px; border-top: 1px dashed #000; height: 0; line-height: 0; position: relative; }
.cut-line span { position: relative; top: -10px; background: #fff; padding: 0 12px; font-size: 11px; color: #999; letter-spacing: 4px; }
.print-date { text-align: right; font-size: 13px; color: #333; margin-top: 4px; }
tr { page-break-inside: avoid; }
@media print {
  .no-print { display: none; }
  .print-page { width: auto; min-height: auto; margin: 0; padding: 10mm 14mm 8mm 14mm; }
}
@page { size: A4 portrait; margin: 10mm 8mm 10mm 8mm; }
</style>
