// Drives the scratch server (scripts/dev/scratch_server.sh) in headless Chrome:
// lists the chat picker, sends one message, prints the reply caption and the
// thinking label, and saves screenshots. Needs puppeteer-core:
//   NODE_PATH=/path/to/node_modules node scripts/dev/ui_check.js OUT_DIR [PORT]
const puppeteer = require('puppeteer-core');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const S = process.argv[2] || '.';
const PORT = process.argv[3] || '7863';
(async () => {
  const browser = await puppeteer.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: 'new' });
  const page = await browser.newPage();
  await page.setViewport({ width: 1320, height: 860 });
  const errs = [];
  page.on('pageerror', e => errs.push('pageerror ' + e.message));
  await page.goto(`http://127.0.0.1:${PORT}/`, { waitUntil: 'networkidle2' });
  await sleep(2000);
  await page.evaluate(() => document.getElementById('model-picker-btn').click());
  await sleep(700);
  await page.evaluate(() => { const t = document.querySelector('[data-mp-tab="all"]'); if (t) t.click(); });
  for (let i = 0; i < 20; i++) { if (await page.evaluate(() => document.querySelectorAll('.mp-model-name').length)) break; await sleep(500); }
  const names = await page.evaluate(() => [...document.querySelectorAll('.mp-model-name')].map(x => x.textContent));
  console.log('picker rows:', JSON.stringify(names));
  await page.screenshot({ path: S + '/ui-picker.png' });
  await page.evaluate(() => { const n = [...document.querySelectorAll('.mp-model-name')].find(x => x.textContent.includes('big-chat')); n.closest('[class]').click(); });
  await sleep(1500);
  await page.focus('#message'); await page.keyboard.type('hello'); await page.keyboard.press('Enter');
  await sleep(5000);
  const info = await page.evaluate(() => {
    const roles = [...document.querySelectorAll('#chat-history .msg-ai .role')].map(r => r.textContent.trim());
    const think = [...document.querySelectorAll('.thinking-header-left span')].map(r => r.textContent.trim());
    return { roles, think };
  });
  console.log('assistant captions:', JSON.stringify(info.roles));
  console.log('thinking labels:', JSON.stringify(info.think));
  // toggle open/closed: label must stay put
  const toggled = await page.evaluate(() => { const h = document.querySelector('.thinking-header'); if (!h) return null; h.click(); return document.querySelector('.thinking-header-left span').textContent.trim(); });
  console.log('after expanding:', toggled);
  await sleep(500);
  await page.screenshot({ path: S + '/ui-chat.png' });
  console.log('page errors:', JSON.stringify(errs));
  await browser.close();
})();
