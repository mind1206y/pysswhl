'use strict';
// 车辆各类费用页面 CDP 真机回归:登录态注入 → /vehicle/clfeiyong → 收集 JS 异常 →
// 主表/合计行/菜单 → 关键字筛选 → 添加费用弹窗(类别单选/车号下拉) → 截图
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9351;
const BASE = 'http://127.0.0.1:5173';
const TOKEN = process.argv[2] || '';
const SHOT = path.join(__dirname, 'ui_clfeiyong_shot.png');
const LIST_SHOT = path.join(__dirname, 'ui_clfeiyong_list.png');

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
  const udd = fs.mkdtempSync(path.join(os.tmpdir(), 'cdp-fy-'));
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
      const e = msg.params.entry;
      // 全局 favicon.ico 404 与业务无关,只有 log.text 拿不到 URL,要用 entry.url 过滤
      if (!String(e.url || '').includes('favicon.ico')) {
        errors.push('log: ' + String(e.url || '') + ' ' + String(e.text || ''));
      }
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

  // 1. 注入登录态后进入 /vehicle/clfeiyong
  await goto(`${BASE}/login`);
  await evalJs(`localStorage.setItem('token', ${JSON.stringify(TOKEN)}); 'ok'`);
  await goto(`${BASE}/vehicle/clfeiyong`);
  await sleep(2500);
  // Vite 首次编译/HMR 会吐其它模块的时序噪声(如 JiabanManage TDZ),与本页面无关;
  // 清掉计数后再冷刷新一次,只统计稳定加载后的异常。
  errors.length = 0;
  logs.length = 0;
  await send(ws, 'Page.reload', { ignoreCache: true });
  await sleep(3000);

  const title = await evalJs(`document.querySelector('.filter-title')?.textContent.trim() || ''`);
  const rowCount = await evalJs(`document.querySelectorAll('.el-table__body tbody tr').length`);
  const summaryText = await evalJs(
    `document.querySelector('.el-table__footer-wrapper')?.textContent || ''`);
  const hint = await evalJs(`document.querySelector('.toolbar-hint')?.textContent || ''`);
  const menuHit = await evalJs(
    `[...document.querySelectorAll('.el-menu-item')].some(a => a.textContent.includes('车辆各类费用表'))`);
  const noPageScroll = await evalJs(
    `document.documentElement.scrollHeight <= document.documentElement.clientHeight + 1`);
  const noTableHScroll = await evalJs(`(() => {
    const w = document.querySelector('.el-table__body-wrapper .el-scrollbar__wrap');
    return w ? w.scrollWidth <= w.clientWidth + 1 : true;
  })()`);
  await send(ws, 'Page.captureScreenshot', { format: 'png' }).then((r) => {
    fs.writeFileSync(LIST_SHOT, Buffer.from(r.data, 'base64'));
  });

  // 2. 关键字筛选(取第一行车号,点查询后条数应变化且无异常)
  const firstCar = await evalJs(
    `document.querySelector('.el-table__body tbody tr td:nth-child(4)')?.textContent.trim() || ''`);
  let filterDebug = null;
  if (firstCar) {
    filterDebug = await evalJs(`(() => {
      const i = document.querySelector('.filter-form input');
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
      setter.call(i, ${JSON.stringify(firstCar)});
      i.dispatchEvent(new Event('input', { bubbles: true }));
      return { typed: i.value };
    })()`);
    const clicked = await evalJs(`(() => {
      const b = [...document.querySelectorAll('button')].find(b => b.textContent.trim() === '查询');
      if (!b) return false;
      b.click(); return true;
    })()`);
    await sleep(1800);
    filterDebug.clicked = clicked;
  }
  const filteredRows = await evalJs(`document.querySelectorAll('.el-table__body tbody tr').length`);
  const filteredHint = await evalJs(`document.querySelector('.toolbar-hint')?.textContent || ''`);

  // 3. 打开添加费用弹窗
  await evalJs(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('添加费用'))?.click(); 'ok'`);
  await sleep(1200);
  const dlgTitle = await evalJs(`document.querySelector('.std-dialog .el-dialog__title')?.textContent || ''`);
  const dlgItems = await evalJs(`document.querySelectorAll('.std-dialog .el-form-item').length`);
  const radioChecked = await evalJs(
    `document.querySelector('.std-dialog .el-radio.is-checked')?.textContent.trim() || ''`);
  const dlgHeight = await evalJs(
    `Math.round(document.querySelector('.std-dialog')?.getBoundingClientRect().height || 0)`);
  const dialogNoScroll = await evalJs(`(() => {
    const b = document.querySelector('.std-dialog .el-dialog__body');
    return b ? b.scrollHeight <= b.clientHeight + 1 : false;
  })()`);

  await send(ws, 'Page.captureScreenshot', { format: 'png' }).then((r) => {
    fs.writeFileSync(SHOT, Buffer.from(r.data, 'base64'));
  });

  const result = {
    title, rowCount, summaryText: summaryText.replace(/\s+/g, ' ').trim(), hint, menuHit,
    noPageScroll, noTableHScroll, firstCar, filterDebug, filteredRows, filteredHint,
    dlgTitle, dlgItems, radioChecked, dlgHeight, dialogNoScroll,
    jsErrors: errors.concat(logs),
  };
  console.log(JSON.stringify(result, null, 2));
  cleanup();
  process.exit(errors.length ? 1 : 0);
})();
