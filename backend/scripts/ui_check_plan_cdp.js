'use strict';
// 年度计划 4 个页面 CDP 真机回归:注入登录态 -> 逐页打开 -> 收集 JS 异常 -> 检查表格/弹窗 -> 截图
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9351;
const BASE = 'http://127.0.0.1:5173';
const TOKEN = process.argv[2] || '';
const SHOT_DIR = path.join(__dirname, 'plan_shots');

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

async function main() {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  const udd = fs.mkdtempSync(path.join(os.tmpdir(), 'cdp-plan-'));
  const chrome = spawn(CHROME, [
    '--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=' + PORT, '--user-data-dir=' + udd,
    '--window-size=1800,980', 'about:blank',
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
      errors.push('exc: ' + JSON.stringify(msg.params.exceptionDetails.exception?.description
        || msg.params.exceptionDetails.text));
    }
    if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error') {
      errors.push('log: ' + msg.params.entry.text);
    }
    if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
      errors.push('console: ' + msg.params.args.map((a) => a.value || a.description || '').join(' '));
    }
  });
  await send(ws, 'Runtime.enable');
  await send(ws, 'Log.enable');
  await send(ws, 'Page.enable');

  const evalJs = async (expr, awaitPromise = true) => {
    const r = await send(ws, 'Runtime.evaluate', { expression: expr, awaitPromise, returnByValue: true });
    return r.result?.value;
  };

  await send(ws, 'Page.navigate', { url: BASE + '/login' });
  await sleep(1500);
  await evalJs(`localStorage.setItem('token', ${JSON.stringify(TOKEN)})`);

  const shots = [];
  const pages = [
    ['jhyyfaqi', '/jhyyfaqi'],
    ['jhssdb', '/jhssdb'],
    ['jhsshz', '/jhsshz'],
    ['plan', '/plan'],
    ['plan2026', '/plan?nd=2026'],
    ['dashboard', '/plan/dashboard'],
  ];
  for (const [name, route] of pages) {
    const before = errors.length;
    await send(ws, 'Page.navigate', { url: BASE + route });
    await sleep(2600);
    const info = await evalJs(`(() => {
      const table = document.querySelector('.el-table');
      const rows = document.querySelectorAll('.el-table__body tbody tr').length;
      const title = document.querySelector('.title, .banner-title')?.innerText || '';
      return { rows, title: title.slice(0, 120), hasTable: !!table, text: document.body.innerText.slice(0, 200) };
    })()`);
    const shot = path.join(SHOT_DIR, name + '.png');
    const data = await send(ws, 'Page.captureScreenshot', { format: 'png' });
    fs.writeFileSync(shot, Buffer.from(data.data, 'base64'));
    shots.push(shot);
    console.log(`[${name}] rows=${info.rows} table=${info.hasTable} newErrors=${errors.length - before}`);
    console.log('  title:', info.title.replace(/\n/g, ' | '));
  }

  // 打开实施单表添加弹窗
  await send(ws, 'Page.navigate', { url: BASE + '/jhssdb' });
  await sleep(2200);
  const clicked = await evalJs(`(() => {
    const b = [...document.querySelectorAll('button')].find((x) => x.innerText.trim() === '添加计划');
    if (!b) return 'no-button';
    b.click();
    return 'clicked';
  })()`);
  await sleep(700);
  const dialog = await evalJs(`(() => {
    const d = [...document.querySelectorAll('.el-dialog')].find((x) => x.offsetParent !== null);
    return d ? d.innerText.slice(0, 160) : 'no-dialog';
  })()`);
  console.log('[jhssdb-dialog]', clicked, '->', dialog.replace(/\n/g, ' | '));
  const dlgShot = path.join(SHOT_DIR, 'jhssdb-dialog.png');
  const data2 = await send(ws, 'Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(dlgShot, Buffer.from(data2.data, 'base64'));

  console.log('\nERRORS:', errors.length);
  for (const e of errors.slice(0, 30)) console.log(' -', e.slice(0, 500));
  cleanup();
  process.exit(errors.length ? 1 : 0);
}

main().catch((e) => { console.error(e); process.exit(2); });
