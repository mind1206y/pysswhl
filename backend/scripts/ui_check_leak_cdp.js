'use strict';
// 测漏笔记(LeakNotes /leak)「新增测漏记录」弹窗 CDP 实机核查:
// 登录态注入 → /leak → 新增 → 校验 std-dialog 视觉 + 标题占两列 + 截图
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9355;
const BASE = 'http://127.0.0.1:5173';
const TOKEN = process.argv[2] || '';
const SHOT = path.join(__dirname, 'ui_leak_shot.png');

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
  const udd = fs.mkdtempSync(path.join(os.tmpdir(), 'cdp-lk-'));
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

  await goto(`${BASE}/login`);
  await evalJs(`localStorage.setItem('token', ${JSON.stringify(TOKEN)}); 'ok'`);
  await goto(`${BASE}/leak`);
  await sleep(2500);
  errors.length = 0;
  await send(ws, 'Page.reload', { ignoreCache: true });
  await sleep(3000);

  const menuHit = await evalJs(
    `[...document.querySelectorAll('.el-menu-item')].some(a => a.textContent.includes('测漏笔记'))`);

  // 点「新增测漏记录」
  await evalJs(`[...document.querySelectorAll('button')].find(b => b.textContent.includes('新增测漏记录'))?.click(); 'ok'`);
  await sleep(1400);

  const hasStd = await evalJs(`!!document.querySelector('.std-dialog')`);
  const headerBg = await evalJs(`(() => {
    const h = document.querySelector('.std-dialog .el-dialog__header');
    return h ? getComputedStyle(h).backgroundColor : null;
  })()`);
  const dlgTitle = await evalJs(`document.querySelector('.std-dialog .el-dialog__title')?.textContent || ''`);

  // 标题字段是否占满两列:找 label 为「标题」的 form-item,向上取最近 .el-col,检查 class 含 el-col-24
  const titleSpan = await evalJs(`(() => {
    const labels = [...document.querySelectorAll('.std-dialog .el-form-item__label')];
    const t = labels.find(l => l.textContent.trim() === '标题');
    if (!t) return null;
    const col = t.closest('.el-col');
    const cls = col ? col.className : '';
    const rect = col ? col.getBoundingClientRect() : null;
    // 第二行第一个(地点)的 col 宽度,用于对比
    const l2 = labels.find(l => l.textContent.trim() === '地点');
    const col2 = l2 ? l2.closest('.el-col') : null;
    const rect2 = col2 ? col2.getBoundingClientRect() : null;
    return { colClass: cls, titleWidth: rect ? Math.round(rect.width) : 0, locWidth: rect2 ? Math.round(rect2.width) : 0 };
  })()`);

  const inpRadius = await evalJs(`(() => {
    const w = document.querySelector('.std-dialog .el-input__wrapper, .std-dialog .el-select__wrapper');
    if (!w) return null;
    const s = getComputedStyle(w);
    return { h: Math.round(w.getBoundingClientRect().height), radius: s.borderRadius };
  })()`);
  const footerBg = await evalJs(`(() => {
    const f = document.querySelector('.std-dialog .el-dialog__footer');
    return f ? getComputedStyle(f).backgroundColor : null;
  })()`);
  const bodyNoScroll = await evalJs(`(() => {
    const b = document.querySelector('.std-dialog .el-dialog__body');
    return b ? b.scrollHeight <= b.clientHeight + 1 : false;
  })()`);

  await send(ws, 'Page.captureScreenshot', { format: 'png' }).then((r) => {
    fs.writeFileSync(SHOT, Buffer.from(r.data, 'base64'));
  });

  const result = {
    menuHit, hasStd, dlgTitle, headerBg, inpRadius, footerBg, titleSpan, bodyNoScroll, jsErrors: errors,
  };
  console.log(JSON.stringify(result, null, 2));
  cleanup();
  process.exit(errors.length ? 1 : 0);
})();
