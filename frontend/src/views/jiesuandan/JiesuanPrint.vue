<script setup>
/**
 * 物资采购申请单 / 验收单打印页 —— 照旧 Views/jiesuandan/PrintCg.cshtml 复刻
 * 独立窗口打开(不套 MainLayout),使用 localStorage token 调后端接口。
 */
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { getJiesuanPrintData } from '@/api/jiesuandan'

const route = useRoute()
const data = ref(null)
const error = ref('')

const rows = computed(() => data.value?.rows || [])
const main = computed(() => data.value?.main || {})
const userBm = computed(() => data.value?.userBm || '')
const sgbm = computed(() => data.value?.sgbm || '')
const sgyy = computed(() => data.value?.sgyy || '')

function joinGg(model, spec) {
  const a = (model || '').trim()
  const b = (spec || '').trim()
  if (a && b) return `${a}/${b}`
  return a + b
}

function F(v) {
  const n = Number(v || 0)
  return Number.isInteger(n) ? String(n) : String(Number(n.toFixed(2)))
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
    error.value = '缺少结算单 id'
    return
  }
  try {
    data.value = await getJiesuanPrintData(id, {
      sgbm: route.query.sgbm || '',
      sgyy: route.query.sgyy || '',
    })
    document.title = `物资采购申请单/验收单 - ${main.value.jiesuandanno || ''}`
  } catch {
    error.value = '加载采购单据失败'
  }
})
</script>

<template>
  <div class="print-page">
    <div class="print-bar no-print">
      <button @click="doPrint">打印两张单</button>
      <span class="tip">
        点击按钮后在弹出的打印对话框中选择打印机,申请单与验收单将分两页打印,明细行数不限
      </span>
    </div>

    <div v-if="error" class="error">{{ error }}</div>

    <template v-else-if="data">
      <!-- ==================== 第一页:物资采购申请单 ==================== -->
      <div class="sheet">
        <div class="doc-title">{{ userBm }}物资采购申请单</div>
        <div class="doc-info">
          <div class="left">申请部门：{{ sgbm }}</div>
          <div>结算单号：{{ main.jiesuandanno }}</div>
        </div>
        <div class="doc-info">申购原因：{{ sgyy }}</div>
        <table class="doc">
          <thead>
            <tr>
              <th style="width: 6%">序号</th>
              <th style="width: 22%">材料名称</th>
              <th style="width: 16%">规格、型号</th>
              <th style="width: 8%">单位</th>
              <th style="width: 9%">数量</th>
              <th style="width: 11%">单价</th>
              <th style="width: 12%">金额</th>
              <th style="width: 16%">备注</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(m, i) in rows" :key="'sq' + i">
              <td>{{ i + 1 }}</td>
              <td class="left">{{ m.llname }}</td>
              <td class="left">{{ joinGg(m.model, m.spec) }}</td>
              <td>{{ m.unit }}</td>
              <td>{{ F(m.num) }}</td>
              <td>{{ F(m.danjia) }}</td>
              <td>{{ F(m.jine) }}</td>
              <td class="left">{{ m.beizhu }}</td>
            </tr>
            <tr class="sum">
              <td colspan="6" style="text-align: right; padding-right: 12px;">合计</td>
              <td>{{ F(main.zonge) }}</td>
              <td></td>
            </tr>
          </tbody>
        </table>
        <div class="sign-row">
          <div class="s1">审核：</div>
          <div class="s2">申请人：</div>
        </div>
      </div>

      <!-- ==================== 第二页:物资采购验收单 ==================== -->
      <div class="sheet">
        <div class="doc-title">{{ userBm }}物资采购验收单</div>
        <div class="doc-info">
          <div class="left">部门名称：{{ sgbm }}　结算单号：{{ main.jiesuandanno }}</div>
          <div>日期：{{ main.jiesuanriqi }}</div>
        </div>
        <table class="doc">
          <thead>
            <tr>
              <th style="width: 5%">序号</th>
              <th style="width: 19%">材料名称</th>
              <th style="width: 14%">规格、型号</th>
              <th style="width: 7%">单位</th>
              <th style="width: 8%">数量</th>
              <th style="width: 10%">单价</th>
              <th style="width: 11%">金额</th>
              <th style="width: 12%">验收情况</th>
              <th style="width: 14%">备注</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(m, i) in rows" :key="'ys' + i">
              <td>{{ i + 1 }}</td>
              <td class="left">{{ m.llname }}</td>
              <td class="left">{{ joinGg(m.model, m.spec) }}</td>
              <td>{{ m.unit }}</td>
              <td>{{ F(m.num) }}</td>
              <td>{{ F(m.danjia) }}</td>
              <td>{{ F(m.jine) }}</td>
              <td></td>
              <td class="left">{{ m.beizhu }}</td>
            </tr>
            <tr class="sum">
              <td colspan="6" style="text-align: right; padding-right: 12px;">合计</td>
              <td>{{ F(main.zonge) }}</td>
              <td></td>
              <td></td>
            </tr>
          </tbody>
        </table>
        <div class="sign-row">
          <div class="s1">验收：</div>
          <div class="s2">经办：</div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
html, body { margin: 0; padding: 0; }
.print-page {
  margin: 0;
  padding: 0;
  background: #eef1f5;
  font-family: "Microsoft YaHei", "SimSun", sans-serif;
  color: #000;
  min-height: 100vh;
}
.print-bar {
  position: sticky; top: 0; z-index: 10;
  background: #1c1e54; color: #fff; padding: 10px 16px;
  display: flex; align-items: center; gap: 10px;
}
.print-bar .tip { font-size: 13px; opacity: 0.85; }
.print-bar button {
  padding: 6px 18px; border: none; border-radius: 6px;
  background: #533afd; color: #fff; font-size: 14px; cursor: pointer;
}
.print-bar button:hover { background: #4529d9; }
.sheet {
  width: 210mm; min-height: 250mm; margin: 16px auto; background: #fff;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12); padding: 12mm 12mm; box-sizing: border-box;
}
.doc-title {
  text-align: center; font-size: 22px; font-weight: bold;
  letter-spacing: 2px; padding: 10px 0 14px;
}
.doc-info { font-size: 14px; margin-bottom: 6px; display: flex; justify-content: space-between; }
.doc-info .left { flex: 1; }
table.doc { width: 100%; border-collapse: collapse; font-size: 13px; }
table.doc thead { display: table-header-group; }
table.doc tr { page-break-inside: avoid; }
table.doc th, table.doc td {
  border: 1px solid #000; padding: 5px 4px; text-align: center; height: 24px;
}
table.doc th { font-weight: bold; }
table.doc td.left { text-align: left; padding-left: 6px; }
table.doc tr.sum td { font-weight: bold; }
.sign-row { margin-top: 22px; font-size: 14px; display: flex; }
.sign-row .s1 { width: 40%; padding-left: 40px; }
.sign-row .s2 { width: 40%; padding-left: 60px; }
.error { text-align: center; color: #f56c6c; padding: 40px 0; }
@media print {
  html, body { background: #fff; }
  .no-print { display: none; }
  .print-page { background: #fff; }
  .sheet {
    box-shadow: none; margin: 0; width: auto; min-height: auto;
    page-break-after: always;
  }
  .sheet:last-child { page-break-after: auto; }
}
</style>
