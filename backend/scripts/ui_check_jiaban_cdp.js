'use strict';
// 维抢修加班页面 CDP 真机回归:登录态注入 → /jiaban 打开 → 收集 JS 异常 →
// 主表渲染 → 打开添加弹窗(人员下拉/工单历史表) → 打开加班人员弹窗 → 打开附件抽屉 → 截图
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9346;
const BASE = 'http://127.0.0.1:5173';
const TOKEN = process.argv[2] || '';
const SHOT = path.join(__dirname, 'ui_jiaban_shot.png');

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
  const udd = fs.mkdtempSync(path.join(os.tmpdir(), 'cdp-jb-'));
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

  // 1. 注入登录态后进入 /jiaban
  await goto(`${BASE}/login`);
  await evalJs(`localStorage.setItem('token', ${JSON.stringify(TOKEN)}); 'ok'`);
  await goto(`${BASE}/jiaban`);
  await sleep(2500);

  const banner = await evalJs(
    `document.querySelector('.jb-banner') ? document.querySelector('.jb-banner').textContent.trim() : ''`);
  const rowCount0 = await evalJs(
    `document.querySelectorAll('.jb-table-wrap .el-table__body tbody tr').length`);
  const summary = await evalJs(
    `document.querySelector('.jb-summary') ? document.querySelector('.jb-summary').textContent : ''`);
  const menuHit = await evalJs(
    `[...document.querySelectorAll('.el-menu-item')].some(a => a.textContent.includes('维抢修加班'))`);

  // 周期切到"全部",主表应有真实数据(3095 条里第 1 页 25 行)
  await evalJs(`(function(){
    const sel = document.querySelector('.jb-search .el-select__wrapper');
    sel.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    return 'ok';
  })()`);
  await sleep(800);
  const periodPicked = await evalJs(`(function(){
    const items = [...document.querySelectorAll('.el-select-dropdown__item')];
    const all = items.find(i => i.textContent.trim() === '全部');
    if (all) all.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    return items.length;
  })()`);
  await sleep(2500);
  const rowCount = await evalJs(
    `document.querySelectorAll('.jb-table-wrap .el-table__body tbody tr').length`);

  // 2. 打开添加弹窗
  await evalJs(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('添加'))?.click(); 'ok'`);
  await sleep(1200);
  const dlgTitle = await evalJs(
    `document.querySelector('.std-dialog .el-dialog__title')?.textContent || ''`);
  const dlgInputs = await evalJs(`document.querySelectorAll('.std-dialog .el-form-item').length`);
  const dlgRecords = await evalJs(`!!document.querySelector('.std-dialog .jb-records')`);

  // 3. 关闭添加弹窗,打开加班人员管理
  await evalJs(`[...document.querySelectorAll('.std-dialog button')].find(b => b.textContent.trim()==='取消')?.click(); 'ok'`);
  await sleep(600);
  await evalJs(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('加班人员'))?.click(); 'ok'`);
  await sleep(1200);
  const renRows = await evalJs(
    `document.querySelectorAll('.jb-ren-top ~ .el-table tbody tr').length`);

  // 4. 打开附件抽屉
  await evalJs(`[...document.querySelectorAll('.std-dialog button')].find(b => b.textContent.trim()==='关闭')?.click(); 'ok'`);
  await sleep(600);
  await evalJs(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('附件'))?.click(); 'ok'`);
  await sleep(1500);
  const attTitle = await evalJs(
    `[...document.querySelectorAll('.el-drawer .el-drawer__title')].pop()?.textContent?.trim() || ''`);
  const attRows = await evalJs(
    `(() => { const ds = [...document.querySelectorAll('.el-drawer')]; const d = ds.pop();
       return d ? d.querySelectorAll('.el-table__body tbody tr').length : -1; })()`);
  const attTotalText = await evalJs(
    `(() => { const ds = [...document.querySelectorAll('.el-drawer')]; const d = ds.pop();
       const p = d && d.querySelector('.jb-att-pager .el-pagination__total');
       return p ? p.textContent : ''; })()`);

  // 5. 点击图片附件名 → 全屏浏览窗(滚轮翻页)
  const ivClicked = await evalJs(`(() => { const ds = [...document.querySelectorAll('.el-drawer')]; const d = ds.pop();
     const a = d && [...d.querySelectorAll('.jb-link')].find(x => x.textContent.includes('jbcheck'));
     if (a) a.click(); return !!a; })()`);
  await sleep(1500);
  const ivVisible = await evalJs(`!!document.querySelector('.jb-iv')`);
  const ivCount = await evalJs(
    `document.querySelector('.jb-iv-count')?.textContent.trim() || ''`);
  const ivImg = await evalJs(`(() => { const i = document.querySelector('.jb-iv-body img');
     return i ? { complete: i.complete, natW: i.naturalWidth } : null; })()`);
  // 滚轮事件:当月仅 1 张,应保持 1/1 不越界
  await evalJs(
    `document.querySelector('.jb-iv').dispatchEvent(new WheelEvent('wheel', {deltaY: 120, bubbles: true})); 'ok'`);
  await sleep(400);
  const ivCountAfterWheel = await evalJs(
    `document.querySelector('.jb-iv-count')?.textContent.trim() || ''`);
  await send(ws, 'Page.captureScreenshot', { format: 'png' }).then((r) => {
    fs.writeFileSync(SHOT, Buffer.from(r.data, 'base64'));
  });
  // Esc 关闭
  await evalJs(
    `window.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); 'ok'`);
  await sleep(400);
  const ivClosed = await evalJs(`!document.querySelector('.jb-iv')`);

  const result = {
    banner, rowCount0, periodPicked, rowCount, summary, menuHit, dlgTitle, dlgInputs, dlgRecords,
    renRows, attTitle, attRows, attTotalText,
    ivClicked, ivVisible, ivCount, ivImg, ivCountAfterWheel, ivClosed,
    jsErrors: errors.concat(logs),
  };
  console.log(JSON.stringify(result, null, 2));
  cleanup();
  process.exit(errors.length ? 1 : 0);
})();
