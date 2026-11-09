'use strict';
// 车辆保险页面 CDP 真机回归:登录态注入 → /vehicle/baoxian 打开 → 收集 JS 异常 →
// 主表渲染/合计行 → 打开添加保单弹窗(类别胶囊/公司标签下拉) → 截图
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9347;
const BASE = 'http://127.0.0.1:5173';
const TOKEN = process.argv[2] || '';
const SHOT = path.join(__dirname, 'ui_baoxian_shot.png');

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
  const udd = fs.mkdtempSync(path.join(os.tmpdir(), 'cdp-bx-'));
  const chrome = spawn(CHROME, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=' + PORT, '--user-data-dir=' + udd,
    '--window-size=1600,900', 'about:blank',
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
  const logs = [];
  ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.method === 'Runtime.exceptionThrown') {
      errors.push(JSON.stringify(msg.params.exceptionDetails.exception?.description
        || msg.params.exceptionDetails.text));
    }
    if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error') {
      errors.push('log: ' + msg.params.entry.text);
    }
    if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
      logs.push('console: ' + msg.params.args.map((a) => a.value || a.description || '').join(' '));
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

  // 1. 注入登录态后进入 /vehicle/baoxian
  await goto(`${BASE}/login`);
  await evalJs(`localStorage.setItem('token', ${JSON.stringify(TOKEN)}); 'ok'`);
  await goto(`${BASE}/vehicle/baoxian`);
  await sleep(2500);

  const title = await evalJs(
    `document.querySelector('.filter-title')?.textContent.trim() || ''`);
  const rowCount = await evalJs(
    `document.querySelectorAll('.el-table__body tbody tr').length`);
  const summaryText = await evalJs(
    `document.querySelector('.el-table__footer-wrapper')?.textContent || ''`);
  const hint = await evalJs(`document.querySelector('.toolbar-hint')?.textContent || ''`);
  const menuHit = await evalJs(
    `[...document.querySelectorAll('.el-menu-item')].some(a => a.textContent.includes('车辆保险信息'))`);

  // 2. 打开添加保单弹窗
  await evalJs(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('添加保单'))?.click(); 'ok'`);
  await sleep(1200);
  const dlgTitle = await evalJs(
    `document.querySelector('.std-dialog .el-dialog__title')?.textContent || ''`);
  const dlgItems = await evalJs(`document.querySelectorAll('.std-dialog .el-form-item').length`);
  const pillChecked = await evalJs(
    `document.querySelector('.std-dialog .large-label.lg-checked')?.textContent.trim() || ''`);
  // 保险公司下拉(历史标签 allow-create)展开看选项
  await evalJs(`[...document.querySelectorAll('.std-dialog .el-select')][1]?.dispatchEvent(new MouseEvent('click', {bubbles:true})); 'ok'`);
  await sleep(900);
  const bxcomOptions = await evalJs(
    `document.querySelector('.el-select-dropdown:not([style*="display: none"]) .el-select-dropdown__item')?.textContent || ''`);

  await send(ws, 'Page.captureScreenshot', { format: 'png' }).then((r) => {
    fs.writeFileSync(SHOT, Buffer.from(r.data, 'base64'));
  });

  const result = {
    title, rowCount, summaryText, hint, menuHit,
    dlgTitle, dlgItems, pillChecked, bxcomOptions,
    jsErrors: errors.concat(logs),
  };
  console.log(JSON.stringify(result, null, 2));
  cleanup();
  process.exit(errors.length ? 1 : 0);
})();
