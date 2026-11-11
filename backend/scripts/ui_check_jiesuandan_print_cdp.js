'use strict';
// 领料结算「直接打印」页 CDP 真机回归:
// 登录态注入 → /jiesuandan/print → 校验申请单三栏签字 + 验收单验收情况=完成 → 截图
// 用法: node scripts/ui_check_jiesuandan_print_cdp.js <token> [orderId]
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9361;
const BASE = 'http://127.0.0.1:5173';
const TOKEN = process.argv[2] || '';
const ORDER_ID = process.argv[3] || '11';
const SHOT = path.join(__dirname, 'ui_jiesuandan_print_shot.png');

function get(url) {
  return new Promise((res, rej) => {
    http.get(url, (r) => { let b = ''; r.on('data', (d) => (b += d)); r.on('end', () => res(b)); })
      .on('error', rej);
  });
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let sendId = 0;
function send(ws, method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++sendId;
    const onMsg = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.id === id) {
        ws.removeEventListener('message', onMsg);
        if (msg.error) reject(new Error(method + ': ' + JSON.stringify(msg.error)));
        else resolve(msg.result);
      }
    };
    ws.addEventListener('message', onMsg);
    ws.send(JSON.stringify({ id, method, params }));
  });
}

(async function main() {
  const udd = fs.mkdtempSync(path.join(os.tmpdir(), 'cdp-jsd-print-'));
  const chrome = spawn(CHROME, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=' + PORT, '--user-data-dir=' + udd,
    '--window-size=1200,2200', 'about:blank',
  ], { stdio: 'ignore' });
  const cleanup = () => { try { chrome.kill(); } catch (e) { } };
  process.on('exit', cleanup);

  let list = null;
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    try { list = JSON.parse(await get(`http://127.0.0.1:${PORT}/json/list`)); } catch (e) { }
    if (list && list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl)) break;
  }
  const target = (list || []).find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
  if (!target) { console.error('调试端口没起来'); cleanup(); process.exit(2); }

  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener('open', r));

  const errors = [];
  ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.method === 'Runtime.exceptionThrown') {
      errors.push(JSON.stringify(msg.params.exceptionDetails.exception?.description
        || msg.params.exceptionDetails.text));
    }
    if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error') {
      const e = msg.params.entry;
      if (!String(e.url || '').includes('favicon.ico')) {
        errors.push('log: ' + String(e.url || '') + ' ' + String(e.text || ''));
      }
    }
  });

  await send(ws, 'Runtime.enable');
  await send(ws, 'Log.enable');
  await send(ws, 'Page.enable');

  async function goto(url) {
    await send(ws, 'Page.navigate', { url });
    await sleep(1800);
  }
  async function evalJs(expr) {
    const r = await send(ws, 'Runtime.evaluate', {
      expression: expr, awaitPromise: true, returnByValue: true,
    });
    if (r.exceptionDetails) throw new Error('eval: ' + JSON.stringify(r.exceptionDetails.text));
    return r.result.value;
  }

  // 注入登录态后打开打印页
  await goto(`${BASE}/login`);
  await evalJs(`localStorage.setItem('token', ${JSON.stringify(TOKEN)}); 'ok'`);
  await goto(`${BASE}/jiesuandan/print?id=${ORDER_ID}&sgbm=${encodeURIComponent('测试部门')}&sgyy=${encodeURIComponent('测试申购原因')}`);
  await sleep(2200);
  errors.length = 0;
  await send(ws, 'Page.reload', { ignoreCache: true });
  await sleep(2500);

  const titles = await evalJs(
    `[...document.querySelectorAll('.sheet .doc-title')].map(d => d.textContent.trim())`);
  const errorText = await evalJs(`document.querySelector('.error')?.textContent.trim() || ''`);
  // 申请单底部三栏签字
  const sign = await evalJs(`(() => {
    const s = document.querySelector('.sheet .sign-row.sign-three');
    return s ? [...s.children].map(d => d.textContent.trim()) : null;
  })()`);
  // 验收单:表头 + 明细行「验收情况」列 + 合计行该列留空
  const ys = await evalJs(`(() => {
    const sheet = document.querySelectorAll('.sheet')[1];
    if (!sheet) return null;
    const rows = [...sheet.querySelectorAll('tbody tr:not(.sum)')];
    return {
      header: sheet.querySelectorAll('thead th')[7]?.textContent.trim(),
      rowCount: rows.length,
      values: [...new Set(rows.map(r => r.children[7]?.textContent.trim()))],
      sumCell: sheet.querySelector('tr.sum')?.children[7]?.textContent.trim(),
      sign: [...(sheet.querySelector('.sign-row')?.children || [])].map(d => d.textContent.trim()),
    };
  })()`);

  await send(ws, 'Page.captureScreenshot', { format: 'png', captureBeyondViewport: true }).then((r) => {
    fs.writeFileSync(SHOT, Buffer.from(r.data, 'base64'));
  });

  const okSign = JSON.stringify(sign) === JSON.stringify(['审批：', '审核：', '申请人：']);
  const okYs = !!ys && ys.header === '验收情况' && ys.rowCount > 0
    && JSON.stringify(ys.values) === JSON.stringify(['完成'])
    && (ys.sumCell || '') === '';
  const result = {
    orderId: ORDER_ID, titles, errorText, sign, ys, okSign, okYs,
    screenshot: SHOT, jsErrors: errors,
  };
  console.log(JSON.stringify(result, null, 2));
  cleanup();
  process.exit(okSign && okYs && errors.length === 0 ? 0 : 1);
})();
