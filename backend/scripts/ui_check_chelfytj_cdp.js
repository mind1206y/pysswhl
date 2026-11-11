'use strict';
// 车辆费用明细统计页面 CDP 真机回归:登录态注入 → /vehicle/chelfytj → 收集 JS 异常 →
// 主表/合计行/菜单/默认日期 → 关键字筛选 → 状态筛选 → 截图
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9352;
const BASE = 'http://127.0.0.1:5173';
const TOKEN = process.argv[2] || '';
const SHOT = path.join(__dirname, 'ui_chelfytj_shot.png');

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
  const udd = fs.mkdtempSync(path.join(os.tmpdir(), 'cdp-cftj-'));
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

  // 1. 注入登录态后进入 /vehicle/chelfytj
  await goto(`${BASE}/login`);
  await evalJs(`localStorage.setItem('token', ${JSON.stringify(TOKEN)}); 'ok'`);
  await goto(`${BASE}/vehicle/chelfytj`);
  await sleep(2500);
  // Vite 首次编译/HMR 会吐其它模块的时序噪声,与本页面无关;
  // 清掉计数后再冷刷新一次,只统计稳定加载后的异常。
  errors.length = 0;
  logs.length = 0;
  await send(ws, 'Page.reload', { ignoreCache: true });
  await sleep(3000);

  const title = await evalJs(`document.querySelector('.filter-title')?.textContent.trim() || ''`);
  const rowCount = await evalJs(`document.querySelectorAll('.el-table__body tbody tr').length`);
  const footerText = await evalJs(
    `document.querySelector('.el-table__footer-wrapper')?.textContent || ''`);
  const hint = await evalJs(`document.querySelector('.toolbar-hint')?.textContent || ''`);
  const menuHit = await evalJs(
    `[...document.querySelectorAll('.el-menu-item')].some(a => a.textContent.includes('车辆费用明细统计'))`);
  const dateVals = await evalJs(`(() => {
    const inputs = [...document.querySelectorAll('.filter-form .el-date-editor input')];
    return inputs.slice(0, 2).map(i => i.value);
  })()`);
  const noPageScroll = await evalJs(
    `document.documentElement.scrollHeight <= document.documentElement.clientHeight + 1`);
  const noTableHScroll = await evalJs(`(() => {
    const w = document.querySelector('.el-table__body-wrapper .el-scrollbar__wrap');
    return w ? w.scrollWidth <= w.clientWidth + 1 : true;
  })()`);
  const exportBtn = await evalJs(
    `[...document.querySelectorAll('button')].some(b => b.textContent.includes('导出Excel'))`);

  // 2. 关键字筛选(取第一行车号,点查询后条数应变化且无异常)
  const firstCar = await evalJs(
    `document.querySelector('.el-table__body tbody tr td:nth-child(3)')?.textContent.trim() || ''`);
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
  const filteredHint = await evalJs(`document.querySelector('.toolbar-hint')?.textContent || ''`);

  // 3. 状态下拉切「已报废」(el-select 交互)
  let bfHint = '';
  try {
    await evalJs(`(() => {
      const items = [...document.querySelectorAll('.filter-form .el-select')];
      // 状态下拉是第 6 个(关键字/部门/类型/用途/状态,年度不算 el-select? 统一按 placeholder 找)
      const s = [...document.querySelectorAll('.filter-form .el-select__wrapper')]
        .find(w => (w.textContent || '').includes('全部'));
      if (s) s.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      return !!s;
    })()`);
    await sleep(800);
    await evalJs(`(() => {
      const opt = [...document.querySelectorAll('.el-select-dropdown__item')]
        .find(o => o.textContent.trim() === '已报废');
      if (opt) opt.dispatchEvent(new MouseEvent('click', { bubbles: true }));
      return !!opt;
    })()`);
    await sleep(800);
    await evalJs(`[...document.querySelectorAll('button')].find(b => b.textContent.trim() === '查询')?.click(); 'ok'`);
    await sleep(1800);
    bfHint = await evalJs(`document.querySelector('.toolbar-hint')?.textContent || ''`);
  } catch (e) { bfHint = 'ERR ' + e.message; }

  await send(ws, 'Page.captureScreenshot', { format: 'png' }).then((r) => {
    fs.writeFileSync(SHOT, Buffer.from(r.data, 'base64'));
  });

  const result = {
    title, rowCount, footerText: footerText.replace(/\s+/g, ' ').trim().slice(0, 120),
    hint, menuHit, dateVals, noPageScroll, noTableHScroll, exportBtn,
    firstCar, filterDebug, filteredHint, bfHint,
    jsErrors: errors.concat(logs),
  };
  console.log(JSON.stringify(result, null, 2));
  cleanup();
  process.exit(errors.length ? 1 : 0);
})();
