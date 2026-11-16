'use strict';
// 传导完好率 4 页面 CDP 真机回归:注入登录态 → /cdwhl /cdgz /cddaxiu /cdbd →
// 冷刷新收集 JS 异常 → 菜单/标题/表头/按钮/滚动条 → 打开主弹窗 → 截图
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9356;
const BASE = 'http://127.0.0.1:5173';
const TOKEN = process.argv[2] || '';

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

const PAGES = [
  { key: 'cdwhl', path: '/cdwhl', title: '传导完好率', head: '传导设备完好率统计汇总表',
    minCols: 14, openBtn: null, dlgTitle: '编辑备注', dblclick: true },
  { key: 'cdgz', path: '/cdgz', title: '传导故障', head: '传导设备故障明细表',
    minCols: 13, openBtn: '添加', dlgTitle: '添加传导设备故障' },
  { key: 'cddaxiu', path: '/cddaxiu', title: '传导大修', head: '传导设备大修/更新记录',
    minCols: 17, openBtn: '添加', dlgTitle: '添加传导设备大修' },
  { key: 'cdbd', path: '/cdbd', title: '传导变动表', head: '传导设备变动明细表',
    minCols: 8, openBtn: '添加', dlgTitle: '新增变动明细' },
];

(async function main() {
  if (!TOKEN) { console.error('缺少 token 参数'); process.exit(2); }
  const udd = fs.mkdtempSync(path.join(os.tmpdir(), 'cdp-cd-'));
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
  let errors = [];
  ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.method === 'Runtime.exceptionThrown') {
      errors.push(String(msg.params.exceptionDetails.exception?.description
        || msg.params.exceptionDetails.text));
    }
    if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error') {
      const e = msg.params.entry;
      if (!String(e.url || '').includes('favicon.ico')) {
        errors.push('log: ' + String(e.url || '') + ' ' + String(e.text || ''));
      }
    }
    if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') {
      errors.push('console: ' + msg.params.args.map((a) => a.value || a.description || '').join(' '));
    }
  });
  await send(ws, 'Runtime.enable');
  await send(ws, 'Log.enable');
  await send(ws, 'Page.enable');

  async function goto(url) {
    await send(ws, 'Page.navigate', { url });
    await sleep(1500);
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

  const out = [];
  for (const p of PAGES) {
    await goto(`${BASE}${p.path}`);
    await sleep(1200);
    errors = [];
    await send(ws, 'Page.reload', { ignoreCache: true });
    await sleep(2200);

    const info = await evalJs(`(() => {
      const wrap = document.querySelector('.el-table__body-wrapper .el-scrollbar__wrap');
      const body = document.querySelector('.el-table__body-wrapper');
      const headers = [...document.querySelectorAll('.el-table__header-wrapper th')]
        .map(th => th.textContent.trim()).filter(Boolean);
      const btns = [...document.querySelectorAll('.toolbar button.el-button')]
        .map(b => b.textContent.trim());
      return {
        headerTitle: document.querySelector('.header-title')?.textContent.trim() || '',
        pageTitle: document.querySelector('.page-title')?.textContent.trim() || '',
        headers, headerCount: headers.length,
        rows: document.querySelectorAll('.el-table__body tbody tr').length,
        footer: (document.querySelector('.el-table__footer-wrapper')?.textContent || '')
          .replace(/\\s+/g, ' ').trim().slice(0, 100),
        buttons: btns,
        menuGroup: [...document.querySelectorAll('.el-sub-menu__title')]
          .some(e => e.textContent.includes('传导完好率')),
        menuItems: [...document.querySelectorAll('.el-menu-item')]
          .map(e => e.textContent.trim())
          .filter(t => ['传导完好率','传导故障','传导大修','传导变动表'].includes(t)),
        monthValue: document.querySelector('.filter-form input[placeholder="选择月份"]')?.value || '',
        noPageScroll: document.documentElement.scrollHeight <= document.documentElement.clientHeight + 1,
        noTableHScroll: wrap ? wrap.scrollWidth <= wrap.clientWidth + 1
          : (body ? body.scrollWidth <= body.clientWidth + 1 : true),
        tableScrollW: wrap ? Math.round(wrap.scrollWidth) : 0,
        tableClientW: wrap ? Math.round(wrap.clientWidth) : 0,
        url: location.pathname,
      };
    })()`);

    // 切到历史有数据的月份(2026-10),验证表格/合计行真实渲染;
    // 开发模式下 Vue 组件实例挂在 DOM.__vueParentComponent.setupState
    const dataView = await evalJs(`(() => {
      const root = document.querySelector('[class$="-page"]');
      const vm = root && root.__vueParentComponent;
      if (!vm || !vm.setupState || !vm.setupState.filters) return { ok: false };
      vm.setupState.filters.rq = '2026-10';
      vm.setupState.load();
      return { ok: true };
    })()`);
    await sleep(1400);
    info.withData = await evalJs(`(() => ({
      rows: document.querySelectorAll('.el-table__body tbody tr').length,
      firstRow: (document.querySelector('.el-table__body tbody tr')?.textContent || '')
        .replace(/\\s+/g, ' ').trim().slice(0, 90),
      footer: (document.querySelector('.el-table__footer-wrapper')?.textContent || '')
        .replace(/\\s+/g, ' ').trim().slice(0, 110),
      noTableHScroll: (() => {
        const w = document.querySelector('.el-table__body-wrapper .el-scrollbar__wrap');
        return w ? w.scrollWidth <= w.clientWidth + 1 : true;
      })(),
    }))()`);
    info.dataView = dataView;

    // 打开主弹窗:完好率双击首行(编辑备注),其余点「添加」
    if (p.dblclick) {
      await evalJs(`(() => {
        const tr = document.querySelector('.el-table__body tbody tr');
        if (!tr) return false;
        tr.dispatchEvent(new MouseEvent('dblclick', { bubbles: true }));
        return true;
      })()`);
    } else {
      await evalJs(`(() => {
        const b = [...document.querySelectorAll('.toolbar button.el-button')]
          .find(x => x.textContent.trim() === ${JSON.stringify(p.openBtn)});
        if (!b) return false;
        b.click(); return true;
      })()`);
    }
    await sleep(900);
    const dlg = await evalJs(`(() => {
      const d = [...document.querySelectorAll('.el-dialog')]
        .find(x => getComputedStyle(x).display !== 'none');
      if (!d) return { open: false };
      return {
        open: true,
        title: (d.querySelector('.el-dialog__title')?.textContent || '').trim(),
        classStd: d.closest('.el-overlay')?.querySelector('.std-dialog') !== null
          || d.classList.contains('std-dialog'),
        fields: [...d.querySelectorAll('.el-form-item')]
          .map(f => (f.querySelector('label')?.textContent || '').trim()).filter(Boolean),
        inputs: d.querySelectorAll('input,textarea').length,
        footerBtns: [...d.querySelectorAll('.el-dialog__footer button')]
          .map(b => b.textContent.trim()),
      };
    })()`);
    const geom = await evalJs(`(() => {
      const d = [...document.querySelectorAll('.el-dialog')]
        .find(x => getComputedStyle(x).display !== 'none');
      const r = d ? d.getBoundingClientRect() : null;
      return {
        dialogBottom: r ? Math.round(r.bottom) : 0,
        viewportH: window.innerHeight,
        pageScrollH: document.documentElement.scrollHeight,
        pageClientH: document.documentElement.clientHeight,
        bodyOverflow: getComputedStyle(document.body).overflow,
      };
    })()`);
    dlg.geom = geom;

    const shot = path.join(__dirname, `ui_cd_${p.key}.png`);
    await send(ws, 'Page.captureScreenshot', { format: 'png' }).then((r) => {
      fs.writeFileSync(shot, Buffer.from(r.data, 'base64'));
    });
    out.push({ page: p.path, ...info, dialog: dlg, shot, jsErrors: errors });
  }
  console.log(JSON.stringify(out, null, 2));
  cleanup();
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
