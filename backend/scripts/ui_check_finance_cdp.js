'use strict';
// 财务管理三页面 CDP 真机回归:注入登录态 → /gdzc /baofeizc /wzcgsq →
// 冷刷新收集 JS 异常 → 菜单/标题/表格/合计行/滚动条 → 打开主弹窗 → 截图
const http = require('http');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawn } = require('child_process');

const CHROME = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 9355;
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

// text 用顶栏标题(页面内重复标题已精简,只保留 MainLayout 的 header-title)
const PAGES = [
  { key: 'gdzc', path: '/gdzc', text: '固定资产', button: '导入盘点文件',
    dlgTitle: '导入盘点文件' },
  { key: 'baofeizc', path: '/baofeizc', text: '清理报告', button: '添加报废单',
    dlgTitle: '报废单' },
  { key: 'wzcgsq', path: '/wzcgsq', text: '物资采购申请', button: '添加采购单',
    dlgTitle: '采购单' },
];

(async function main() {
  if (!TOKEN) { console.error('缺少 token 参数'); process.exit(2); }
  const udd = fs.mkdtempSync(path.join(os.tmpdir(), 'cdp-fin-'));
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
  let logs = [];
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
      logs.push('console: ' + msg.params.args.map((a) => a.value || a.description || '').join(' '));
    }
  });
  await send(ws, 'Runtime.enable');
  await send(ws, 'Log.enable');
  await send(ws, 'Page.enable');

  async function goto(url) {
    await send(ws, 'Page.navigate', { url });
    await sleep(1600);
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
    await sleep(1800);
    // Vite HMR / 其它模块 TDZ 噪声:冷刷新后清空计数,只统计稳定加载后的异常
    errors = []; logs = [];
    await send(ws, 'Page.reload', { ignoreCache: true });
    await sleep(2600);

    const info = await evalJs(`(() => {
      const wrap = document.querySelector('.el-table__body-wrapper .el-scrollbar__wrap');
      const w = document.querySelector('.el-table__body-wrapper');
      const headerTitle = document.querySelector('.header-title')?.textContent.trim() || '';
      return {
        hitText: headerTitle === ${JSON.stringify(p.text)},
        headerTitle,
        // 表头列清单:确认 22 列完整(含曾被隐藏的规格型号/设备编号/期限/已用/备注人/备注日期)
        headers: [...document.querySelectorAll('.el-table__header-wrapper th')]
          .map(th => th.textContent.trim()).filter(Boolean),
        rows: document.querySelectorAll('.el-table__body tbody tr').length,
        footer: (document.querySelector('.el-table__footer-wrapper')?.textContent || '')
          .replace(/\\s+/g, ' ').trim().slice(0, 120),
        menuGroup: [...document.querySelectorAll('.el-sub-menu__title')]
          .some(e => e.textContent.includes('财务管理')),
        menuItems: [...document.querySelectorAll('.el-menu-item')]
          .map(e => e.textContent.trim()).filter(t =>
            t.includes('固定资产') || t.includes('清理报告') || t.includes('物资采购申请')),
        // 左侧菜单紧凑度:分组标题/一级项 40px,展开子项 34px
        menuHeights: (() => {
          const h = (els) => [...new Set([...els]
            .filter(e => e.getBoundingClientRect().height > 0)
            .map(e => Math.round(e.getBoundingClientRect().height)))];
          return {
            top: h(document.querySelectorAll('.menu > .el-menu-item, .menu > .el-sub-menu > .el-sub-menu__title')),
            sub: h(document.querySelectorAll('.el-menu--inline .el-menu-item')),
            subCount: document.querySelectorAll('.el-menu--inline .el-menu-item').length,
          };
        })(),
        noPageScroll: document.documentElement.scrollHeight <= document.documentElement.clientHeight + 1,
        noTableHScroll: wrap ? wrap.scrollWidth <= wrap.clientWidth + 1
          : (w ? w.scrollWidth <= w.clientWidth + 1 : true),
        tableScrollW: wrap ? Math.round(wrap.scrollWidth) : (w ? Math.round(w.scrollWidth) : 0),
        tableClientW: wrap ? Math.round(wrap.clientWidth) : (w ? Math.round(w.clientWidth) : 0),
        // 工具栏按钮:要求全部同一行(top 一致)、同一高度(32px)
        toolbarBtns: (() => {
          const t = document.querySelector('.toolbar');
          if (!t) return null;
          const bs = [...t.querySelectorAll('button.el-button')];
          return {
            count: bs.length,
            heights: [...new Set(bs.map(b => Math.round(b.getBoundingClientRect().height)))],
            tops: [...new Set(bs.map(b => Math.round(b.getBoundingClientRect().top)))],
          };
        })(),
        url: location.pathname,
      };
    })()`);

    // 列表态截图(弹窗打开前,便于检查列宽/表格滚动)
    const listShot = path.join(__dirname, `ui_finance_${p.key}_list.png`);
    await send(ws, 'Page.captureScreenshot', { format: 'png' }).then((r) => {
      fs.writeFileSync(listShot, Buffer.from(r.data, 'base64'));
    });

    // 侧栏菜单紧凑度:单独截一张左侧 220px 菜单区(当前路由所在分组自动展开)
    if (p.key === 'gdzc') {
      const menuShot = path.join(__dirname, 'ui_layout_menu.png');
      await send(ws, 'Page.captureScreenshot', {
        format: 'png', clip: { x: 0, y: 0, width: 220, height: 740, scale: 1 },
      }).then((r) => { fs.writeFileSync(menuShot, Buffer.from(r.data, 'base64')); });
    }

    // 固定资产列多:另截一张横向滚动后的右侧列(规格型号/设备编号/备注等)
    if (p.key === 'gdzc') {
      await evalJs(`(() => {
        const wrap = document.querySelector('.el-table__body-wrapper .el-scrollbar__wrap');
        if (wrap) wrap.scrollLeft = 1180;
        return wrap ? wrap.scrollLeft : -1;
      })()`);
      await sleep(350);
      const colShot = path.join(__dirname, 'ui_finance_gdzc_cols.png');
      await send(ws, 'Page.captureScreenshot', { format: 'png' }).then((r) => {
        fs.writeFileSync(colShot, Buffer.from(r.data, 'base64'));
      });
      await evalJs(`(() => {
        const wrap = document.querySelector('.el-table__body-wrapper .el-scrollbar__wrap');
        if (wrap) wrap.scrollLeft = 0;
        return true;
      })()`);
      await sleep(200);
    }

    // 打开该页的主弹窗
    await evalJs(`(() => {
      const b = [...document.querySelectorAll('button')]
        .find(b => b.textContent.trim().includes(${JSON.stringify(p.button)}));
      if (b) b.click(); return !!b;
    })()`);
    await sleep(900);
    const dlg = await evalJs(`(() => {
      const d = document.querySelector('.std-dialog');
      return {
        title: document.querySelector('.std-dialog .el-dialog__title')?.textContent.trim() || '',
        height: Math.round(d?.getBoundingClientRect().height || 0),
        bodyNoScroll: (() => { const b = document.querySelector('.std-dialog .el-dialog__body');
          return b ? b.scrollHeight <= b.clientHeight + 1 : false; })(),
        items: document.querySelectorAll('.std-dialog .el-form-item').length,
      };
    })()`);

    // 采购单明细表:最后一行按 ↓ 追加一行并聚焦新行首格;中间行按 ↓ 只移动焦点
    let downKey = null;
    if (p.key === 'wzcgsq') {
      await evalJs(`(() => {
        const rows = [...document.querySelectorAll('.mx-wrap tbody tr')]
          .filter(tr => tr.querySelector('input.cell-input'));
        const first = rows[0]?.querySelector('input.cell-input');
        first?.focus();
        first?.dispatchEvent(new KeyboardEvent('keydown',
          { key: 'ArrowDown', bubbles: true, cancelable: true }));
        return rows.length;
      })()`);
      await sleep(300);
      downKey = await evalJs(`(() => {
        const rows = [...document.querySelectorAll('.mx-wrap tbody tr')]
          .filter(tr => tr.querySelector('input.cell-input'));
        const last = rows[rows.length - 1];
        return {
          rows: rows.length,
          focusNewFirstCell: document.activeElement === last?.querySelector('input.cell-input'),
        };
      })()`);
      await evalJs(`(() => {
        const rows = [...document.querySelectorAll('.mx-wrap tbody tr')]
          .filter(tr => tr.querySelector('input.cell-input'));
        const first = rows[0].querySelector('input.cell-input');
        first.focus();
        first.dispatchEvent(new KeyboardEvent('keydown',
          { key: 'ArrowDown', bubbles: true, cancelable: true }));
        return true;
      })()`);
      await sleep(150);
      downKey.nav = await evalJs(`(() => {
        const rows = [...document.querySelectorAll('.mx-wrap tbody tr')]
          .filter(tr => tr.querySelector('input.cell-input'));
        return {
          rows: rows.length,
          focusSecondRow: document.activeElement === rows[1]?.querySelector('input.cell-input'),
        };
      })()`);
    }

    const shot = path.join(__dirname, `ui_finance_${p.key}.png`);
    await send(ws, 'Page.captureScreenshot', { format: 'png' }).then((r) => {
      fs.writeFileSync(shot, Buffer.from(r.data, 'base64'));
    });
    out.push({ page: p.path, ...info, dialog: dlg, downKey, shot,
      jsErrors: errors.concat(logs) });
  }
  console.log(JSON.stringify(out, null, 2));
  cleanup();
  process.exit(0);
})().catch((e) => { console.error(e); process.exit(1); });
